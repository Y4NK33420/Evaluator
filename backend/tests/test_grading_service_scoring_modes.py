"""Unit tests for grading scoring mode directives and coding-weight policy."""

from app.models import Assignment, QuestionType
from app.services.grading_service import _build_scoring_directives, _resolve_coding_weights


def _mk_assignment(*, question_type: QuestionType, has_code_question: bool) -> Assignment:
    return Assignment(
        course_id="TST101",
        title="Scoring mode test",
        max_marks=100.0,
        question_type=question_type,
        has_code_question=has_code_question,
    )


def test_objective_assignment_uses_question_level_mode():
    assignment = _mk_assignment(question_type=QuestionType.objective, has_code_question=False)
    mode, cfg = _build_scoring_directives(assignment, rubric={"questions": []})

    assert mode == "question_level"
    assert cfg["mode"] == "question_level"
    assert "question_scores" in cfg["directive"]


def test_subjective_assignment_uses_rubric_step_level_mode():
    assignment = _mk_assignment(question_type=QuestionType.subjective, has_code_question=False)
    mode, cfg = _build_scoring_directives(assignment, rubric={"questions": []})

    assert mode == "rubric_step_level"
    assert cfg["mode"] == "rubric_step_level"
    assert "rubric_step_scores" in cfg["directive"]


def test_mixed_assignment_follows_subjective_scoring_mode():
    assignment = _mk_assignment(question_type=QuestionType.mixed, has_code_question=False)
    mode, cfg = _build_scoring_directives(assignment, rubric={"questions": []})

    assert mode == "rubric_step_level"
    assert cfg["mode"] == "rubric_step_level"


def test_coding_assignment_uses_hybrid_mode_with_explicit_weights():
    assignment = _mk_assignment(question_type=QuestionType.subjective, has_code_question=True)
    rubric = {
        "questions": [{"id": "Q1", "max_marks": 100}],
        "scoring_policy": {
            "coding": {
                "rubric_weight": 0.4,
                "testcase_weight": 0.6,
            }
        },
    }
    mode, cfg = _build_scoring_directives(assignment, rubric=rubric)

    assert mode == "hybrid_code"
    assert cfg["mode"] == "hybrid_code"
    assert cfg["coding_weights"]["rubric_weight"] == 0.4
    assert cfg["coding_weights"]["testcase_weight"] == 0.6


def test_coding_weights_allow_100_percent_testcase():
    rubric = {
        "scoring_policy": {
            "coding": {
                "rubric_weight": 0.0,
                "testcase_weight": 1.0,
            }
        }
    }
    rw, tw = _resolve_coding_weights(rubric)
    assert rw == 0.0
    assert tw == 1.0


def test_coding_weights_reject_missing_policy():
    try:
        _resolve_coding_weights({"questions": []})
    except ValueError as exc:
        msg = str(exc)
        assert "rubric_weight" in msg or "scoring_policy.coding" in msg
    else:
        raise AssertionError("Expected ValueError for missing scoring_policy.coding")


def test_coding_weights_reject_non_positive_sum():
    rubric = {
        "scoring_policy": {
            "coding": {
                "rubric_weight": 0.0,
                "testcase_weight": 0.0,
            }
        }
    }
    try:
        _resolve_coding_weights(rubric)
    except ValueError as exc:
        assert "greater than 0" in str(exc)
    else:
        raise AssertionError("Expected ValueError for non-positive coding weight sum")
