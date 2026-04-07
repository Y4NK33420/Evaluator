"""Code-evaluator Celery task skeleton with strict state-machine transitions."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.models import CodeEvalAttempt, CodeEvalJob, CodeEvalJobStatus
from app.services.code_eval.contracts import CodeEvalJobRequest, CodeEvalJobResult
from app.services.code_eval.execution_service import execute_code_eval_job
from app.services.code_eval.shim_service import analyze_for_retrying_shim
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
    attempt_result,
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


@celery_app.task(
    name="app.workers.code_eval_tasks.run_code_eval_job_task",
    bind=True,
    max_retries=0,
)
def run_code_eval_job_task(self, job_id: str):
    """Advance one code-eval job through the phase-1 skeleton lifecycle."""
    db: Session = SessionLocal()
    try:
        job = db.get(CodeEvalJob, job_id)
        if job is None:
            log.error("Code-eval job %s not found", job_id)
            return

        request = CodeEvalJobRequest.model_validate(job.request_json)

        _transition(job, CodeEvalJobState.EXECUTING_RAW)
        db.commit()

        raw_started_at = _now()
        raw_attempt_result, raw_execution_artifacts = execute_code_eval_job(
            request,
            stage=CodeEvalJobState.EXECUTING_RAW.value,
        )
        raw_attempt_index = job.attempt_count + 1
        _record_attempt(
            db,
            job,
            attempt_index=raw_attempt_index,
            attempt_result=raw_attempt_result,
            execution_artifacts=raw_execution_artifacts,
            started_at=raw_started_at,
        )
        db.commit()

        attempts_for_result = [raw_attempt_result]
        attempt_artifacts = [
            {
                "attempt_index": raw_attempt_index,
                "stage": raw_attempt_result.stage,
                "shim_used": raw_attempt_result.shim_used,
                "executor": raw_execution_artifacts.get("executor"),
                "comparison_mode": raw_execution_artifacts.get("comparison_mode", "strict"),
            }
        ]
        shim_decision: dict | None = None

        final_attempt_result = raw_attempt_result

        if not raw_attempt_result.passed and settings.code_eval_enable_shim_retry:
            shim_decision = analyze_for_retrying_shim(request, raw_execution_artifacts)
            if bool(shim_decision.get("eligible")):
                _transition(job, CodeEvalJobState.AI_ANALYZING)
                db.commit()

                _transition(job, CodeEvalJobState.RETRYING_SHIM)
                db.commit()

                retry_started_at = _now()
                retry_attempt_result, retry_execution_artifacts = execute_code_eval_job(
                    request,
                    stage=CodeEvalJobState.RETRYING_SHIM.value,
                    comparison_mode=str(shim_decision.get("comparison_mode") or "strict"),
                    shim_used=True,
                    shim_source=shim_decision.get("shim_source"),
                )
                retry_attempt_index = job.attempt_count + 1
                _record_attempt(
                    db,
                    job,
                    attempt_index=retry_attempt_index,
                    attempt_result=retry_attempt_result,
                    execution_artifacts=retry_execution_artifacts,
                    started_at=retry_started_at,
                )
                db.commit()

                attempts_for_result.append(retry_attempt_result)
                attempt_artifacts.append(
                    {
                        "attempt_index": retry_attempt_index,
                        "stage": retry_attempt_result.stage,
                        "shim_used": retry_attempt_result.shim_used,
                        "executor": retry_execution_artifacts.get("executor"),
                        "comparison_mode": retry_execution_artifacts.get("comparison_mode", "strict"),
                    }
                )
                final_attempt_result = retry_attempt_result

        _transition(job, CodeEvalJobState.FINALIZING)

        max_score = float(sum(test.weight for test in request.testcases))
        if final_attempt_result.passed:
            final_result = CodeEvalJobResult(
                job_id=job.id,
                submission_id=job.submission_id,
                total_score=final_attempt_result.score,
                max_score=max_score,
                status="COMPLETED",
                attempts=attempts_for_result,
            )
            final_payload = final_result.model_dump(mode="json")
            final_payload["attempt_artifacts"] = attempt_artifacts
            if shim_decision is not None:
                final_payload["shim_decision"] = shim_decision
            job.final_result_json = final_payload
            job.error_message = None
            _transition(job, CodeEvalJobState.COMPLETED)
        else:
            job.final_result_json = {
                "job_id": job.id,
                "submission_id": job.submission_id,
                "status": "FAILED",
                "attempts": [attempt.model_dump(mode="json") for attempt in attempts_for_result],
                "attempt_artifacts": attempt_artifacts,
                "shim_decision": shim_decision,
            }
            job.error_message = final_attempt_result.stderr or "Code evaluation failed."
            _transition(job, CodeEvalJobState.FAILED)

        db.commit()
        log.info("Code-eval job %s finalized with state=%s", job_id, job.status.value)

    except Exception as exc:
        db.rollback()
        log.exception("Code-eval task crashed for %s: %s", job_id, exc)
        try:
            job = db.get(CodeEvalJob, job_id)
            if job and _as_state(job.status) not in {CodeEvalJobState.COMPLETED, CodeEvalJobState.FAILED}:
                _transition_to_failed(job)
                job.error_message = str(exc)
                db.commit()
        except Exception:
            db.rollback()
            log.exception("Failed to persist terminal failure state for %s", job_id)
    finally:
        db.close()
