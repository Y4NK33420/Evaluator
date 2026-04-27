"""Code-evaluator Celery task — full lifecycle with grade write-back.

Changes vs. original skeleton:
  - Grade row is written in FINALIZING state so completed jobs produce a grades record
  - Structured transition logging at every state change
  - job.error_message includes exception type for operator triage
  - shim_warning surfaced in final_result_json when AI model was unavailable
  - Environment freeze-key pre-check: warns if env version is not ready
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.models import (
    Assignment,
    CodeEvalAttempt,
    CodeEvalEnvironmentStatus,
    CodeEvalEnvironmentVersion,
    CodeEvalJob,
    CodeEvalJobStatus,
    Grade,
    GradeSource,
    Submission,
    SubmissionStatus,
)
from app.services.code_eval.contracts import AttemptResult, CodeEvalJobRequest, CodeEvalJobResult
from app.services.code_eval.execution_service import execute_code_eval_job
from app.services.code_eval.language_config import parse_language_config
from app.services.code_eval.quality_service import evaluate_code_quality
from app.services.code_eval.scoring_service import build_score_breakdown
from app.services.code_eval.shim_service import (
    analyze_for_retrying_shim,
    build_retry_request_from_shim_decision,
)
from app.services.code_eval.static_analysis import run_static_analysis_gate
from app.services.code_eval.state_machine import CodeEvalJobState, validate_transition
from app.workers.celery_app import celery_app

log = logging.getLogger(__name__)
settings = get_settings()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_state(status: CodeEvalJobStatus) -> CodeEvalJobState:
    return CodeEvalJobState(status.value)


def _transition(job: CodeEvalJob, next_state: CodeEvalJobState) -> None:
    current = _as_state(job.status)
    validate_transition(current, next_state)
    job.status = CodeEvalJobStatus(next_state.value)

    if next_state == CodeEvalJobState.EXECUTING_RAW and job.started_at is None:
        job.started_at = _now()
    if next_state in {CodeEvalJobState.COMPLETED, CodeEvalJobState.FAILED}:
        job.finished_at = _now()

    log.info(
        "code_eval_transition job=%s from=%s to=%s",
        job.id, current.value, next_state.value,
    )


def _transition_to_failed(job: CodeEvalJob) -> None:
    current = _as_state(job.status)

    if current == CodeEvalJobState.QUEUED:
        _transition(job, CodeEvalJobState.EXECUTING_RAW)
        current = _as_state(job.status)

    if current in {
        CodeEvalJobState.EXECUTING_RAW,
        CodeEvalJobState.AI_ANALYZING,
        CodeEvalJobState.RETRYING_SHIM,
    }:
        _transition(job, CodeEvalJobState.FINALIZING)
        current = _as_state(job.status)

    if current == CodeEvalJobState.FINALIZING:
        _transition(job, CodeEvalJobState.FAILED)


def _record_attempt(
    db: Session,
    job: CodeEvalJob,
    *,
    attempt_index: int,
    attempt_result: AttemptResult,
    execution_artifacts: dict,
    started_at: datetime,
) -> None:
    attempt = CodeEvalAttempt(
        job_id=job.id,
        attempt_index=attempt_index,
        stage=attempt_result.stage,
        passed=attempt_result.passed,
        exit_code=attempt_result.exit_code,
        score=attempt_result.score,
        stdout=attempt_result.stdout,
        stderr=attempt_result.stderr,
        shim_used=attempt_result.shim_used,
        shim_source=attempt_result.shim_source,
        artifacts_json=execution_artifacts,
        started_at=started_at,
        finished_at=_now(),
    )
    db.add(attempt)
    job.attempt_count = attempt_index


def _write_grade(
    db: Session,
    job: CodeEvalJob,
    score_breakdown: dict,
    quality_payload: dict,
    max_score: float,
) -> Grade | None:
    """Write a Grade row for the completed code-eval job. Returns Grade or None on failure."""
    try:
        # Deactivate any existing active grade rows for this submission
        db.query(Grade).filter(
            Grade.submission_id == job.submission_id,
            Grade.active_version == True,
        ).update({"active_version": False}, synchronize_session=False)

        grade = Grade(
            submission_id=job.submission_id,
            active_version=True,
            total_score=float(score_breakdown.get("total_score", 0.0)),
            breakdown_json={
                "source": "code_eval",
                "job_id": str(job.id),
                "assignment_id": str(job.assignment_id),
                "score_breakdown": score_breakdown,
                "quality_evaluation": quality_payload,
                "attempt_count": job.attempt_count,
                "max_score": max_score,
            },
            source=GradeSource.code_eval,
            is_truncated=False,
        )
        db.add(grade)
        db.flush()  # populate grade.id before linking
        job.grade_id = str(grade.id)
        log.info(
            "code_eval grade_write job=%s grade_id=%s score=%.4f",
            job.id, grade.id, grade.total_score,
        )
        return grade
    except Exception as exc:
        log.error(
            "code_eval grade_write FAILED for job=%s: [%s] %s",
            job.id, type(exc).__name__, exc,
        )
        # Grade write failure is non-fatal — job still completes, but we surface it
        return None


def _check_environment_ready(db: Session, job: CodeEvalJob) -> str | None:
    """Return a warning string if the linked environment version is not ready, else None."""
    if job.environment_version_id is None:
        return None
    try:
        env = db.get(type(job.environment_version), job.environment_version_id)
        if env is None:
            return f"environment_version {job.environment_version_id} not found in DB"
        if env.status != CodeEvalEnvironmentStatus.ready:
            return (
                f"environment_version {job.environment_version_id} status={env.status.value} "
                f"(expected 'ready'). freeze_key may be absent."
            )
    except Exception as exc:
        return f"environment_version lookup failed: {exc}"
    return None


@celery_app.task(
    name="app.workers.code_eval_tasks.run_code_eval_job_task",
    bind=True,
    max_retries=0,
)
def run_code_eval_job_task(self, job_id: str):
    """Advance one code-eval job through the full lifecycle with grade write-back."""
    db: Session = SessionLocal()
    try:
        job = db.get(CodeEvalJob, job_id)
        if job is None:
            log.error("code_eval: job %s not found in DB", job_id)
            return

        log.info(
            "code_eval_start job=%s assignment=%s submission=%s language=%s",
            job_id, job.assignment_id, job.submission_id, job.language,
        )

        # Warn if environment is not ready (non-fatal, job proceeds)
        env_warning = _check_environment_ready(db, job)
        if env_warning:
            log.warning("code_eval env_check job=%s: %s", job_id, env_warning)

        request = CodeEvalJobRequest.model_validate(job.request_json)

        # ── Language config validation (gate) ──────────────────────────────────
        # Resolve the env version's spec_json from DB and validate language_config
        # BEFORE any execution starts. This is the authoritative validation point
        # because request.environment (EnvironmentSpec) does NOT carry spec_json.
        env_version: CodeEvalEnvironmentVersion | None = None
        if job.environment_version_id:
            env_version = db.get(CodeEvalEnvironmentVersion, job.environment_version_id)
        env_spec_json = env_version.spec_json if env_version else None

        try:
            parse_language_config(env_spec_json, job_language=request.language.value)
        except ValueError as cfg_err:
            log.error(
                "code_eval job=%s: language_config validation failed lang=%s: %s",
                job_id, request.language.value, cfg_err,
            )
            _transition(job, CodeEvalJobState.EXECUTING_RAW)
            cfg_fail_result = AttemptResult(
                stage=CodeEvalJobState.EXECUTING_RAW.value,
                passed=False,
                exit_code=-1,
                stderr=f"language_config validation failed: {cfg_err}",
                score=0.0,
            )
            cfg_artifacts = {
                "executor": "config_validator",
                "error_code": "configuration_error",
                "comparison_mode": "strict",
                "testcases": [
                    {
                        "testcase_id": t.testcase_id,
                        "passed": False,
                        "weight": float(t.weight),
                        "awarded_score": 0.0,
                        "exit_code": -1,
                        "stdout": "",
                        "stderr": str(cfg_err),
                        "failure_reason": "configuration_error",
                        "output_truncated": False,
                    }
                    for t in request.testcases
                ],
            }
            _record_attempt(
                db, job,
                attempt_index=job.attempt_count + 1,
                attempt_result=cfg_fail_result,
                execution_artifacts=cfg_artifacts,
                started_at=_now(),
            )
            db.commit()
            _transition(job, CodeEvalJobState.FINALIZING)
            job.final_result_json = {
                "job_id": job.id,
                "submission_id": job.submission_id,
                "status": "FAILED",
                "error_code": "configuration_error",
                "attempts": [cfg_fail_result.model_dump(mode="json")],
                "attempt_artifacts": [{
                    "attempt_index": 1,
                    "stage": cfg_fail_result.stage,
                    "shim_used": False,
                    "executor": "config_validator",
                    "error_code": "configuration_error",
                    "comparison_mode": "strict",
                    "testcases": cfg_artifacts["testcases"],
                }],
            }
            job.error_message = (
                f"[configuration_error] language_config.{request.language.value} "
                f"has invalid keys: {cfg_err}"
            )
            _transition(job, CodeEvalJobState.FAILED)
            db.commit()
            log.info("code_eval job=%s failed language_config validation", job_id)
            return

        static_analysis = run_static_analysis_gate(request)
        if bool(static_analysis.get("blocked")):
            _transition(job, CodeEvalJobState.EXECUTING_RAW)
            db.commit()

            blocked_started_at = _now()
            blocked_attempt_result = AttemptResult(
                stage=CodeEvalJobState.EXECUTING_RAW.value,
                passed=False,
                exit_code=40,
                stderr="Static analysis blocked execution due to forbidden patterns.",
                score=0.0,
            )
            blocked_artifacts = {
                "executor": "static_analysis_gate",
                "error_code": "static_analysis_blocked",
                "comparison_mode": "strict",
                "blocked": True,
                "language": request.language.value,
                "violations": static_analysis.get("violations") or [],
            }
            blocked_attempt_index = job.attempt_count + 1
            _record_attempt(
                db, job,
                attempt_index=blocked_attempt_index,
                attempt_result=blocked_attempt_result,
                execution_artifacts=blocked_artifacts,
                started_at=blocked_started_at,
            )
            db.commit()

            _transition(job, CodeEvalJobState.FINALIZING)
            job.final_result_json = {
                "job_id": job.id,
                "submission_id": job.submission_id,
                "status": "FAILED",
                "error_code": "static_analysis_blocked",
                "attempts": [blocked_attempt_result.model_dump(mode="json")],
                "attempt_artifacts": [{
                    "attempt_index": blocked_attempt_index,
                    "stage": blocked_attempt_result.stage,
                    "shim_used": False,
                    "executor": "static_analysis_gate",
                    "error_code": "static_analysis_blocked",
                    "comparison_mode": "strict",
                }],
                "static_analysis": static_analysis,
            }
            job.error_message = f"[static_analysis_blocked] {blocked_attempt_result.stderr}"
            _transition(job, CodeEvalJobState.FAILED)
            db.commit()
            log.info("code_eval job=%s blocked by static-analysis gate", job_id)
            return

        # ── Raw execution ─────────────────────────────────────────────────────
        _transition(job, CodeEvalJobState.EXECUTING_RAW)
        db.commit()

        raw_started_at = _now()
        raw_attempt_result, raw_execution_artifacts = execute_code_eval_job(
            request,
            stage=CodeEvalJobState.EXECUTING_RAW.value,
        )
        final_execution_artifacts = raw_execution_artifacts
        raw_attempt_index = job.attempt_count + 1
        _record_attempt(
            db, job,
            attempt_index=raw_attempt_index,
            attempt_result=raw_attempt_result,
            execution_artifacts=raw_execution_artifacts,
            started_at=raw_started_at,
        )
        db.commit()

        attempts_for_result = [raw_attempt_result]
        attempt_artifacts = [{
            "attempt_index": raw_attempt_index,
            "stage": raw_attempt_result.stage,
            "shim_used": raw_attempt_result.shim_used,
            "executor": raw_execution_artifacts.get("executor"),
            "error_code": raw_execution_artifacts.get("error_code"),
            "comparison_mode": raw_execution_artifacts.get("comparison_mode", "strict"),
        }]
        shim_decision: dict | None = None
        shim_warning: dict | None = None

        final_attempt_result = raw_attempt_result

        # ── AI Shim retry ─────────────────────────────────────────────────────
        log.info(f"code_eval job={job_id}: raw_passed={raw_attempt_result.passed}, shim_retry_enabled={settings.code_eval_enable_shim_retry}, ai_shim_enabled={settings.code_eval_enable_ai_shim_generation}")
        if not raw_attempt_result.passed and settings.code_eval_enable_shim_retry:
            shim_decision = analyze_for_retrying_shim(request, raw_execution_artifacts)

            # Surface shim_warning even if not eligible (e.g. model was down)
            shim_warning = shim_decision.get("shim_warning")

            log.info(f"code_eval job={job_id}: shim_decision eligible={shim_decision.get('eligible')} reason={shim_decision.get('reason')}")
            if bool(shim_decision.get("eligible")):
                _transition(job, CodeEvalJobState.AI_ANALYZING)
                db.commit()

                _transition(job, CodeEvalJobState.RETRYING_SHIM)
                db.commit()

                retry_request = build_retry_request_from_shim_decision(request, shim_decision)

                retry_started_at = _now()
                retry_attempt_result, retry_execution_artifacts = execute_code_eval_job(
                    retry_request,
                    stage=CodeEvalJobState.RETRYING_SHIM.value,
                    comparison_mode=str(shim_decision.get("comparison_mode") or "strict"),
                    shim_used=True,
                    shim_source=shim_decision.get("shim_source"),
                )
                retry_attempt_index = job.attempt_count + 1
                _record_attempt(
                    db, job,
                    attempt_index=retry_attempt_index,
                    attempt_result=retry_attempt_result,
                    execution_artifacts=retry_execution_artifacts,
                    started_at=retry_started_at,
                )
                db.commit()

                attempts_for_result.append(retry_attempt_result)
                attempt_artifacts.append({
                    "attempt_index": retry_attempt_index,
                    "stage": retry_attempt_result.stage,
                    "shim_used": retry_attempt_result.shim_used,
                    "shim_strategy": shim_decision.get("shim_strategy"),
                    "shim_reason": shim_decision.get("reason"),
                    "shim_model": shim_decision.get("model"),
                    "shim_prompt_hash": shim_decision.get("prompt_hash"),
                    "executor": retry_execution_artifacts.get("executor"),
                    "error_code": retry_execution_artifacts.get("error_code"),
                    "comparison_mode": retry_execution_artifacts.get("comparison_mode", "strict"),
                })
                final_attempt_result = retry_attempt_result
                final_execution_artifacts = retry_execution_artifacts

        # ── Finalizing ────────────────────────────────────────────────────────
        _transition(job, CodeEvalJobState.FINALIZING)

        assignment = db.get(Assignment, job.assignment_id)
        assignment_max_marks = float(assignment.max_marks) if assignment and assignment.max_marks else 100.0

        raw_max = float(sum(test.weight for test in request.testcases))
        raw_score = float(final_attempt_result.score)

        scale_factor = assignment_max_marks / raw_max if raw_max > 0 else 0.0
        scaled_score = raw_score * scale_factor

        if final_attempt_result.passed:
            quality_payload = evaluate_code_quality(
                request,
                earned_score=scaled_score,
                max_score=assignment_max_marks,
                execution_artifacts=final_execution_artifacts,
            )
            score_breakdown = build_score_breakdown(
                correctness_score=scaled_score,
                max_score=assignment_max_marks,
                quality_payload=quality_payload,
            )
            final_score = float(score_breakdown.get("total_score", scaled_score))

            final_result = CodeEvalJobResult(
                job_id=job.id,
                submission_id=job.submission_id,
                total_score=final_score,
                max_score=assignment_max_marks,
                status="COMPLETED",
                attempts=attempts_for_result,
            )
            final_payload = final_result.model_dump(mode="json")
            final_payload["attempt_artifacts"] = attempt_artifacts
            final_payload["quality_evaluation"] = quality_payload
            final_payload["score_breakdown"] = score_breakdown
            if shim_decision is not None:
                final_payload["shim_decision"] = shim_decision
            if shim_warning is not None:
                final_payload["shim_warning"] = shim_warning

            job.final_result_json = final_payload
            job.error_message = None

            # ── Grade write-back ──────────────────────────────────────────────
            grade = _write_grade(db, job, score_breakdown, quality_payload, assignment_max_marks)
            if grade is None:
                # Grade write failed — still complete the job but note it
                final_payload["grade_write_warning"] = (
                    "Grade row could not be written. "
                    "Check application logs for error_code=grade_write_failed."
                )
                job.final_result_json = final_payload

            _transition(job, CodeEvalJobState.COMPLETED)

        else:
            failed_quality_payload = {
                "enabled": False,
                "applied": False,
                "reason": "correctness_not_passed",
                "weight_percent": float(request.quality_evaluation.weight_percent),
                "mode": request.quality_evaluation.mode.value,
                "correctness_score": float(scaled_score),
                "max_score": assignment_max_marks,
            }
            failed_score_breakdown = build_score_breakdown(
                correctness_score=scaled_score,
                max_score=assignment_max_marks,
                quality_payload=failed_quality_payload,
            )
            failed_error_code = (
                final_execution_artifacts.get("error_code")
                or (final_attempt_result.stderr.split("|")[0] if final_attempt_result.stderr else None)
                or "execution_failed"
            )
            job.final_result_json = {
                "job_id": job.id,
                "submission_id": job.submission_id,
                "status": "FAILED",
                "error_code": failed_error_code,
                "attempts": [a.model_dump(mode="json") for a in attempts_for_result],
                "attempt_artifacts": attempt_artifacts,
                "shim_decision": shim_decision,
                "quality_evaluation": failed_quality_payload,
                "score_breakdown": failed_score_breakdown,
                **({"shim_warning": shim_warning} if shim_warning else {}),
            }
            job.error_message = (
                f"[{failed_error_code}] "
                + (final_attempt_result.stderr or "Code evaluation failed.")
            )[:2000]
            
            # Grade write-back for partial/failed scores
            grade = _write_grade(db, job, failed_score_breakdown, failed_quality_payload, assignment_max_marks)
            if grade is None:
                job.final_result_json["grade_write_warning"] = "Grade row could not be written."
                
            _transition(job, CodeEvalJobState.FAILED)

        # Update Submission status to graded
        sub = db.get(Submission, job.submission_id)
        if sub:
            sub.status = SubmissionStatus.graded
            
        db.commit()
        log.info(
            "code_eval_finish job=%s state=%s score=%.4f grade_id=%s",
            job_id, job.status.value,
            (job.final_result_json or {}).get("total_score", 0.0),
            job.grade_id,
        )

    except Exception as exc:
        db.rollback()
        log.exception(
            "code_eval_crash job=%s [%s]: %s",
            job_id, type(exc).__name__, exc,
        )
        try:
            job = db.get(CodeEvalJob, job_id)
            if job and _as_state(job.status) not in {CodeEvalJobState.COMPLETED, CodeEvalJobState.FAILED}:
                _transition_to_failed(job)
                job.error_message = f"[{type(exc).__name__}] {exc}"[:2000]
                db.commit()
        except Exception:
            db.rollback()
            log.exception("code_eval: failed to persist terminal FAILED state for job=%s", job_id)
    finally:
        db.close()
