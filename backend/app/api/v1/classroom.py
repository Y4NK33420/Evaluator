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

from fastapi import APIRouter, Depends, HTTPException
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


class CreateCourseworkRequest(BaseModel):
    course_id: str
    publish: bool = True
    title: str | None = None
    description: str | None = None
    max_points: float | None = None


class UpdateCourseworkRequest(BaseModel):
    course_id: str
    title: str | None = None
    description: str | None = None
    max_points: float | None = None
    publish: bool | None = None


class LinkCourseworkRequest(BaseModel):
    course_id: str
    coursework_id: str


class GenerateTokenRequest(BaseModel):
    force_reauth: bool = False


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


def _resolve_classroom_course_id(assignment: Assignment, requested_course_id: str | None) -> str:
    course_id = (requested_course_id or assignment.course_id or "").strip()
    if course_id.startswith("classroom-"):
        course_id = course_id[len("classroom-") :]
    if not course_id:
        raise HTTPException(422, "Classroom course_id is required")
    return course_id


def _require_sync_ready_coursework(cs, assignment: Assignment, course_id: str) -> dict:
    coursework_id = (assignment.classroom_id or "").strip()
    if not coursework_id:
        raise HTTPException(422, "Assignment is not linked to Classroom coursework")
    validation = cs.validate_coursework_grade_sync_target(course_id, coursework_id)
    if not validation.get("ready"):
        raise HTTPException(
            409,
            {
                "message": "Classroom coursework is not eligible for AMGS grade sync",
                "checks": validation.get("checks", {}),
                "missing": validation.get("missing", []),
                "coursework_id": coursework_id,
                "course_id": course_id,
            },
        )
    return validation.get("coursework", {})


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/auth-status")
def auth_status():
    """Check whether stored Google credentials are valid without triggering OAuth flow."""
    cs = _classroom_sync_import()
    return cs.get_auth_status()


@router.post("/generate-token")
def generate_token(body: GenerateTokenRequest | None = None):
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
        return cs.regenerate_token(force_reauth=bool(body and body.force_reauth))
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


@router.get("/coursework")
def list_coursework(course_id: str):
    """List coursework entries for a Classroom course to help linking."""
    cs = _classroom_sync_import()
    try:
        items = cs.list_coursework(course_id=course_id)
    except FileNotFoundError as exc:
        raise HTTPException(503, str(exc))
    except Exception as exc:
        log.exception("coursework list failed for course %s", course_id)
        raise HTTPException(500, f"Coursework list failed: {exc}")

    return {
        "course_id": course_id,
        "items": [
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "state": item.get("state"),
                "workType": item.get("workType"),
                "maxPoints": item.get("maxPoints"),
                "associatedWithDeveloper": item.get("associatedWithDeveloper"),
                "updateTime": item.get("updateTime"),
            }
            for item in items
        ],
    }


@router.post("/{assignment_id}/link-coursework")
def link_coursework(
    assignment_id: str,
    body: LinkCourseworkRequest,
    db: Session = Depends(get_db),
):
    """Link an existing Classroom coursework to an AMGS assignment."""
    assignment = _get_assignment_or_404(assignment_id, db)
    cs = _classroom_sync_import()
    course_id = _resolve_classroom_course_id(assignment, body.course_id)

    try:
        cw = cs.get_coursework(course_id=course_id, coursework_id=body.coursework_id)
    except Exception as exc:
        raise HTTPException(422, f"Could not fetch coursework {body.coursework_id}: {exc}")

    assignment.classroom_id = body.coursework_id
    assignment.course_id = course_id
    db.commit()
    db.refresh(assignment)
    return {
        "assignment_id": assignment.id,
        "course_id": course_id,
        "coursework_id": assignment.classroom_id,
        "coursework": cw,
    }


@router.post("/{assignment_id}/create-coursework")
def create_coursework(
    assignment_id: str,
    body: CreateCourseworkRequest,
    db: Session = Depends(get_db),
):
    """Create Classroom coursework from AMGS assignment and link it."""
    assignment = _get_assignment_or_404(assignment_id, db)
    cs = _classroom_sync_import()
    course_id = _resolve_classroom_course_id(assignment, body.course_id)

    title = (body.title or assignment.title or "").strip()
    if not title:
        raise HTTPException(422, "Assignment title is required to create coursework")

    try:
        cw = cs.create_coursework_for_assignment(
            course_id=course_id,
            title=title,
            description=body.description if body.description is not None else assignment.description,
            max_points=body.max_points if body.max_points is not None else assignment.max_marks,
            state="PUBLISHED" if body.publish else "DRAFT",
        )
    except FileNotFoundError as exc:
        raise HTTPException(503, str(exc))
    except Exception as exc:
        log.exception("coursework create failed for assignment %s", assignment_id)
        raise HTTPException(500, f"Create coursework failed: {exc}")

    assignment.classroom_id = cw.get("id")
    assignment.course_id = course_id
    db.commit()
    db.refresh(assignment)
    return {
        "assignment_id": assignment.id,
        "course_id": course_id,
        "coursework_id": assignment.classroom_id,
        "coursework": cw,
    }


