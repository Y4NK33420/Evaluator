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
    from app.services.classroom_sync import push_assigned_grade, validate_coursework_grade_sync_target

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
            sub = db.query(Submission).filter(Submission.id == sid).first()
            if not sub or not sub.assignment or not sub.assignment.classroom_id:
                errors.append({"submission_id": sid, "error": "assignment_not_linked_to_classroom"})
                continue
            course_id = sub.assignment.course_id
            if course_id and course_id.startswith("classroom-"):
                course_id = course_id[len("classroom-") :]
            validation = validate_coursework_grade_sync_target(course_id, sub.assignment.classroom_id)
            if not validation.get("ready"):
                errors.append({
                    "submission_id": sid,
                    "error": "classroom_sync_target_not_ready",
                    "missing": validation.get("missing", []),
                })
                continue
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
    from app.services.classroom_sync import push_draft_grade, validate_coursework_grade_sync_target

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
            if not sub.assignment or not sub.assignment.classroom_id:
                errors.append({"submission_id": sid, "error": "assignment_not_linked_to_classroom"})
                continue
            course_id = sub.assignment.course_id
            if course_id and course_id.startswith("classroom-"):
                course_id = course_id[len("classroom-") :]
            validation = validate_coursework_grade_sync_target(course_id, sub.assignment.classroom_id)
            if not validation.get("ready"):
                errors.append({
                    "submission_id": sid,
                    "error": "classroom_sync_target_not_ready",
                    "missing": validation.get("missing", []),
                })
                continue
            push_draft_grade(sid, grade.total_score, db)
            grade.classroom_status = ClassroomStatus.draft
            synced.append(sid)
        except Exception as e:
            errors.append({"submission_id": sid, "error": str(e)})

    db.commit()
    return {"synced_as_draft": synced, "errors": errors}
