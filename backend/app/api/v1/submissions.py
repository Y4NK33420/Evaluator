"""Submissions: upload, list, OCR-correction, re-grade, audit log."""

import copy
import hashlib
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import Assignment, AuditLog, ClassroomStatus, Grade, GradeSource, Submission, SubmissionStatus
from app.schemas import (
    AuditLogOut,
    GradeOut,
    JobEnqueuedResponse,
    ManualGradeOverrideRequest,
    OCRCorrectionRequest,
    RegradeRequest,
    SubmissionOut,
)
from app.workers.ocr_tasks import run_ocr_task
from app.workers.grading_tasks import run_grading_task

router   = APIRouter(prefix="/submissions", tags=["submissions"])
settings = get_settings()


def _resolve_coding_weights_from_rubric(content_json: dict) -> tuple[float, float]:
    policy = content_json.get("scoring_policy") if isinstance(content_json, dict) else None
    coding = policy.get("coding") if isinstance(policy, dict) else None
    if not isinstance(coding, dict):
        raise ValueError("Missing scoring_policy.coding in approved rubric")
    rw = float(coding.get("rubric_weight"))
    tw = float(coding.get("testcase_weight"))
    if rw < 0 or tw < 0 or (rw + tw) <= 0:
        raise ValueError("Invalid rubric_weight/testcase_weight in approved rubric")
    return rw, tw


# ── Upload ────────────────────────────────────────────────────────────────────

@router.post("/{assignment_id}/upload", response_model=JobEnqueuedResponse, status_code=202)
async def upload_submission(
    assignment_id: str,
    student_id:    str,
    student_name:  str | None = None,
    file:          UploadFile = File(...),
    db:            Session    = Depends(get_db),
):
    """Upload a student scan and enqueue OCR. Accepts JPEG, PNG, PDF."""
    assignment = db.get(Assignment, assignment_id)
    if not assignment:
        raise HTTPException(404, "Assignment not found")

    raw   = await file.read()
    sha   = hashlib.sha256(raw).hexdigest()
    
    # Deduplication: block exact file matches for DIFFERENT students,
    # but only for written scans (simple code files might be identical boilerplate)
    if not assignment.has_code_question:
        dupe = db.query(Submission).filter(
            Submission.assignment_id == assignment_id,
            Submission.image_hash    == sha,
            Submission.student_id    != student_id,
        ).first()
        if dupe:
            raise HTTPException(409, f"Duplicate file: already recorded for student {dupe.student_id}")

    # Persist file
    upload_dir = Path(settings.uploads_dir) / assignment_id / student_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest = upload_dir / file.filename
    dest.write_bytes(raw)

    # Upsert submission row (allow re-upload overwriting previous)
    sub = db.query(Submission).filter(
        Submission.assignment_id == assignment_id,
        Submission.student_id    == student_id,
    ).first()
    if sub:
        sub.file_path    = str(dest)
        sub.image_hash   = sha
        sub.status       = SubmissionStatus.pending
        sub.ocr_result   = None
        sub.error_message= None
    else:
        sub = Submission(
            assignment_id = assignment_id,
            student_id    = student_id,
            student_name  = student_name,
            file_path     = str(dest),
            image_hash    = sha,
        )
        db.add(sub)

    db.commit()
    db.refresh(sub)

    if assignment.has_code_question:
        # Code assignments: no OCR needed — the file IS the submission artifact.
        # Set status to ocr_done so the submission is immediately ready for code-eval dispatch.
        sub.status = SubmissionStatus.ocr_done
        sub.ocr_result = None
        db.commit()
    else:
        # Regular written assignments: enqueue OCR pipeline
        run_ocr_task.delay(sub.id)

    return JobEnqueuedResponse(job_id=sub.id, submission_id=sub.id)


# ── List / Get ────────────────────────────────────────────────────────────────

