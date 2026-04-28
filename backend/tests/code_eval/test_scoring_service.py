"""Unit tests for score aggregation and breakdown fields."""

from app.services.code_eval.scoring_service import build_score_breakdown


def test_score_breakdown_without_quality_lane():
    breakdown = build_score_breakdown(
        correctness_score=7.0,
        max_score=10.0,
        quality_payload={
            "applied": False,
            "mode": "disabled",
            "weight_percent": 0.0,
        },
    )

    assert breakdown["total_score"] == 7.0
    assert breakdown["correctness_percent"] == 70.0
    assert breakdown["quality_applied"] is False


def test_score_breakdown_with_quality_lane_applied():
    breakdown = build_score_breakdown(
        correctness_score=60.0,
        max_score=100.0,
        quality_payload={
            "applied": True,
            "mode": "rubric_only",
            "weight_percent": 20.0,
            "quality_score": 80.0,
            "adjusted_total_score": 64.0,
        },
    )

    assert breakdown["quality_applied"] is True
    assert breakdown["quality_weight_percent"] == 20.0
    assert breakdown["total_score"] == 64.0
    assert breakdown["total_percent"] == 64.0


def test_score_breakdown_handles_zero_max_score():
    breakdown = build_score_breakdown(
        correctness_score=0.0,
        max_score=0.0,
        quality_payload={"applied": False},
    )

    assert breakdown["correctness_percent"] == 0.0
    assert breakdown["total_percent"] == 0.0
