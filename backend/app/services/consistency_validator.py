"""Mathematical consistency validator for Gemini-produced grades."""

import logging
from typing import Optional

log = logging.getLogger(__name__)
_TOLERANCE = 0.01   # floating point tolerance for sum check


def _to_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _sum_marks(items: list[dict]) -> float:
    return sum(_to_float(item.get("marks_awarded", 0.0)) for item in items)


def validate_grade(result: dict, max_marks: float) -> list[str]:
    """
    Validate the grading result. Returns a list of issue strings (empty = OK).

    Checks:
      1. total_score <= max_marks
      2. sum(breakdown marks) == total_score
    """
    issues: list[str] = []
    total = result.get("total_score", 0.0)

    # Check 1: ceiling
    if total > max_marks + _TOLERANCE:
        issues.append(
            f"total_score {total} exceeds max_marks {max_marks}"
        )

    score_details = result.get("score_details", {})
    granularity = None
    if isinstance(score_details, dict):
        granularity = score_details.get("granularity")

    # Check 2: breakdown sum
    breakdown = result.get("breakdown", {})
    # For hybrid coding, total_score is intentionally weighted and may differ from
    # raw breakdown mark sums. Hybrid consistency is validated in dedicated checks below.
    if breakdown and granularity != "hybrid_code":
        awarded_sum = sum(
            q.get("marks_awarded", 0.0) for q in breakdown.values()
        )
        if abs(awarded_sum - total) > _TOLERANCE:
            issues.append(
                f"breakdown sum {awarded_sum:.2f} != total_score {total:.2f}"
            )

    if isinstance(score_details, dict):
        if granularity == "question_level":
            question_scores = score_details.get("question_scores", [])
            if isinstance(question_scores, list) and question_scores:
                q_sum = _sum_marks(question_scores)
                if abs(q_sum - total) > _TOLERANCE:
                    issues.append(
                        f"question_scores sum {q_sum:.2f} != total_score {total:.2f}"
                    )

        elif granularity == "rubric_step_level":
            step_scores = score_details.get("rubric_step_scores", [])
            if isinstance(step_scores, list) and step_scores:
                step_sum = _sum_marks(step_scores)
                if abs(step_sum - total) > _TOLERANCE:
                    issues.append(
                        f"rubric_step_scores sum {step_sum:.2f} != total_score {total:.2f}"
                    )

        elif granularity == "hybrid_code":
            coding = score_details.get("coding", {})
            if isinstance(coding, dict):
                rw = _to_float(coding.get("rubric_weight"), 0.0)
                tw = _to_float(coding.get("testcase_weight"), 0.0)
                if abs((rw + tw) - 1.0) > _TOLERANCE:
                    issues.append(
                        f"coding weights must sum to 1.0, got {rw + tw:.4f}"
                    )

                rubric_score = _to_float(coding.get("rubric_score"), 0.0)
                testcase_score = _to_float(coding.get("testcase_score"), 0.0)
                combined_score = _to_float(coding.get("combined_score"), 0.0)
                expected_combined = rw * rubric_score + tw * testcase_score
                if abs(expected_combined - combined_score) > _TOLERANCE:
                    issues.append(
                        "coding combined_score does not match weighted rubric/testcase score"
                    )

                non_coding_score = _to_float(coding.get("non_coding_score"), 0.0)
                expected_total = non_coding_score + combined_score
                if abs(expected_total - total) > _TOLERANCE:
                    issues.append(
                        "total_score does not match non_coding_score + coding combined_score"
                    )

    if issues:
        log.warning("Grade consistency issues: %s", issues)

    return issues
