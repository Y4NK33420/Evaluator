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

    # Deduplication: check hash before writing
    raw   = await file.read()
    sha   = hashlib.sha256(raw).hexdigest()
    dupe  = db.query(Submission).filter(
        Submission.assignment_id == assignment_id,
        Submission.image_hash    == sha,
    ).first()
    if dupe:
        raise HTTPException(409, f"Duplicate file: already recorded as submission {dupe.id}")

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

    # Enqueue OCR
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
        result.assignment_title     = s.assignment.title
        result.assignment_max_marks = s.assignment.max_marks
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
