"""Unit tests for optional code-quality scoring lane."""

from app.services.code_eval.contracts import (
    CodeEvalJobRequest,
    InputMode,
    LanguageRuntime,
    QualityEvaluationConfig,
    QualityEvaluationMode,
    QualityRubricSourceMode,
    TestCaseSpec,
)
from app.services.code_eval.quality_service import evaluate_code_quality
from app.services.genai_client import ModelServiceTransientError


def _request(mode: QualityEvaluationMode, weight_percent: float) -> CodeEvalJobRequest:
    return CodeEvalJobRequest(
        assignment_id="a1",
        submission_id="s1",
        language=LanguageRuntime.PYTHON,
        entrypoint="main.py",
        source_files={"main.py": "print('ok')\n"},
        testcases=[
            TestCaseSpec(
                testcase_id="t1",
                input_mode=InputMode.STDIN,
                stdin="",
                expected_stdout="ok",
                expected_stderr="",
                expected_exit_code=0,
            )
        ],
        quality_evaluation=QualityEvaluationConfig(
            mandatory_per_assignment=True,
            mode=mode,
            rubric_source_mode=QualityRubricSourceMode.INSTRUCTOR_PROVIDED,
            weight_percent=weight_percent,
            dimensions=["readability", "structure"],
            rubric="Readability and structure",
        ),
    )


def test_quality_disabled_returns_not_applied():
    req = _request(QualityEvaluationMode.DISABLED, 0.0)

    payload = evaluate_code_quality(req, earned_score=1.0, max_score=1.0, execution_artifacts={})

    assert payload["enabled"] is False
    assert payload["applied"] is False


def test_quality_applies_weighted_score_when_model_returns_result(monkeypatch):
    req = _request(QualityEvaluationMode.RUBRIC_ONLY, 20.0)

    def fake_model_call(**_kwargs):
        return {
            "overall_score": 80,
            "summary": "Good quality",
            "dimension_scores": {"readability": 82, "structure": 78},
            "strengths": ["clear naming"],
            "improvements": ["add comments"],
        }

    monkeypatch.setattr("app.services.code_eval.quality_service.generate_structured_json_with_retry", fake_model_call)

    payload = evaluate_code_quality(req, earned_score=60.0, max_score=100.0, execution_artifacts={"testcases": []})

    assert payload["enabled"] is True
    assert payload["applied"] is True
    assert payload["adjusted_total_score"] == 64.0


def test_quality_falls_back_when_model_unavailable(monkeypatch):
    req = _request(QualityEvaluationMode.RUBRIC_ONLY, 25.0)

    def failing_model_call(**_kwargs):
        raise ModelServiceTransientError("temporary model outage")

    monkeypatch.setattr("app.services.code_eval.quality_service.generate_structured_json_with_retry", failing_model_call)

    payload = evaluate_code_quality(req, earned_score=70.0, max_score=100.0, execution_artifacts={})

    assert payload["enabled"] is True
    assert payload["applied"] is False
    assert payload["reason"] == "quality_model_unavailable"
