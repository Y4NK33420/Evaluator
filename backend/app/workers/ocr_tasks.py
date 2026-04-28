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
from app.services.pdf_pages import render_pdf_to_jpeg_bytes
from app.services.preprocessor import preprocess_image
from app.workers.celery_app import celery_app

log = logging.getLogger(__name__)


def _is_pdf(path: Path) -> bool:
    return path.suffix.lower() == ".pdf"


def _merge_page_ocr_results(page_results: list[dict]) -> dict:
    merged_blocks: list[dict] = []
    merged_objective_regions: list[dict] = []
    merged_raw_text: list[str] = []
    objective_flagged_total = 0
    flagged_total = 0
    index = 0

    for page_number, result in enumerate(page_results, start=1):
        blocks = result.get("blocks", [])
        if isinstance(blocks, list):
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                normalized = dict(block)
                normalized["index"] = index
                normalized["page"] = page_number
                merged_blocks.append(normalized)
                index += 1

        objective_regions = result.get("objective_regions", [])
        if isinstance(objective_regions, list):
            for region in objective_regions:
                if not isinstance(region, dict):
                    continue
                normalized = dict(region)
                normalized.setdefault("page", page_number)
                merged_objective_regions.append(normalized)

        raw_text = result.get("raw_text")
        if isinstance(raw_text, str) and raw_text.strip():
            merged_raw_text.append(f"[page {page_number}]\n{raw_text}")

        try:
            flagged_total += int(result.get("flagged_count", 0) or 0)
        except Exception:
            pass
        try:
            objective_flagged_total += int(result.get("objective_flagged_count", 0) or 0)
        except Exception:
            pass

    merged: dict = {
        "blocks": merged_blocks,
        "block_count": len(merged_blocks),
        "flagged_count": flagged_total,
        "page_count": len(page_results),
    }
    if merged_objective_regions:
        merged["objective_regions"] = merged_objective_regions
        merged["objective_region_count"] = len(merged_objective_regions)
        merged["objective_flagged_count"] = objective_flagged_total
    if merged_raw_text:
        merged["raw_text"] = "\n\n".join(merged_raw_text)
    return merged


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
        submission.error_message = None
        db.commit()

        image_path = Path(submission.file_path)
        question_type = submission.assignment.question_type

        if _is_pdf(image_path):
            page_images = render_pdf_to_jpeg_bytes(image_path)
            page_results: list[dict] = []
            engines: list[str] = []
            for page_bytes in page_images:
                page_result, page_engine = run_ocr(page_bytes, question_type)
                page_results.append(page_result)
                engines.append(page_engine)
            result = _merge_page_ocr_results(page_results)
            result["engine"] = "+".join(sorted(set(engines))) if engines else "unknown"
            engine = "pdf_multi_page_ocr"
        else:
            # Preprocess (rotation fix, dedup check)
            image_path, image_hash = preprocess_image(image_path)
            submission.image_hash = image_hash
            result, engine = run_ocr(image_path.read_bytes(), question_type)
            result["page_count"] = 1
            for block in result.get("blocks", []):
                if isinstance(block, dict):
                    block.setdefault("page", 1)

        submission.ocr_result  = result
        submission.ocr_engine  = engine
        submission.status      = SubmissionStatus.ocr_done
        submission.error_message = None
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