@router.patch("/{assignment_id}/coursework")
def update_coursework(
    assignment_id: str,
    body: UpdateCourseworkRequest,
    db: Session = Depends(get_db),
):
    """Update linked Classroom coursework from AMGS assignment fields."""
    assignment = _get_assignment_or_404(assignment_id, db)
    cs = _classroom_sync_import()
    course_id = _resolve_classroom_course_id(assignment, body.course_id)
    coursework_id = (assignment.classroom_id or "").strip()
    if not coursework_id:
        raise HTTPException(422, "Assignment is not linked to Classroom coursework")

    try:
        cw = cs.update_coursework_for_assignment(
            course_id=course_id,
            coursework_id=coursework_id,
            title=body.title,
            description=body.description,
            max_points=body.max_points,
            state=("PUBLISHED" if body.publish else "DRAFT") if body.publish is not None else None,
        )
    except FileNotFoundError as exc:
        raise HTTPException(503, str(exc))
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except Exception as exc:
        log.exception("coursework update failed for assignment %s", assignment_id)
        raise HTTPException(500, f"Update coursework failed: {exc}")

    return {
        "assignment_id": assignment.id,
        "course_id": course_id,
        "coursework_id": coursework_id,
        "coursework": cw,
    }


@router.post("/{assignment_id}/sync-draft", response_model=SyncSummary)
def sync_draft_grades(
    assignment_id: str,
    db: Session = Depends(get_db),
):
    """Push draftGrade to Classroom for every submission that has an active Grade.

    Draft grades are visible to teachers but NOT to students until released.
    Safe to call multiple times — Classroom accepts repeated PATCH calls.
    """
    assignment = _get_assignment_or_404(assignment_id, db)
    cs = _classroom_sync_import()
    course_id = _resolve_classroom_course_id(assignment, assignment.course_id)
    coursework = _require_sync_ready_coursework(cs, assignment, course_id)
    try:
        result = cs.push_draft_grades_bulk(assignment_id=assignment_id, db=db)
    except FileNotFoundError as exc:
        raise HTTPException(503, str(exc))
    except Exception as exc:
        log.exception("draft grade sync failed for assignment %s", assignment_id)
        raise HTTPException(500, f"Draft grade sync failed: {exc}")

    return SyncSummary(
        assignment_id=assignment_id,
        pushed=result["pushed"],
        skipped=result["skipped"],
        errors=result["errors"],
        status=f"sync_target:{coursework.get('id')}",
    )


@router.post("/{assignment_id}/release", response_model=SyncSummary)
def release_grades(
    assignment_id: str,
    db: Session = Depends(get_db),
):
    """Push assignedGrade and call return() — makes grades visible to students.

    This is a one-way operation: once grades are returned in Classroom,
    students can see them. Confirm before calling on a live course.
    """
    assignment = _get_assignment_or_404(assignment_id, db)
    cs = _classroom_sync_import()
    course_id = _resolve_classroom_course_id(assignment, assignment.course_id)
    coursework = _require_sync_ready_coursework(cs, assignment, course_id)
    try:
        result = cs.release_grades_bulk(assignment_id=assignment_id, db=db)
    except FileNotFoundError as exc:
        raise HTTPException(503, str(exc))
    except Exception as exc:
        log.exception("grade release failed for assignment %s", assignment_id)
        raise HTTPException(500, f"Grade release failed: {exc}")

    return SyncSummary(
        assignment_id=assignment_id,
        released=result["released"],
        skipped=result["skipped"],
        errors=result["errors"],
        status=f"sync_target:{coursework.get('id')}",
    )


@router.get("/{assignment_id}/status")
def classroom_sync_status(
    assignment_id: str,
    db: Session = Depends(get_db),
):
    """Overview of how many submissions are ingested and graded for an assignment."""
    assignment = _get_assignment_or_404(assignment_id, db)
    cs = _classroom_sync_import()
    course_id = _resolve_classroom_course_id(assignment, assignment.course_id)
    coursework_meta = None
    sync_checks = {}
    sync_missing: list[str] = []
    try:
        if assignment.classroom_id:
            validation = cs.validate_coursework_grade_sync_target(course_id, assignment.classroom_id)
            coursework_meta = validation.get("coursework")
            sync_checks = validation.get("checks", {})
            sync_missing = validation.get("missing", [])
    except Exception as exc:
        sync_checks = {"coursework_lookup_failed": False}
        sync_missing = [str(exc)]

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
        "course_id": course_id,
        "classroom_id": assignment.classroom_id,
        "total_submissions": total_submissions,
        "graded": graded,
        "ungraded": ungraded,
        "sync_checks": sync_checks,
        "sync_missing": sync_missing,
        "coursework": coursework_meta,
        "submissions": rows,
    }
