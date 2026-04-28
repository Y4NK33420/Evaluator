"""
Google grading service — google-genai SDK.

Single consolidated API call per student:
  Input : OCR blocks + assignment + rubric JSON
  Output: {total_score, breakdown, feedback, is_truncated}
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from app.config import get_settings
from app.models import QuestionType
from app.services.genai_client import (
    build_structured_json_config,
    generate_structured_json_with_retry,
)

log = logging.getLogger(__name__)
settings = get_settings()

_SYSTEM_PROMPT = """You are a strict, fair university exam grader.
You will receive:
1. OCR-extracted student answers (may contain OCR errors — use academic judgement).
2. The assignment rubric with step-wise marks.

Rules:
- Apply only the provided rubric. No bonus marks. No negative marking.
- If an answer is cut off mid-sentence, mark is_truncated: true for that question.
- Sum of all question marks must equal total_score exactly.
- total_score must not exceed max_marks.
- Before returning, perform an internal arithmetic self-check:
  - breakdown[Q].marks_awarded must equal the sum of that question's detailed rows in score_details.
  - total_score must equal the sum implied by score_details.
  - If any mismatch exists, fix the JSON values before returning.

Return ONLY valid JSON — no markdown fences, no commentary."""

_PROMPT_TEMPLATE = """\
Assignment: {title}
Max marks : {max_marks}
Question type: {question_type}
Has code question: {has_code_question}

OCR Extracted Answers:
{ocr_text}

Rubric:
{rubric_json}

Scoring mode:
{scoring_mode}

Scoring directives:
{scoring_directives}

