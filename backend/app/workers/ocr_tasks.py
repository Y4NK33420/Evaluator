"""
OCR Celery tasks.

Routes to the correct engine based on assignment.question_type:
    objective  → Gemini OCR text + GLM bbox/confidence metadata
    subjective → Gemini OCR text
    mixed      → same as subjective
"""

import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Submission, SubmissionStatus, QuestionType, AuditLog
from app.services.genai_client import ModelServicePermanentError, ModelServiceTransientError
from app.services.ocr_service import run_ocr
from app.services.preprocessor import preprocess_image
from app.workers.celery_app import celery_app

log = logging.getLogger(__name__)


@celery_app.task(
    name="app.workers.ocr_tasks.run_ocr_task",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def run_ocr_task(self, submission_id: str):
    """
    Full OCR pipeline for one submission.
    Runs in the ocr_queue (sequential, GPU-safe).
    """
    db: Session = SessionLocal()
    try:
        submission = db.get(Submission, submission_id)
        if submission is None:
            log.error("Submission %s not found", submission_id)
            return

        # Mark as processing
        submission.status = SubmissionStatus.processing
        db.commit()

        # Preprocess (rotation fix, dedup check)
        image_path = Path(submission.file_path)
        image_path, image_hash = preprocess_image(image_path)
        submission.image_hash = image_hash

        # OCR
        question_type = submission.assignment.question_type
        result, engine = run_ocr(image_path.read_bytes(), question_type)

        submission.ocr_result  = result
        submission.ocr_engine  = engine
        submission.status      = SubmissionStatus.ocr_done
        db.commit()

        log.info("OCR done for %s (engine=%s, blocks=%d)",
                 submission_id, engine, len(result.get("blocks", [])))

        # Automatically enqueue grading
        from app.workers.grading_tasks import run_grading_task
        run_grading_task.delay(submission_id)

    except Exception as exc:
        db.rollback()
        log.exception("OCR task failed for %s: %s", submission_id, exc)
        try:
            sub = db.get(Submission, submission_id)
            if sub:
                sub.status        = SubmissionStatus.failed
                sub.error_message = str(exc)
                db.commit()
        except Exception:
            pass

        if isinstance(exc, ModelServicePermanentError):
            # Non-retryable model failures should be surfaced without repeated retries.
            raise

        raise self.retry(exc=exc)
    finally:
        db.close()
