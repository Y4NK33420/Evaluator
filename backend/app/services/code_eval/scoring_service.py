"""Score aggregation helpers for correctness + optional quality weighting."""

from __future__ import annotations

from typing import Any


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def build_score_breakdown(
    *,
    correctness_score: float,
    max_score: float,
    quality_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    payload = quality_payload if isinstance(quality_payload, dict) else {}
    quality_applied = bool(payload.get("applied"))

    total_score = float(correctness_score)
    if quality_applied:
        try:
            total_score = float(payload.get("adjusted_total_score", total_score))
        except Exception:
            total_score = float(correctness_score)

    if max_score > 0:
        correctness_percent = _clamp((float(correctness_score) / float(max_score)) * 100.0, 0.0, 100.0)
        total_percent = _clamp((float(total_score) / float(max_score)) * 100.0, 0.0, 100.0)
    else:
        correctness_percent = 0.0
        total_percent = 0.0

    return {
        "correctness_score": round(float(correctness_score), 6),
        "max_score": round(float(max_score), 6),
        "correctness_percent": round(correctness_percent, 6),
        "quality_applied": quality_applied,
        "quality_mode": payload.get("mode"),
        "quality_weight_percent": float(payload.get("weight_percent", 0.0) or 0.0),
        "quality_score": payload.get("quality_score"),
        "total_score": round(float(total_score), 6),
        "total_percent": round(total_percent, 6),
    }
