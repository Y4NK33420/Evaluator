"""Google Classroom API endpoints.

Routes:
  GET  /classroom/auth-status              — credential validity check (no browser flow)
  POST /classroom/{assignment_id}/ingest   — pull student submissions from Classroom → DB
  POST /classroom/{assignment_id}/sync-draft — push draftGrade for all graded submissions
  POST /classroom/{assignment_id}/release  — push assignedGrade + return to students
  GET  /classroom/{assignment_id}/status   — per-assignment sync status overview
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Assignment, Grade, Submission

log = logging.getLogger(__name__)
router = APIRouter(prefix="/classroom", tags=["classroom"])


# ── Request / Response shapes ─────────────────────────────────────────────────

class IngestRequest(BaseModel):
    course_id: str
    coursework_id: str           # Google Classroom courseWorkId
    force_reingest: bool = False  # re-download even if submission already exists


class SyncSummary(BaseModel):
    assignment_id: str
    found: int = 0
    ingested: int = 0
    pushed: int = 0
    released: int = 0
    skipped: int = 0
    errors: list = []
    status: str = "ok"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_assignment_or_404(assignment_id: str, db: Session) -> Assignment:
    a = db.get(Assignment, assignment_id)
    if not a:
        raise HTTPException(404, f"Assignment {assignment_id} not found")
    return a


def _classroom_sync_import():
    """Lazy import so startup doesn't fail if google libs are absent."""
    try:
        from app.services import classroom_sync  # noqa: F401
        return classroom_sync
    except ImportError as exc:
        raise HTTPException(
            503,
            f"Google Classroom dependencies not installed: {exc}. "
            "Add google-api-python-client to requirements.txt.",
        )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/auth-status")
def auth_status():
    """Check whether stored Google credentials are valid without triggering OAuth flow."""
    cs = _classroom_sync_import()
    return cs.get_auth_status()


@router.post("/generate-token")
def generate_token():
    """Trigger the OAuth browser flow to create/refresh token.json.

    Requires credentials.json to be present.  Opens a local browser window
    on the server machine — intended for localhost / teacher-laptop deployments.
    Returns the resulting auth-status dict so the frontend can update immediately.
    """
    cs = _classroom_sync_import()
    from pathlib import Path
    from app.config import get_settings
    settings = get_settings()

    creds_path = Path(settings.google_credentials_file)
    if not creds_path.exists():
        raise HTTPException(
            422,
            f"credentials.json not found at {creds_path}. "
            "Download it from GCP Console → APIs & Services → Credentials "
            "and place it in backend/app/services/google_auth/.",
        )

    try:
        # _get_services() will run the browser flow if token.json is absent / expired
        cs._get_services()
        return cs.get_auth_status()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"OAuth flow failed: {exc}") from exc


@router.post("/{assignment_id}/ingest", response_model=SyncSummary)
def ingest_submissions(
    assignment_id: str,
    body: IngestRequest,
    db: Session = Depends(get_db),
):
    """Pull TURNED_IN student submissions from Google Classroom into the local DB.

    Downloads attached Drive files, deduplicates by SHA-256, and creates
    Submission rows. Idempotent — safe to call repeatedly; already-ingested
    submissions are skipped unless force_reingest=true.
    """
    assignment = _get_assignment_or_404(assignment_id, db)

    # Validate that the local assignment's classroom_id matches the request
    if assignment.classroom_id and assignment.classroom_id != body.coursework_id:
        raise HTTPException(
            422,
            f"Assignment has classroom_id={assignment.classroom_id} but "
            f"request specified coursework_id={body.coursework_id}",
        )

    # Set classroom_id on the assignment if not already set
    if not assignment.classroom_id:
        assignment.classroom_id = body.coursework_id
        db.commit()

    cs = _classroom_sync_import()
    try:
        result = cs.ingest_course_submissions(
            course_id=body.course_id,
            coursework_id=body.coursework_id,
            assignment_id=assignment_id,
            db=db,
            force_reingest=body.force_reingest,
        )
    except FileNotFoundError as exc:
        raise HTTPException(503, str(exc))
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except Exception as exc:
        log.exception("classroom ingest failed for assignment %s", assignment_id)
        raise HTTPException(500, f"Classroom ingest failed: {exc}")

    return SyncSummary(assignment_id=assignment_id, **result)


@router.post("/{assignment_id}/sync-draft", response_model=SyncSummary)
def sync_draft_grades(
    assignment_id: str,
    db: Session = Depends(get_db),
):
    """Push draftGrade to Classroom for every submission that has an active Grade.

    Draft grades are visible to teachers but NOT to students until released.
    Safe to call multiple times — Classroom accepts repeated PATCH calls.
    """
    _get_assignment_or_404(assignment_id, db)
    cs = _classroom_sync_import()
    try:
        result = cs.push_draft_grades_bulk(assignment_id=assignment_id, db=db)
    except FileNotFoundError as exc:
        raise HTTPException(503, str(exc))
    except Exception as exc:
        log.exception("draft grade sync failed for assignment %s", assignment_id)
        raise HTTPException(500, f"Draft grade sync failed: {exc}")

    return SyncSummary(assignment_id=assignment_id, pushed=result["pushed"],
                       skipped=result["skipped"], errors=result["errors"])


@router.post("/{assignment_id}/release", response_model=SyncSummary)
def release_grades(
    assignment_id: str,
    db: Session = Depends(get_db),
):
    """Push assignedGrade and call return() — makes grades visible to students.

    This is a one-way operation: once grades are returned in Classroom,
    students can see them. Confirm before calling on a live course.
    """
    _get_assignment_or_404(assignment_id, db)
    cs = _classroom_sync_import()
    try:
        result = cs.release_grades_bulk(assignment_id=assignment_id, db=db)
    except FileNotFoundError as exc:
        raise HTTPException(503, str(exc))
    except Exception as exc:
        log.exception("grade release failed for assignment %s", assignment_id)
        raise HTTPException(500, f"Grade release failed: {exc}")

    return SyncSummary(assignment_id=assignment_id, released=result["released"],
                       skipped=result["skipped"], errors=result["errors"])


@router.get("/{assignment_id}/status")
def classroom_sync_status(
    assignment_id: str,
    db: Session = Depends(get_db),
):
    """Overview of how many submissions are ingested and graded for an assignment."""
    _get_assignment_or_404(assignment_id, db)

    total_submissions = (
        db.query(Submission)
        .filter(Submission.assignment_id == assignment_id)
        .count()
    )

    graded = (
        db.query(Grade)
        .join(Submission, Grade.submission_id == Submission.id)
        .filter(
            Submission.assignment_id == assignment_id,
            Grade.active_version == True,
        )
        .count()
    )

    ungraded = total_submissions - graded

    submissions = (
        db.query(Submission)
        .filter(Submission.assignment_id == assignment_id)
        .all()
    )

    rows = []
    for sub in submissions:
        grade = (
            db.query(Grade)
            .filter(Grade.submission_id == sub.id, Grade.active_version == True)
            .first()
        )
        rows.append({
            "submission_id": sub.id,
            "student_id": sub.student_id,
            "student_name": sub.student_name,
            "status": sub.status,
            "graded": grade is not None,
            "total_score": grade.total_score if grade else None,
            "grade_source": (grade.source.value if hasattr(grade.source, "value") else grade.source)
                            if grade else None,
        })

    return {
        "assignment_id": assignment_id,
        "total_submissions": total_submissions,
        "graded": graded,
        "ungraded": ungraded,
        "submissions": rows,
    }