Follow the provided structured response schema exactly."""

_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "total_score":  {"type": "NUMBER", "description": "Overall awarded score"},
        "is_truncated": {"type": "BOOLEAN", "description": "True if any answer appears truncated"},
        "score_details": {"type": "OBJECT", "description": "Granularity-specific score details"},
        "breakdown":    {"type": "OBJECT", "description": "Per-question marks and feedback"},
    },
    "required": ["total_score", "is_truncated", "score_details", "breakdown"],
    "propertyOrdering": ["total_score", "is_truncated", "score_details", "breakdown"],
}


def _build_response_schema(scoring_mode: str) -> dict:
    breakdown_entries_schema = {
        "type": "ARRAY",
        "minItems": 1,
        "items": {
            "type": "OBJECT",
            "properties": {
                "question_id": {"type": "STRING"},
                "marks_awarded": {"type": "NUMBER"},
                "max_marks": {"type": "NUMBER"},
                "feedback": {"type": "STRING"},
                "is_truncated": {"type": "BOOLEAN"},
            },
            "required": [
                "question_id",
                "marks_awarded",
                "max_marks",
                "feedback",
                "is_truncated",
            ],
            "propertyOrdering": [
                "question_id",
                "marks_awarded",
                "max_marks",
                "feedback",
                "is_truncated",
            ],
        },
    }

    if scoring_mode == "question_level":
        return {
            "type": "OBJECT",
            "properties": {
                "total_score": {"type": "NUMBER"},
                "is_truncated": {"type": "BOOLEAN"},
                "score_details": {
                    "type": "OBJECT",
                    "properties": {
                        "granularity": {
                            "type": "STRING",
                            "enum": ["question_level"],
                        },
                        "question_scores": {
                            "type": "ARRAY",
                            "minItems": 1,
                            "items": {
                                "type": "OBJECT",
                                "properties": {
                                    "question_id": {"type": "STRING"},
                                    "marks_awarded": {"type": "NUMBER"},
                                    "max_marks": {"type": "NUMBER"},
                                    "feedback": {"type": "STRING"},
                                },
                                "required": [
                                    "question_id",
                                    "marks_awarded",
                                    "max_marks",
                                    "feedback",
                                ],
                                "propertyOrdering": [
                                    "question_id",
                                    "marks_awarded",
                                    "max_marks",
                                    "feedback",
                                ],
                            },
                        },
                    },
                    "required": ["granularity", "question_scores"],
                    "propertyOrdering": ["granularity", "question_scores"],
                },
                "breakdown": {"type": "OBJECT"},
                "breakdown_entries": breakdown_entries_schema,
            },
            "required": [
                "total_score",
                "is_truncated",
                "score_details",
                "breakdown",
                "breakdown_entries",
            ],
            "propertyOrdering": [
                "total_score",
                "is_truncated",
                "score_details",
                "breakdown",
                "breakdown_entries",
            ],
        }

    if scoring_mode == "rubric_step_level":
        return {
            "type": "OBJECT",
            "properties": {
                "total_score": {"type": "NUMBER"},
                "is_truncated": {"type": "BOOLEAN"},
                "score_details": {
                    "type": "OBJECT",
                    "properties": {
                        "granularity": {
                            "type": "STRING",
                            "enum": ["rubric_step_level"],
                        },
                        "rubric_step_scores": {
                            "type": "ARRAY",
                            "minItems": 1,
                            "items": {
                                "type": "OBJECT",
                                "properties": {
                                    "question_id": {"type": "STRING"},
                                    "step_id": {"type": "STRING"},
                                    "step": {"type": "STRING"},
                                    "marks_awarded": {"type": "NUMBER"},
                                    "max_marks": {"type": "NUMBER"},
                                    "feedback": {"type": "STRING"},
                                },
                                "required": [
                                    "question_id",
                                    "step_id",
                                    "step",
                                    "marks_awarded",
                                    "max_marks",
                                    "feedback",
                                ],
                                "propertyOrdering": [
                                    "question_id",
                                    "step_id",
                                    "step",
                                    "marks_awarded",
                                    "max_marks",
                                    "feedback",
                                ],
                            },
                        },
                    },
                    "required": ["granularity", "rubric_step_scores"],
                    "propertyOrdering": ["granularity", "rubric_step_scores"],
                },
                "breakdown": {"type": "OBJECT"},
                "breakdown_entries": breakdown_entries_schema,
            },
            "required": [
                "total_score",
                "is_truncated",
                "score_details",
                "breakdown",
                "breakdown_entries",
            ],
            "propertyOrdering": [
                "total_score",
                "is_truncated",
                "score_details",
                "breakdown",
                "breakdown_entries",
            ],
        }

    # hybrid_code
    return {
        "type": "OBJECT",
        "properties": {
            "total_score": {"type": "NUMBER"},
            "is_truncated": {"type": "BOOLEAN"},
            "score_details": {
                "type": "OBJECT",
                "properties": {
                    "granularity": {
                        "type": "STRING",
                        "enum": ["hybrid_code"],
                    },
                    "rubric_step_scores": {
                        "type": "ARRAY",
                        "minItems": 1,
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "question_id": {"type": "STRING"},
                                "step_id": {"type": "STRING"},
                                "step": {"type": "STRING"},
                                "marks_awarded": {"type": "NUMBER"},
                                "max_marks": {"type": "NUMBER"},
                                "feedback": {"type": "STRING"},
                            },
                            "required": [
                                "question_id",
                                "step_id",
                                "step",
                                "marks_awarded",
                                "max_marks",
                                "feedback",
                            ],
                            "propertyOrdering": [
                                "question_id",
                                "step_id",
                                "step",
                                "marks_awarded",
                                "max_marks",
                                "feedback",
                            ],
                        },
                    },
                    "coding": {
                        "type": "OBJECT",
                        "properties": {
                            "rubric_weight": {"type": "NUMBER"},
                            "testcase_weight": {"type": "NUMBER"},
                            "rubric_score": {"type": "NUMBER"},
                            "testcase_score": {"type": "NUMBER"},
                            "combined_score": {"type": "NUMBER"},
                            "non_coding_score": {"type": "NUMBER"},
                        },
                        "required": [
                            "rubric_weight",
                            "testcase_weight",
                            "rubric_score",
                            "testcase_score",
                            "combined_score",
                            "non_coding_score",
                        ],
                        "propertyOrdering": [
                            "rubric_weight",
                            "testcase_weight",
                            "rubric_score",
                            "testcase_score",
                            "combined_score",
                            "non_coding_score",
                        ],
                    },
                },
                "required": ["granularity", "rubric_step_scores", "coding"],
                "propertyOrdering": ["granularity", "rubric_step_scores", "coding"],
            },
            "breakdown": {"type": "OBJECT"},
            "breakdown_entries": breakdown_entries_schema,
        },
        "required": [
            "total_score",
            "is_truncated",
            "score_details",
            "breakdown",
            "breakdown_entries",
        ],
        "propertyOrdering": [
            "total_score",
            "is_truncated",
            "score_details",
            "breakdown",
            "breakdown_entries",
        ],
    }


def _has_required_scoring_payload(result: dict, scoring_mode: str) -> bool:
    score_details = result.get("score_details")
    breakdown_entries = result.get("breakdown_entries")
    if not isinstance(score_details, dict):
        return False
    if not isinstance(breakdown_entries, list) or len(breakdown_entries) == 0:
        return False

    if scoring_mode == "question_level":
        scores = score_details.get("question_scores")
        return isinstance(scores, list) and len(scores) > 0

    if scoring_mode == "rubric_step_level":
        scores = score_details.get("rubric_step_scores")
        return isinstance(scores, list) and len(scores) > 0

    # hybrid_code
    scores = score_details.get("rubric_step_scores")
    coding = score_details.get("coding")
    return isinstance(scores, list) and len(scores) > 0 and isinstance(coding, dict)


def _to_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_total_score(result: dict, scoring_mode: str) -> None:
    """Force internal math consistency from structured detail rows."""
    details = result.get("score_details")
    if not isinstance(details, dict):
        return

    derived_total: float | None = None
    if scoring_mode == "question_level":
        rows = details.get("question_scores", [])
        if isinstance(rows, list) and rows:
            derived_total = sum(_to_float(r.get("marks_awarded", 0.0)) for r in rows)
    elif scoring_mode == "rubric_step_level":
        rows = details.get("rubric_step_scores", [])
        if isinstance(rows, list) and rows:
            derived_total = sum(_to_float(r.get("marks_awarded", 0.0)) for r in rows)
    else:
        coding = details.get("coding")
        if isinstance(coding, dict):
            derived_total = _to_float(coding.get("non_coding_score"), 0.0) + _to_float(
                coding.get("combined_score"), 0.0
            )
        else:
            rows = details.get("rubric_step_scores", [])
            if isinstance(rows, list) and rows:
                derived_total = sum(_to_float(r.get("marks_awarded", 0.0)) for r in rows)

    if derived_total is not None:
        result["total_score"] = round(derived_total, 4)


def _rebuild_breakdown_from_score_details(result: dict, scoring_mode: str) -> None:
    """Authoritative post-processing: derive breakdown marks from score_details."""
    details = result.get("score_details")
    if not isinstance(details, dict):
        return

    existing = result.get("breakdown")
    if not isinstance(existing, dict):
        existing = {}

    if scoring_mode == "question_level":
        rows = details.get("question_scores", [])
        if not isinstance(rows, list):
            return
        rebuilt: dict[str, dict] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            qid = str(row.get("question_id", "")).strip()
            if not qid:
                continue
            prev = existing.get(qid) if isinstance(existing.get(qid), dict) else {}
            rebuilt[qid] = {
                "marks_awarded": _to_float(row.get("marks_awarded", 0.0)),
                "max_marks": _to_float(row.get("max_marks", 0.0)),
                "feedback": str(prev.get("feedback", row.get("feedback", ""))),
                "is_truncated": bool(prev.get("is_truncated", result.get("is_truncated", False))),
            }
        if rebuilt:
            result["breakdown"] = rebuilt
        return

    if scoring_mode == "rubric_step_level":
        rows = details.get("rubric_step_scores", [])
        if not isinstance(rows, list):
            return
        agg: dict[str, dict] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            qid = str(row.get("question_id", "")).strip()
            if not qid:
                continue
            marks = _to_float(row.get("marks_awarded", 0.0))
            max_marks = _to_float(row.get("max_marks", 0.0))
            slot = agg.setdefault(qid, {"marks_awarded": 0.0, "max_marks": 0.0})
            slot["marks_awarded"] += marks
            slot["max_marks"] += max_marks

        rebuilt: dict[str, dict] = {}
        for qid, sums in agg.items():
            prev = existing.get(qid) if isinstance(existing.get(qid), dict) else {}
            rebuilt[qid] = {
                "marks_awarded": round(_to_float(sums.get("marks_awarded", 0.0)), 4),
                "max_marks": round(_to_float(sums.get("max_marks", 0.0)), 4),
                "feedback": str(prev.get("feedback", "")),
                "is_truncated": bool(prev.get("is_truncated", result.get("is_truncated", False))),
            }
        if rebuilt:
            result["breakdown"] = rebuilt
        return

    # hybrid_code: keep question-level narrative breakdown from model,
    # because coding-weight composition can intentionally diverge from raw sums.
    return


def _build_ocr_text(ocr_result: dict) -> str:
    blocks = ocr_result.get("blocks", [])
    if not blocks:
        return "(No OCR text extracted)"
    lines = []
    for b in blocks:
        page = b.get("page")
        q = b.get("question", "")
        parts = []
        if page is not None:
            parts.append(f"p{page}")
        if q:
            parts.append(str(q))
        prefix = f"[{' | '.join(parts)}] " if parts else ""
        lines.append(f"{prefix}{b.get('content', '').strip()}")
    return "\n".join(lines)


def _normalize_weight(value: object, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if parsed < 0:
        return default
    return parsed


def _resolve_coding_weights(rubric: dict) -> tuple[float, float]:
    policy = rubric.get("scoring_policy", {})
    coding = policy.get("coding", {}) if isinstance(policy, dict) else {}

    if not isinstance(coding, dict):
        raise ValueError(
            "Coding assignments require scoring_policy.coding with "
            "rubric_weight and testcase_weight."
        )

    if "rubric_weight" not in coding or "testcase_weight" not in coding:
        raise ValueError(
            "Coding assignments require both rubric_weight and testcase_weight."
        )

    try:
        rubric_w = float(coding.get("rubric_weight"))
        testcase_w = float(coding.get("testcase_weight"))
    except (TypeError, ValueError):
        raise ValueError("rubric_weight and testcase_weight must be numeric values.")

    if rubric_w < 0 or testcase_w < 0:
        raise ValueError("rubric_weight and testcase_weight must be non-negative.")

    total = rubric_w + testcase_w
    if total <= 0:
        raise ValueError("rubric_weight + testcase_weight must be greater than 0.")

    # Normalize to ensure strict convex combination.
    return rubric_w / total, testcase_w / total


def _resolve_scoring_mode(assignment) -> str:
    if assignment.has_code_question:
        return "hybrid_code"
    if assignment.question_type == QuestionType.objective:
        return "question_level"
    # subjective and mixed both use rubric-step-level scoring detail.
    return "rubric_step_level"


def _build_scoring_directives(assignment, rubric: dict) -> tuple[str, dict]:
    mode = _resolve_scoring_mode(assignment)

    if mode == "question_level":
        directive = (
            "Use question-level scoring only. In score_details return: "
            "{\"granularity\": \"question_level\", \"question_scores\": ["
            "{\"question_id\": \"Q1\", \"marks_awarded\": <float>, "
            "\"max_marks\": <float>, \"feedback\": \"...\"}]}. "
            "Do not use rubric_step_scores or testcase-level entries."
        )
        return mode, {
            "mode": mode,
            "coding_weights": None,
            "directive": directive,
        }

    if mode == "rubric_step_level":
        directive = (
            "Use rubric-step-level scoring. In score_details return: "
            "{\"granularity\": \"rubric_step_level\", \"rubric_step_scores\": ["
            "{\"question_id\": \"Q1\", \"step_id\": \"Q1.S1\", "
            "\"step\": \"...\", \"marks_awarded\": <float>, "
            "\"max_marks\": <float>, \"feedback\": \"...\"}]}."
        )
        return mode, {
            "mode": mode,
            "coding_weights": None,
            "directive": directive,
        }

    rubric_weight, testcase_weight = _resolve_coding_weights(rubric)
    directive = (
        "This assignment has coding and must use hybrid scoring. "
        f"Use rubric_weight={rubric_weight:.6f} and testcase_weight={testcase_weight:.6f}. "
        "Return score_details with this shape: "
        "{\"granularity\": \"hybrid_code\", "
        "\"rubric_step_scores\": [...], "
        "\"coding\": {"
        "\"rubric_weight\": <float>, \"testcase_weight\": <float>, "
        "\"rubric_score\": <float>, \"testcase_score\": <float>, "
        "\"combined_score\": <float>, \"non_coding_score\": <float>, "
        "\"testcases\": [{\"testcase_id\": \"TC1\", \"passed\": <bool>, "
        "\"marks_awarded\": <float>, \"max_marks\": <float>, \"feedback\": \"...\"}]}}. "
        "combined_score must equal rubric_weight * rubric_score + testcase_weight * testcase_score. "
        "total_score must equal non_coding_score + combined_score. "
        "If instructor wants 100% testcase based, testcase_weight can be 1.0 and rubric_weight 0.0."
    )
    return mode, {
        "mode": mode,
        "coding_weights": {
            "rubric_weight": rubric_weight,
            "testcase_weight": testcase_weight,
        },
        "directive": directive,
    }


def grade_submission(
    ocr_result: dict,
    assignment,
    rubric: Optional[dict],
) -> dict:
    """
    Call Gemini to grade one submission.
    Returns a grade result dict ready to store in Grade.breakdown_json.
    """
    if not rubric:
        raise ValueError("Approved rubric is required before grading.")

    question_type = assignment.question_type.value
    if question_type == "mixed":
        question_type = "subjective"

    model_name = settings.grading_model_for(question_type)
    scoring_mode, scoring_config = _build_scoring_directives(assignment, rubric)

    prompt = _PROMPT_TEMPLATE.format(
        title         = assignment.title,
        max_marks     = assignment.max_marks,
        question_type = question_type,
        has_code_question = assignment.has_code_question,
        ocr_text      = _build_ocr_text(ocr_result),
        rubric_json   = json.dumps(rubric, indent=2),
        scoring_mode  = scoring_mode,
        scoring_directives = scoring_config["directive"],
    )

    response_schema = _build_response_schema(scoring_mode)
    result: dict | None = None
    prompts = [
        prompt,
        (
            prompt
            + "\n\nIMPORTANT: score_details and breakdown must be fully populated "
              "with concrete entries. Do not return empty objects. "
              "Run a final arithmetic self-check and fix any mismatch before returning."
        ),
    ]
    for attempt, attempt_prompt in enumerate(prompts, start=1):
        cfg = build_structured_json_config(
            response_schema=response_schema,
            system_instruction=_SYSTEM_PROMPT,
            temperature=0.0,
            top_p=0.95,
            max_output_tokens=8192,
        )

        result = generate_structured_json_with_retry(
            model_name=model_name,
            contents=attempt_prompt,
            config=cfg,
            operation="Submission grading",
        )
        if _has_required_scoring_payload(result, scoring_mode):
            break
        log.warning(
            "Grading structured output missing required scoring payload on attempt %d",
            attempt,
        )

    if result is None or not _has_required_scoring_payload(result, scoring_mode):
        raise ValueError(
            "Model response missing required structured scoring payload after retries."
        )

    if (not isinstance(result.get("breakdown"), dict)) or (not result.get("breakdown")):
        synthesized: dict[str, dict] = {}
        for row in result.get("breakdown_entries", []):
            qid = str(row.get("question_id", "")).strip()
            if not qid:
                continue
            synthesized[qid] = {
                "marks_awarded": row.get("marks_awarded", 0.0),
                "max_marks": row.get("max_marks", 0.0),
                "feedback": row.get("feedback", ""),
                "is_truncated": row.get("is_truncated", False),
            }
        result["breakdown"] = synthesized

    result.pop("breakdown_entries", None)
    _normalize_total_score(result, scoring_mode)
    _rebuild_breakdown_from_score_details(result, scoring_mode)

    result["assignment_id"] = str(assignment.id)
    result["ocr_engine"]    = ocr_result.get("engine", "unknown")
    result["model"]         = model_name
    result["scoring_mode"]  = scoring_mode
    result["scoring_config"] = scoring_config
    return result
