"""
OCR service router — google-genai SDK.

Dispatches based on question_type with this policy:
    objective  → Gemini OCR text + GLM region metadata (bbox/confidence)
    subjective → Gemini OCR text
    mixed      → same as subjective

Gemini OCR is always the downstream text source for grading.
GLM is used only for objective-region confidence and spatial metadata.
"""

from __future__ import annotations

import base64
import logging

import httpx
from google.genai import types

from app.config import get_settings
from app.models import QuestionType
from app.services.json_utils import robust_json_loads

log = logging.getLogger(__name__)
settings = get_settings()

# ── Gemini prompt for OCR ─────────────────────────────────────────────────────

_OCR_PROMPT = 'Extract as JSON: {"Question Number": {"Sub-question": "Answer"}}'

_OCR_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "response": {
            "type": "STRING",
            "description": "Stringified JSON of extracted question-wise answers",
        }
    },
    "required": ["response"],
    "propertyOrdering": ["response"],
}

# ── Public router ─────────────────────────────────────────────────────────────

def run_ocr(image_bytes: bytes, question_type: QuestionType) -> tuple[dict, str]:
    """
    OCR an image. Returns (result_dict, engine_name).
    result_dict shape:
        blocks, block_count, flagged_count, engine
    """
    if question_type == QuestionType.objective:
        return _objective_ocr(image_bytes), "gemini+glm_meta"

    # Mixed type follows the subjective path by product decision.
    return _gemini_ocr(
        image_bytes,
        model_name=settings.ocr_model_for("subjective"),
    ), "gemini"


def _objective_ocr(image_bytes: bytes) -> dict:
    """
    Objective flow:
      - Gemini provides OCR text used downstream for grading.
      - GLM provides bbox/confidence metadata for review triage.
    """
    gemini = _gemini_ocr(
        image_bytes,
        model_name=settings.ocr_model_for("objective"),
    )
    glm = _glm_ocr(image_bytes)

    merged = {
        **gemini,
        "engine": "gemini",
        "objective_regions": glm.get("blocks", []),
        "objective_region_count": glm.get("block_count", 0),
        "objective_flagged_count": glm.get("flagged_count", 0),
        # For objective submissions, triage confidence uses GLM region flags.
        "flagged_count": glm.get("flagged_count", 0),
    }
    return merged


# ── GLM-OCR (objective — bboxes + logprob confidence) ────────────────────────

def _glm_ocr(image_bytes: bytes) -> dict:
    b64 = base64.b64encode(image_bytes).decode()
    payload = {
        "image": {"id": "submission", "data": b64, "mime": "image/jpeg"},
        "options": {
            "confidence_threshold": settings.ocr_confidence_threshold,
            "layout_threshold": 0.40,
        },
    }
    try:
        with httpx.Client(timeout=300.0) as client:
            r = client.post(f"{settings.ocr_service_url}/v1/ocr/process", json=payload)
            r.raise_for_status()
            data = r.json()
            return {
                "blocks":        data.get("blocks", []),
                "block_count":   data.get("block_count", 0),
                "flagged_count": data.get("flagged_count", 0),
                "engine":        "glm",
                "processing_ms": data.get("processing_ms", 0),
            }
    except Exception as exc:
        log.error("GLM-OCR failed: %s — falling back to Gemini", exc)
        return _gemini_ocr(
            image_bytes,
            model_name=settings.ocr_model_for("objective"),
        )


# ── Gemini Vision OCR (subjective — handwritten text) ────────────────────────

def _gemini_ocr(image_bytes: bytes, model_name: str) -> dict:
    from app.services.genai_client import (
        ModelServicePermanentError,
        ModelServiceTransientError,
        build_structured_json_config,
        generate_structured_json_with_retry,
    )

    try:
        cfg = build_structured_json_config(
            response_schema=_OCR_RESPONSE_SCHEMA,
            temperature=1,
            top_p=0.95,
            max_output_tokens=65535,
        )
        parsed = generate_structured_json_with_retry(
            model_name=model_name,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                _OCR_PROMPT,
            ],
            config=cfg,
            operation="Gemini OCR",
        )
        response_str = str(parsed.get("response", ""))
        # Try to parse the inner JSON string; fall back to raw string block
        try:
            inner = robust_json_loads(response_str)
        except Exception:
            inner = {"raw": response_str}

        blocks = _flatten_gemini_ocr(inner)
        flagged = sum(1 for b in blocks if b.get("flagged"))
        return {
            "blocks":        blocks,
            "block_count":   len(blocks),
            "flagged_count": flagged,
            "engine":        "gemini",
            "raw_text":      response_str,
            "model":         model_name,
        }
    except (ModelServiceTransientError, ModelServicePermanentError):
        raise
    except Exception as exc:
        log.error("Gemini OCR failed: %s", exc)
        return {"blocks": [], "block_count": 0, "flagged_count": 0,
                "engine": "gemini", "error": str(exc)}


def _flatten_gemini_ocr(inner: dict) -> list[dict]:
    """
    Convert Gemini's {"Q1": {"a": "...", "b": "..."}} structure
    into a flat list of OCRBlock-like dicts.
    """
    blocks = []
    idx = 0
    if isinstance(inner, dict):
        for q_num, sub in inner.items():
            if isinstance(sub, dict):
                for sub_q, answer in sub.items():
                    blocks.append({
                        "index":      idx,
                        "label":      "text",
                        "content":    str(answer),
                        "bbox_2d":    None,       # Gemini doesn't give bboxes
                        "confidence": 0.90,
                        "flagged":    False,
                        "question":   f"{q_num}.{sub_q}",
                    })
                    idx += 1
            else:
                blocks.append({
                    "index":    idx, "label": "text",
                    "content":  str(sub), "bbox_2d": None,
                    "confidence": 0.90, "flagged": False,
                    "question": q_num,
                })
                idx += 1
    return blocks


