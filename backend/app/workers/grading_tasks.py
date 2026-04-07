"""Grading Celery task — rubric-gated grading execution."""

import logging

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Submission, SubmissionStatus, Grade, GradeSource, AuditLog
from app.services.genai_client import ModelServicePermanentError, ModelServiceTransientError
from app.services.grading_service import grade_submission
from app.services.consistency_validator import validate_grade
from app.workers.celery_app import celery_app

log = logging.getLogger(__name__)


@celery_app.task(
    name="app.workers.grading_tasks.run_grading_task",
    bind=True,
    max_retries=3,
    default_retry_delay=10,
)
def run_grading_task(self, submission_id: str):
    """
    Grade one submission with Gemini.
    Runs in the grading_queue (concurrent, I/O-bound).
    """
    db: Session = SessionLocal()
    try:
        submission = db.get(Submission, submission_id)
        if submission is None or submission.ocr_result is None:
            log.error("Submission %s not ready for grading", submission_id)
            return

        submission.status = SubmissionStatus.grading
        db.commit()

        # Get active rubric for this assignment
        rubric = next(
            (r for r in submission.assignment.rubrics if r.approved),
            None,
        )

        if rubric is None:
            msg = (
                "Grading blocked: no approved rubric found for assignment "
                f"{submission.assignment_id}"
            )
            submission.status = SubmissionStatus.failed
            submission.error_message = msg
            db.add(AuditLog(
                submission_id  = submission_id,
                changed_by     = "system",
                action         = "grading_blocked_unapproved_rubric",
                reason         = "Rubric must be approved before grading.",
            ))
            db.commit()
            log.warning(msg)
            return

        result = grade_submission(
            ocr_result    = submission.ocr_result,
            assignment    = submission.assignment,
            rubric        = rubric.content_json if rubric else None,
        )

        # Validate mathematical consistency
        issues = validate_grade(result, submission.assignment.max_marks)
        if issues:
            log.warning("Grade consistency issues for %s: %s", submission_id, issues)
            result["consistency_issues"] = issues

        # Deactivate previous versions
        db.query(Grade).filter(
            Grade.submission_id == submission_id,
            Grade.active_version == True,
        ).update({"active_version": False})

        grade = Grade(
            submission_id  = submission_id,
            active_version = True,
            total_score    = result["total_score"],
            breakdown_json = result,
            source         = GradeSource.ai_generated,
            is_truncated   = result.get("is_truncated", False),
        )
        db.add(grade)

        db.add(AuditLog(
            submission_id  = submission_id,
            changed_by     = "system",
            action         = "ai_grade",
            new_value_json = {"total_score": result["total_score"]},
        ))

        submission.status = SubmissionStatus.graded
        db.commit()

        log.info("Grading done for %s — score=%.1f/%.1f",
                 submission_id, result["total_score"], submission.assignment.max_marks)

    except Exception as exc:
        db.rollback()
        log.exception("Grading task failed for %s: %s", submission_id, exc)
        try:
            sub = db.get(Submission, submission_id)
            if sub:
                sub.status        = SubmissionStatus.failed
                sub.error_message = str(exc)
                db.commit()
        except Exception:
            pass

        if isinstance(exc, ModelServicePermanentError):
            # Non-retryable model failures (invalid model/config/auth) should surface directly.
            raise

        raise self.retry(exc=exc)
    finally:
        db.close()
