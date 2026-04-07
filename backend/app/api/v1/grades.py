"""Grades: batch release to Google Classroom."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Grade, Submission, ClassroomStatus, AuditLog
from app.schemas import BatchGradeRelease, GradeOut

router = APIRouter(prefix="/grades", tags=["grades"])


@router.post("/release", status_code=202)
def release_grades(body: BatchGradeRelease, db: Session = Depends(get_db)):
    """
    Push grades to Google Classroom as `assignedGrade` for listed submission IDs.
    Grades must currently be in `draft` or `not_synced` state.
    """
    from app.services.classroom_sync import push_assigned_grade

    released, errors = [], []
    for sid in body.submission_ids:
        grade = db.query(Grade).filter(
            Grade.submission_id == sid,
            Grade.active_version == True,
        ).first()
        if not grade:
            errors.append({"submission_id": sid, "error": "no active grade"})
            continue
        try:
            push_assigned_grade(sid, grade.total_score, db)
            grade.classroom_status = ClassroomStatus.released
            db.add(AuditLog(
                submission_id  = sid,
                changed_by     = "system",
                action         = "grade_released",
                new_value_json = {"total_score": grade.total_score},
            ))
            released.append(sid)
        except Exception as e:
            errors.append({"submission_id": sid, "error": str(e)})

    db.commit()
    return {"released": released, "errors": errors}


@router.post("/draft", status_code=202)
def push_draft_grades(body: BatchGradeRelease, db: Session = Depends(get_db)):
    """Push grades as `draftGrade` to Google Classroom."""
    from app.services.classroom_sync import push_draft_grade

    synced, errors = [], []
    for sid in body.submission_ids:
        sub   = db.get(Submission, sid)
        grade = db.query(Grade).filter(
            Grade.submission_id == sid,
            Grade.active_version == True,
        ).first()
        if not grade or not sub:
            errors.append({"submission_id": sid, "error": "not found"})
            continue
        try:
            push_draft_grade(sid, grade.total_score, db)
            grade.classroom_status = ClassroomStatus.draft
            synced.append(sid)
        except Exception as e:
            errors.append({"submission_id": sid, "error": str(e)})

    db.commit()
    return {"synced_as_draft": synced, "errors": errors}
