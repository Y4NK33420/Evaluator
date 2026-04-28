"""Assignments CRUD."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    Assignment,
    AuditLog,
    CodeEvalApprovalRecord,
    CodeEvalEnvironmentStatus,
    CodeEvalEnvironmentVersion,
    CodeEvalAttempt,
    CodeEvalJob,
    Grade,
    Rubric,
    Submission,
)
from app.schemas import (
    AssignmentCreate,
    AssignmentOut,
    AssignmentPublishOut,
    AssignmentPublishRequest,
    AssignmentPublishValidationOut,
    AssignmentPublishValidationRequest,
    AssignmentSummaryOut,
    AssignmentUpdate,
)

router = APIRouter(prefix="/assignments", tags=["assignments"])


def _resolve_publish_environment(
    db: Session,
    assignment: Assignment,
    requested_environment_version_id: str | None,
) -> CodeEvalEnvironmentVersion | None:
    if requested_environment_version_id:
        env = db.get(CodeEvalEnvironmentVersion, requested_environment_version_id)
        if not env:
            raise HTTPException(404, "Environment version not found")
        return env

    if assignment.published_environment_version_id:
        return db.get(CodeEvalEnvironmentVersion, assignment.published_environment_version_id)

    return None


def _build_publish_validation(
    db: Session,
    assignment: Assignment,
    requested_environment_version_id: str | None,
) -> AssignmentPublishValidationOut:
    approved_rubric_exists = (
        db.query(Rubric)
        .filter(
            Rubric.assignment_id == assignment.id,
            Rubric.approved == True,
        )
        .first()
        is not None
    )

    checks: dict[str, bool] = {
        "rubric_approved": approved_rubric_exists,
    }

    env_version = _resolve_publish_environment(db, assignment, requested_environment_version_id)

    if assignment.has_code_question:
        # Single env readiness check — true only when a ready, active version exists
        env_ready = (
            env_version is not None
            and env_version.is_active
            and env_version.status == CodeEvalEnvironmentStatus.ready
        )
        checks["environment_ready"] = env_ready

        # Check approved test cases exist
        from app.models import CodeEvalApprovalRecord, CodeEvalApprovalArtifactType, CodeEvalApprovalStatus
        approved_tests = (
            db.query(CodeEvalApprovalRecord)
            .filter(
                CodeEvalApprovalRecord.assignment_id == assignment.id,
                CodeEvalApprovalRecord.artifact_type == CodeEvalApprovalArtifactType.ai_tests,
                CodeEvalApprovalRecord.status == CodeEvalApprovalStatus.approved,
            )
            .first()
            is not None
        )
        checks["test_cases_approved"] = approved_tests

    missing = [name for name, ok in checks.items() if not ok]
    return AssignmentPublishValidationOut(
        assignment_id=assignment.id,
        ready_for_publish=not missing,
        checks=checks,
        missing=missing,
        environment_version_id=(env_version.id if env_version else None),
    )



@router.post("/", response_model=AssignmentOut, status_code=201)
def create_assignment(body: AssignmentCreate, db: Session = Depends(get_db)):
    a = Assignment(**body.model_dump())
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


@router.get("/summary", response_model=list[AssignmentSummaryOut])
def list_assignments_summary(course_id: str | None = None, db: Session = Depends(get_db)):
    """List assignments enriched with per-row submission/grade counts."""
    from app.models import Grade, Submission, ClassroomStatus
    from sqlalchemy import func

    q = db.query(Assignment)
    if course_id:
        q = q.filter(Assignment.course_id == course_id)
    assignments = q.order_by(Assignment.created_at.desc()).all()

    results = []
    for a in assignments:
        subs = db.query(Submission).filter(Submission.assignment_id == a.id).all()
        sub_ids = [s.id for s in subs]
        graded_count = 0
        released_count = 0
        if sub_ids:
            graded_count = db.query(Grade).filter(
                Grade.submission_id.in_(sub_ids),
                Grade.active_version == True,
            ).count()
            released_count = db.query(Grade).filter(
                Grade.submission_id.in_(sub_ids),
                Grade.active_version == True,
                Grade.classroom_status == ClassroomStatus.released,
            ).count()
        error_count = sum(1 for s in subs if s.status == "failed")
        out = AssignmentSummaryOut.model_validate(a)
        out.submission_count = len(subs)
        out.graded_count     = graded_count
        out.released_count   = released_count
        out.error_count      = error_count
        results.append(out)

    return results


@router.get("/", response_model=list[AssignmentOut])
def list_assignments(course_id: str | None = None, db: Session = Depends(get_db)):
    q = db.query(Assignment)
    if course_id:
        q = q.filter(Assignment.course_id == course_id)
    return q.order_by(Assignment.created_at.desc()).all()



@router.get("/{assignment_id}", response_model=AssignmentOut)
def get_assignment(assignment_id: str, db: Session = Depends(get_db)):
    a = db.get(Assignment, assignment_id)
    if not a:
        raise HTTPException(404, "Assignment not found")
    return a


@router.patch("/{assignment_id}", response_model=AssignmentOut)
def update_assignment(assignment_id: str, body: AssignmentUpdate, db: Session = Depends(get_db)):
    a = db.get(Assignment, assignment_id)
    if not a:
        raise HTTPException(404, "Assignment not found")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(a, k, v)
    db.commit()
    db.refresh(a)
    return a


@router.delete("/{assignment_id}", status_code=204)
def delete_assignment(assignment_id: str, db: Session = Depends(get_db)):
    a = db.get(Assignment, assignment_id)
    if not a:
        raise HTTPException(404, "Assignment not found")

    # Explicitly delete dependent rows first to avoid SQLAlchemy nulling
    # non-null FK columns (e.g. code_eval_approval_records.assignment_id).
    submission_ids = [
        sid
        for (sid,) in db.query(Submission.id).filter(Submission.assignment_id == assignment_id).all()
    ]
    job_ids = [
        jid
        for (jid,) in db.query(CodeEvalJob.id).filter(CodeEvalJob.assignment_id == assignment_id).all()
    ]

    if job_ids:
        db.query(CodeEvalAttempt).filter(CodeEvalAttempt.job_id.in_(job_ids)).delete(
            synchronize_session=False
        )

    db.query(CodeEvalJob).filter(CodeEvalJob.assignment_id == assignment_id).delete(
        synchronize_session=False
    )
    db.query(CodeEvalApprovalRecord).filter(
        CodeEvalApprovalRecord.assignment_id == assignment_id
    ).delete(synchronize_session=False)
    db.query(Rubric).filter(Rubric.assignment_id == assignment_id).delete(
        synchronize_session=False
    )

    if submission_ids:
        db.query(AuditLog).filter(AuditLog.submission_id.in_(submission_ids)).delete(
            synchronize_session=False
        )
        db.query(Grade).filter(Grade.submission_id.in_(submission_ids)).delete(
            synchronize_session=False
        )
        db.query(Submission).filter(Submission.id.in_(submission_ids)).delete(
            synchronize_session=False
        )

    db.query(CodeEvalEnvironmentVersion).filter(
        CodeEvalEnvironmentVersion.assignment_id == assignment_id
    ).delete(synchronize_session=False)

    db.delete(a)
    db.commit()


@router.post("/{assignment_id}/validate-publish", response_model=AssignmentPublishValidationOut)
def validate_assignment_publish(
    assignment_id: str,
    body: AssignmentPublishValidationRequest,
    db: Session = Depends(get_db),
):
    assignment = db.get(Assignment, assignment_id)
    if not assignment:
        raise HTTPException(404, "Assignment not found")
    return _build_publish_validation(db, assignment, body.environment_version_id)


@router.post("/{assignment_id}/publish", response_model=AssignmentPublishOut)
def publish_assignment(
    assignment_id: str,
    body: AssignmentPublishRequest,
    db: Session = Depends(get_db),
):
    assignment = db.get(Assignment, assignment_id)
    if not assignment:
        raise HTTPException(404, "Assignment not found")

    if assignment.is_published and not body.force_republish:
        raise HTTPException(
            status_code=409,
            detail=(
                "Assignment is already published. Pass force_republish=true to republish "
                "with updated readiness artifacts."
            ),
        )

    validation = _build_publish_validation(db, assignment, body.environment_version_id)
    if not validation.ready_for_publish:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Assignment is not ready for publish",
                "missing": validation.missing,
                "checks": validation.checks,
            },
        )

    assignment.is_published = True
    assignment.published_at = datetime.now(timezone.utc)
    assignment.published_by = body.actor or "system"
    if assignment.has_code_question:
        assignment.published_environment_version_id = validation.environment_version_id

    db.commit()
    db.refresh(assignment)
    return AssignmentPublishOut(assignment=assignment, validation=validation)