@router.get("/", response_model=list[SubmissionOut])
def list_all_submissions(
    status: SubmissionStatus | None = None,
    limit:  int = 200,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """List submissions across all assignments (for dashboard / global views)."""
    q = db.query(Submission)
    if status:
        q = q.filter(Submission.status == status)
    return q.order_by(Submission.created_at.desc()).offset(offset).limit(limit).all()


@router.get("/{assignment_id}", response_model=list[SubmissionOut])
def list_submissions(
    assignment_id: str,
    status: SubmissionStatus | None = None,
    db: Session = Depends(get_db),
):
    q = db.query(Submission).filter(Submission.assignment_id == assignment_id)
    if status:
        q = q.filter(Submission.status == status)
    return q.order_by(Submission.created_at).all()


@router.get("/detail/{submission_id}", response_model=SubmissionOut)
def get_submission(submission_id: str, db: Session = Depends(get_db)):
    s = db.get(Submission, submission_id)
    if not s:
        raise HTTPException(404, "Submission not found")
    # Enrich with assignment info
    result = SubmissionOut.model_validate(s)
    if s.assignment:
        result.assignment_title             = s.assignment.title
        result.assignment_max_marks         = s.assignment.max_marks
        result.assignment_has_code_question = s.assignment.has_code_question
        
        # Inject the uploaded code text for the frontend
        if s.assignment.has_code_question and s.file_path:
            fp = Path(s.file_path)
            if fp.exists():
                try:
                    result.source_code = fp.read_text(errors="replace")
                except Exception:
                    pass

    return result


# ── OCR Correction (TA edit → re-grade) ──────────────────────────────────────

@router.patch("/{submission_id}/ocr-correction", response_model=JobEnqueuedResponse)
def ocr_correction(
    submission_id: str,
    body: OCRCorrectionRequest,
    db:   Session = Depends(get_db),
):
    """TA edits one OCR block → archives old text + re-grades."""
    sub = db.get(Submission, submission_id)
    if not sub or not sub.ocr_result:
        raise HTTPException(404, "Submission / OCR result not found")

    # SQLAlchemy JSON columns do not reliably track nested in-place mutations,
    # so mutate a deep copy and assign it back to persist edits.
    updated_ocr_result = copy.deepcopy(sub.ocr_result)
    blocks = updated_ocr_result.get("blocks", [])
    target = next((b for b in blocks if b["index"] == body.block_index), None)
    if not target:
        raise HTTPException(404, f"Block index {body.block_index} not found")

    old_content  = target["content"]
    target["content"] = body.new_content
    sub.ocr_result = updated_ocr_result

    db.add(AuditLog(
        submission_id  = submission_id,
        changed_by     = body.changed_by,
        action         = "ocr_correction",
        old_value_json = {"block_index": body.block_index, "content": old_content},
        new_value_json = {"block_index": body.block_index, "content": body.new_content},
        reason         = body.reason,
    ))
    db.commit()

    # Trigger targeted re-grade
    run_grading_task.delay(submission_id)
    return JobEnqueuedResponse(job_id=submission_id, submission_id=submission_id, status="re_grading")


# ── Re-grade ──────────────────────────────────────────────────────────────────

@router.post("/{submission_id}/regrade", response_model=JobEnqueuedResponse)
def regrade_submission(
    submission_id: str,
    body: RegradeRequest,
    db:   Session = Depends(get_db),
):
    """Re-trigger AI grading on the current OCR text without changing OCR."""
    sub = db.get(Submission, submission_id)
    if not sub:
        raise HTTPException(404, "Submission not found")
    if not sub.ocr_result:
        raise HTTPException(422, "No OCR result available – upload and process the submission first")

    sub.status = SubmissionStatus.grading
    db.add(AuditLog(
        submission_id  = submission_id,
        changed_by     = body.changed_by,
        action         = "regrade_requested",
        new_value_json = {"reason": body.reason},
        reason         = body.reason,
    ))
    db.commit()

    run_grading_task.delay(submission_id)
    return JobEnqueuedResponse(job_id=submission_id, submission_id=submission_id, status="re_grading")


# ── Manual grade override ─────────────────────────────────────────────────────

@router.post("/{submission_id}/grade-override", response_model=GradeOut)
def manual_grade_override(
    submission_id: str,
    body: ManualGradeOverrideRequest,
    db:   Session = Depends(get_db),
):
    """TA fully overrides the grade — archives old grade, creates new active one."""
    sub = db.get(Submission, submission_id)
    if not sub:
        raise HTTPException(404, "Submission not found")

    # Deactivate all previous grade versions
    old_grades = db.query(Grade).filter(
        Grade.submission_id == submission_id,
        Grade.active_version == True,
    ).all()
    old_grade_snapshot = None
    for g in old_grades:
        old_grade_snapshot = {"total_score": g.total_score, "source": g.source.value}
        g.active_version = False

    from app.models import GradeSource
    new_grade = Grade(
        submission_id   = submission_id,
        active_version  = True,
        total_score     = body.total_score,
        breakdown_json  = body.breakdown_json,
        source          = GradeSource.ta_manual,
        classroom_status= ClassroomStatus.not_synced,
        is_truncated    = False,
    )
    db.add(new_grade)
    db.add(AuditLog(
        submission_id  = submission_id,
        changed_by     = body.changed_by,
        action         = "manual_grade_override",
        old_value_json = old_grade_snapshot,
        new_value_json = {"total_score": body.total_score, "source": "TA_Manual"},
        reason         = body.reason,
    ))
    sub.status = SubmissionStatus.graded
    db.commit()
    db.refresh(new_grade)
    return new_grade



@router.get("/{submission_id}/grade", response_model=GradeOut)
def get_grade(submission_id: str, db: Session = Depends(get_db)):
    grade = db.query(Grade).filter(
        Grade.submission_id == submission_id,
        Grade.active_version == True,
    ).first()
    if not grade:
        raise HTTPException(404, "No active grade found")
    return grade


@router.get("/{submission_id}/audit", response_model=list[AuditLogOut])
def get_audit_log(submission_id: str, db: Session = Depends(get_db)):
    return (
        db.query(AuditLog)
        .filter(AuditLog.submission_id == submission_id)
        .order_by(AuditLog.timestamp)
        .all()
    )


@router.delete("/{submission_id}", status_code=204)
def delete_submission(submission_id: str, db: Session = Depends(get_db)):
    """Delete a submission and its dependent grade/audit rows."""
    sub = db.get(Submission, submission_id)
    if not sub:
        raise HTTPException(404, "Submission not found")

    # Remove file from disk when present.
    try:
        if sub.file_path:
            fp = Path(sub.file_path)
            if fp.exists():
                fp.unlink(missing_ok=True)
            # best effort cleanup of now-empty student folder
            parent = fp.parent
            if parent.exists() and parent.is_dir():
                try:
                    parent.rmdir()
                except OSError:
                    pass
    except Exception:
        pass

    db.query(AuditLog).filter(AuditLog.submission_id == submission_id).delete(synchronize_session=False)
    db.query(Grade).filter(Grade.submission_id == submission_id).delete(synchronize_session=False)
    db.delete(sub)
    db.commit()


@router.post("/bulk-delete", status_code=202)
def bulk_delete_submissions(body: dict, db: Session = Depends(get_db)):
    """Delete selected submissions in bulk."""
    ids = body.get("submission_ids", [])
    if not isinstance(ids, list) or not ids:
        raise HTTPException(422, "submission_ids is required")
    deleted = []
    errors = []
    for sid in ids:
        sub = db.get(Submission, sid)
        if not sub:
            errors.append({"submission_id": sid, "error": "not found"})
            continue
        try:
            if sub.file_path:
                fp = Path(sub.file_path)
                if fp.exists():
                    fp.unlink(missing_ok=True)
            db.query(AuditLog).filter(AuditLog.submission_id == sid).delete(synchronize_session=False)
            db.query(Grade).filter(Grade.submission_id == sid).delete(synchronize_session=False)
            db.delete(sub)
            deleted.append(sid)
        except Exception as exc:
            errors.append({"submission_id": sid, "error": str(exc)})
    db.commit()
    return {"deleted": deleted, "errors": errors}


# ── Dispatch code-eval job (one-click for coding submissions) ─────────────────

@router.post("/{submission_id}/dispatch-code-eval", response_model=JobEnqueuedResponse)
def dispatch_code_eval(
    submission_id: str,
    explicit_regrade: bool = False,
    changed_by: str = "ta",
    db: Session = Depends(get_db),
):
    """One-click dispatch of a code-eval job for a coding submission.

    Reads the code file, resolves the assignment's published environment version
    and approved test artifact, then creates and queues a CodeEvalJob.
    Returns a JobEnqueuedResponse so the frontend can poll job status.
    """
    from app.models import (
        CodeEvalApprovalArtifactType, CodeEvalApprovalRecord, CodeEvalApprovalStatus,
        CodeEvalEnvironmentStatus, CodeEvalEnvironmentVersion, CodeEvalJob,
        CodeEvalJobStatus, CodeEvalRegradePolicy,
    )
    from app.services.code_eval.contracts import (
        CodeEvalJobRequest, EnvironmentSpec, ExecutionQuota,
        LanguageRuntime, QualityEvaluationConfig, QualityEvaluationMode,
        RegradePolicy, TestCaseSpec, InputMode,
    )
    from app.services.code_eval.test_authoring_service import draft_to_testcase_specs
    from app.workers.code_eval_tasks import run_code_eval_job_task

    sub = db.get(Submission, submission_id)
    if not sub:
        raise HTTPException(404, "Submission not found")

    assignment = db.get(Assignment, sub.assignment_id)
    if not assignment:
        raise HTTPException(404, "Assignment not found")
    if not assignment.has_code_question:
        raise HTTPException(422, "Assignment does not have a coding question")
    if not assignment.is_published:
        raise HTTPException(409, "Assignment must be published before dispatching code-eval")

    # ── Resolve environment version ────────────────────────────────────────────
    env_version: CodeEvalEnvironmentVersion | None = None
    if assignment.published_environment_version_id:
        env_version = db.get(CodeEvalEnvironmentVersion, assignment.published_environment_version_id)
    if env_version is None:
        # Fall back to latest ready version for this assignment
        env_version = (
            db.query(CodeEvalEnvironmentVersion)
            .filter(
                CodeEvalEnvironmentVersion.assignment_id == sub.assignment_id,
                CodeEvalEnvironmentVersion.status == CodeEvalEnvironmentStatus.ready,
                CodeEvalEnvironmentVersion.is_active == True,
            )
            .order_by(CodeEvalEnvironmentVersion.version_number.desc())
            .first()
        )
    if env_version is None:
        raise HTTPException(
            409,
            "No ready environment version found for this assignment. "
            "Build and publish an environment in the assignment's Environment tab first."
        )
    if env_version.status != CodeEvalEnvironmentStatus.ready:
        raise HTTPException(409, f"Environment version is not ready (status={env_version.status.value})")

    # ── Resolve approved rubric (weights + optional quality rubric text) ──────
    approved_rubric = next((r for r in assignment.rubrics if r.approved), None)
    if approved_rubric is None:
        raise HTTPException(
            422,
            "No approved rubric found for this coding assignment. "
            "Approve a rubric with coding scoring_policy first."
        )
    try:
        rubric_weight, testcase_weight = _resolve_coding_weights_from_rubric(approved_rubric.content_json or {})
    except Exception as exc:
        raise HTTPException(422, f"Invalid coding scoring_policy in approved rubric: {exc}")

    # ── Resolve approved test cases (only required when testcase_weight > 0) ──
    tests_approval: CodeEvalApprovalRecord | None = (
        db.query(CodeEvalApprovalRecord)
        .filter(
            CodeEvalApprovalRecord.assignment_id == sub.assignment_id,
            CodeEvalApprovalRecord.artifact_type == CodeEvalApprovalArtifactType.ai_tests,
            CodeEvalApprovalRecord.status == CodeEvalApprovalStatus.approved,
        )
        .order_by(CodeEvalApprovalRecord.version_number.desc())
        .first()
    )
    if testcase_weight > 0 and tests_approval is None:
        raise HTTPException(
            422,
            "No approved test cases found for this assignment. "
            "Generate and approve test cases in the assignment's Test Cases tab first."
        )

    # ── Read source file and map to configured entrypoint ───────────────────────
    # We must resolve entrypoint *before* reading, to map the uploaded
    # file (which might have any random name) to the expected entrypoint.
    spec_json = env_version.spec_json if isinstance(env_version.spec_json, dict) else {}
    raw_language = spec_json.get("language", "python")
    raw_entrypoint = spec_json.get("entrypoint", "solution.py")
    try:
        language = LanguageRuntime(raw_language)
    except ValueError:
        language = LanguageRuntime.PYTHON

    source_files: dict[str, str] = {}
    if sub.file_path:
        fp = Path(sub.file_path)
        if fp.exists():
            try:
                source_files[raw_entrypoint] = fp.read_text(errors="replace")
            except Exception:
                source_files[raw_entrypoint] = ""

    # ── Convert approved content_json to TestCaseSpec list ────────────────────
    content = (tests_approval.content_json or {}) if tests_approval is not None else {}
    testcases: list[TestCaseSpec] = []
    raw_tc_list = content.get("testcases") or content.get("tests") or []
    try:
        # draft_to_testcase_specs normalizes both mode2/mode3 output formats
        testcases = draft_to_testcase_specs(raw_tc_list)
    except Exception:
        # Fallback: minimal construction preserving all spec fields
        for i, tc in enumerate(raw_tc_list):
            if not isinstance(tc, dict):
                continue
            raw_mode = str(tc.get("input_mode") or "stdin").lower()
            try:
                im = InputMode(raw_mode)
            except ValueError:
                im = InputMode.STDIN
            testcases.append(TestCaseSpec(
                testcase_id=tc.get("testcase_id") or tc.get("id") or f"tc_{i+1:03d}",
                stdin=tc.get("stdin") if tc.get("stdin") is not None else None,
                argv=[str(a) for a in tc.get("argv", [])] if isinstance(tc.get("argv"), list) else [],
                files={},
                expected_stdout=tc.get("expected_stdout") if tc.get("expected_stdout") is not None else None,
                expected_stderr=tc.get("expected_stderr") if tc.get("expected_stderr") is not None else None,
                expected_exit_code=int(tc.get("expected_exit_code", 0)),
                weight=float(tc.get("weight", 1.0)),
                input_mode=im,
            ))

    if testcase_weight > 0 and not testcases:
        raise HTTPException(
            422,
            "The approved test artifact contains no valid test cases. "
            "Regenerate and re-approve the test cases."
        )
    if testcase_weight <= 0:
        # Quality-only mode: use one non-scoring smoke testcase so executor can run.
        testcases = [
            TestCaseSpec(
                testcase_id="quality_only_smoke",
                weight=1e-6,
                input_mode=InputMode.STDIN,
                stdin="",
                expected_exit_code=0,
            )
        ]

    # ── Build environment spec ─────────────────────────────────────────────────
    env_spec = EnvironmentSpec(
        freeze_key=env_version.freeze_key or "",
        runtime=raw_language,
        image_reference=spec_json.get("image_reference"),
    )

    # ── Build the full job request ─────────────────────────────────────────────
    request = CodeEvalJobRequest(
        assignment_id=sub.assignment_id,
        submission_id=submission_id,
        language=language,
        entrypoint=raw_entrypoint,
        source_files=source_files,
        testcases=testcases,
        environment=env_spec,
        quality_evaluation=QualityEvaluationConfig(
            mode=(
                QualityEvaluationMode.RUBRIC_ONLY
                if rubric_weight > 0
                else QualityEvaluationMode.DISABLED
            ),
            weight_percent=(rubric_weight / (rubric_weight + testcase_weight)) * 100.0,
            rubric=(
                (approved_rubric.content_json or {}).get("coding_quality_rubric")
                or (approved_rubric.content_json or {}).get("quality_rubric")
                or None
            ),
            mandatory_per_assignment=True,
        ),
        regrade_policy=RegradePolicy.NEW_ONLY_UNLESS_EXPLICIT,
        quota=ExecutionQuota(),
    )

    # ── Check for existing completed job (honour regrade policy) ──────────────
    if not explicit_regrade:
        prior = (
            db.query(CodeEvalJob)
            .filter(
                CodeEvalJob.submission_id == submission_id,
                CodeEvalJob.status == CodeEvalJobStatus.COMPLETED,
            )
            .first()
        )
        if prior:
            raise HTTPException(
                409,
                "Submission already has a completed code-eval job. "
                "Pass explicit_regrade=true to force regrading."
            )

    # ── Create and queue the job ───────────────────────────────────────────────
    job = CodeEvalJob(
        assignment_id=sub.assignment_id,
        submission_id=submission_id,
        environment_version_id=env_version.id,
        language=language.value,
        entrypoint=raw_entrypoint,
        request_json=request.model_dump(mode="json"),
        quality_config_json=request.quality_evaluation.model_dump(mode="json"),
        regrade_policy=CodeEvalRegradePolicy.new_only_unless_explicit,
        explicit_regrade=explicit_regrade,
    )
    db.add(job)

    sub.status = SubmissionStatus.grading
    db.add(AuditLog(
        submission_id=submission_id,
        changed_by=changed_by,
        action="code_eval_dispatched",
        new_value_json={"job_id": job.id, "env_version_id": env_version.id, "num_testcases": len(testcases)},
        reason="Code-eval job dispatched from submission detail page",
    ))
    db.commit()
    db.refresh(job)

    run_code_eval_job_task.delay(job.id)

    return JobEnqueuedResponse(job_id=job.id, submission_id=submission_id, status="code_eval_queued")


@router.post("/{submission_id}/process", response_model=JobEnqueuedResponse, status_code=202)
def process_submission(submission_id: str, db: Session = Depends(get_db)):
    """Queue the appropriate processing path for a submission."""
    sub = db.get(Submission, submission_id)
    if not sub:
        raise HTTPException(404, "Submission not found")

    # Coding submissions should go through code-eval dispatch, not OCR/grading.
    if sub.assignment and sub.assignment.has_code_question:
        return dispatch_code_eval(
            submission_id=submission_id,
            explicit_regrade=False,
            changed_by="system",
            db=db,
        )

    if not sub.ocr_result:
        sub.status = SubmissionStatus.pending
        db.commit()
        run_ocr_task.delay(submission_id)
        return JobEnqueuedResponse(job_id=submission_id, submission_id=submission_id, status="ocr_queued")

    sub.status = SubmissionStatus.grading
    db.commit()
    run_grading_task.delay(submission_id)
    return JobEnqueuedResponse(job_id=submission_id, submission_id=submission_id, status="grading_queued")


@router.post("/process-bulk", status_code=202)
def process_submissions_bulk(body: dict, db: Session = Depends(get_db)):
    ids = body.get("submission_ids", [])
    if not isinstance(ids, list) or not ids:
        raise HTTPException(422, "submission_ids is required")

    queued = []
    errors = []
    for sid in ids:
        sub = db.get(Submission, sid)
        if not sub:
            errors.append({"submission_id": sid, "error": "not found"})
            continue
        try:
            if sub.assignment and sub.assignment.has_code_question:
                resp = dispatch_code_eval(
                    submission_id=sid,
                    explicit_regrade=False,
                    changed_by="system",
                    db=db,
                )
                queued.append({"submission_id": sid, "status": resp.status})
                continue
            if not sub.ocr_result:
                sub.status = SubmissionStatus.pending
                run_ocr_task.delay(sid)
                queued.append({"submission_id": sid, "status": "ocr_queued"})
            else:
                sub.status = SubmissionStatus.grading
                run_grading_task.delay(sid)
                queued.append({"submission_id": sid, "status": "grading_queued"})
        except Exception as exc:
            errors.append({"submission_id": sid, "error": str(exc)})
    db.commit()
    return {"queued": queued, "errors": errors}
