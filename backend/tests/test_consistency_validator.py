"""Unit tests for grade consistency validation across score detail granularities."""

from app.services.consistency_validator import validate_grade


def test_question_level_details_match_total():
    result = {
        "total_score": 30.0,
        "breakdown": {
            "Q1": {"marks_awarded": 10.0},
            "Q2": {"marks_awarded": 20.0},
        },
        "score_details": {
            "granularity": "question_level",
            "question_scores": [
                {"question_id": "Q1", "marks_awarded": 10.0},
                {"question_id": "Q2", "marks_awarded": 20.0},
            ],
        },
    }
    assert validate_grade(result, max_marks=30.0) == []


def test_rubric_step_level_sum_mismatch_is_flagged():
    result = {
        "total_score": 25.0,
        "breakdown": {
            "Q1": {"marks_awarded": 25.0},
        },
        "score_details": {
            "granularity": "rubric_step_level",
            "rubric_step_scores": [
                {"step_id": "Q1.S1", "marks_awarded": 10.0},
                {"step_id": "Q1.S2", "marks_awarded": 10.0},
            ],
        },
    }
    issues = validate_grade(result, max_marks=30.0)
    assert any("rubric_step_scores sum" in issue for issue in issues)


def test_hybrid_code_weighted_formula_is_enforced():
    result = {
        "total_score": 80.0,
        "breakdown": {
            "Q1": {"marks_awarded": 80.0},
        },
        "score_details": {
            "granularity": "hybrid_code",
            "coding": {
                "rubric_weight": 0.2,
                "testcase_weight": 0.8,
                "rubric_score": 50.0,
                "testcase_score": 90.0,
                # Expected combined = 0.2*50 + 0.8*90 = 82
                "combined_score": 70.0,
                "non_coding_score": 10.0,
            },
        },
    }
    issues = validate_grade(result, max_marks=100.0)
    assert any("coding combined_score" in issue for issue in issues)


def test_hybrid_code_supports_full_testcase_weighting():
    result = {
        "total_score": 90.0,
        "breakdown": {
            "Q1": {"marks_awarded": 90.0},
        },
        "score_details": {
            "granularity": "hybrid_code",
            "coding": {
                "rubric_weight": 0.0,
                "testcase_weight": 1.0,
                "rubric_score": 50.0,
                "testcase_score": 90.0,
                "combined_score": 90.0,
                "non_coding_score": 0.0,
            },
        },
    }
    assert validate_grade(result, max_marks=100.0) == []
