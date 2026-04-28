"""Optional code-quality evaluation for code-eval jobs."""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.services.code_eval.contracts import CodeEvalJobRequest
from app.services.genai_client import (
    ModelServiceError,
    build_structured_json_config,
    generate_structured_json_with_retry,
)

settings = get_settings()


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _trim_sources(source_files: dict[str, str], max_bytes: int = 30_000) -> dict[str, str]:
    result: dict[str, str] = {}
    total = 0
    for path in sorted(source_files.keys()):
        content = source_files[path]
        if not isinstance(content, str):
            continue
        encoded = content.encode("utf-8", errors="replace")
        remaining = max_bytes - total
        if remaining <= 0:
            break
        if len(encoded) > remaining:
            result[path] = encoded[:remaining].decode("utf-8", errors="ignore") + "\n# [truncated]"
            break
        result[path] = content
        total += len(encoded)
    return result


def evaluate_code_quality(
    request: CodeEvalJobRequest,
    *,
    earned_score: float,
    max_score: float,
    execution_artifacts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = request.quality_evaluation
    mode = cfg.mode.value
    weight = float(cfg.weight_percent)

    if mode == "disabled" or weight <= 0.0:
        return {
            "enabled": False,
            "applied": False,
            "reason": "quality_mode_disabled_or_weight_zero",
            "weight_percent": weight,
            "mode": mode,
            "correctness_score": earned_score,
            "max_score": max_score,
        }

    dimensions = cfg.dimensions or ["readability", "structure", "naming"]
    schema = {
        "type": "OBJECT",
        "required": ["overall_score", "summary", "dimension_scores"],
        "properties": {
            "overall_score": {"type": "NUMBER"},
            "summary": {"type": "STRING"},
            "dimension_scores": {
                "type": "OBJECT",
                "additionalProperties": {"type": "NUMBER"},
            },
            "strengths": {
                "type": "ARRAY",
                "items": {"type": "STRING"},
            },
            "improvements": {
                "type": "ARRAY",
                "items": {"type": "STRING"},
            },
        },
    }

    model_name = cfg.model_name or settings.resolve_code_healing_model()
    prompt = {
        "task": "Evaluate code quality only (not functional correctness).",
        "language": request.language.value,
        "entrypoint": request.entrypoint,
        "dimensions": dimensions,
        "rubric": cfg.rubric,
        "mode": mode,
        "source_files": _trim_sources(request.source_files),
        "execution_summary": (execution_artifacts or {}).get("testcases", []),
    }

    config = build_structured_json_config(
        response_schema=schema,
        system_instruction=(
            "Score only code quality on a 0-100 scale. "
            "Do not reward or penalize functional correctness in this score."
        ),
        temperature=0.0,
        max_output_tokens=2048,
    )

    try:
        output = generate_structured_json_with_retry(
            model_name=model_name,
            contents=[{"role": "user", "parts": [{"text": str(prompt)}]}],
            config=config,
            operation="Code quality evaluation",
        )
    except ModelServiceError as exc:
        return {
            "enabled": True,
            "applied": False,
            "reason": "quality_model_unavailable",
            "error": str(exc),
            "weight_percent": weight,
            "mode": mode,
            "correctness_score": earned_score,
            "max_score": max_score,
        }

    try:
        quality_score = float(output.get("overall_score", 0.0))
    except Exception:
        quality_score = 0.0
    quality_score = _clamp(quality_score, 0.0, 100.0)

    correctness_pct = 0.0 if max_score <= 0 else _clamp((earned_score / max_score) * 100.0, 0.0, 100.0)
    w = _clamp(weight / 100.0, 0.0, 1.0)
    combined_pct = (correctness_pct * (1.0 - w)) + (quality_score * w)
    adjusted_total = round(max_score * combined_pct / 100.0, 6)

    return {
        "enabled": True,
        "applied": True,
        "reason": "quality_weight_applied",
        "weight_percent": weight,
        "mode": mode,
        "model": model_name,
        "correctness_score": earned_score,
        "max_score": max_score,
        "correctness_percent": round(correctness_pct, 6),
        "quality_score": round(quality_score, 6),
        "combined_percent": round(combined_pct, 6),
        "adjusted_total_score": adjusted_total,
        "summary": output.get("summary"),
        "dimension_scores": output.get("dimension_scores") if isinstance(output.get("dimension_scores"), dict) else {},
        "strengths": output.get("strengths") if isinstance(output.get("strengths"), list) else [],
        "improvements": output.get("improvements") if isinstance(output.get("improvements"), list) else [],
    }
