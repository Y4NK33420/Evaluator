"""Deterministic shim retry decision logic for code-eval failures."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.services.code_eval.contracts import CodeEvalJobRequest

_ALLOWED_MISMATCH_TOKENS = {"stdout_mismatch", "stderr_mismatch"}
_BLOCKING_TOKENS = {"timeout", "entrypoint_missing", "output_truncated"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _collapse_whitespace(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


def _parse_failure_tokens(reason: str | None) -> set[str]:
    if not reason:
        return set()
    return {token for token in str(reason).split("|") if token}


def analyze_for_retrying_shim(
    request: CodeEvalJobRequest,
    raw_execution_artifacts: dict[str, Any],
) -> dict[str, Any]:
    """Return shim retry decision and audit payload.

    Retry is only allowed for deterministic interface mismatches where failed
    testcases differ from expectations by whitespace formatting only.
    """
    testcases = raw_execution_artifacts.get("testcases")
    if not isinstance(testcases, list):
        return {
            "eligible": False,
            "reason": "raw_execution_artifacts_missing_testcases",
            "comparison_mode": None,
            "shim_source": None,
            "analyzed_at": _now_iso(),
            "failed_testcases": [],
        }

    if request.language.value != "python":
        return {
            "eligible": False,
            "reason": "shim_retry_not_enabled_for_language",
            "comparison_mode": None,
            "shim_source": None,
            "analyzed_at": _now_iso(),
            "failed_testcases": [],
        }

    spec_by_id = {case.testcase_id: case for case in request.testcases}
    failed_cases: list[dict[str, Any]] = []
    whitespace_only_failures: list[str] = []

    for case_result in testcases:
        if not isinstance(case_result, dict):
            continue
        if bool(case_result.get("passed")):
            continue

        case_id = str(case_result.get("testcase_id") or "")
        tokens = _parse_failure_tokens(case_result.get("failure_reason"))
        case_audit = {
            "testcase_id": case_id,
            "failure_tokens": sorted(tokens),
            "eligible": False,
            "decision_reason": "",
        }

        if any(token.startswith("exit_code_expected_") for token in tokens):
            case_audit["decision_reason"] = "exit_code_mismatch"
            failed_cases.append(case_audit)
            continue

        if tokens & _BLOCKING_TOKENS:
            case_audit["decision_reason"] = "blocking_runtime_failure"
            failed_cases.append(case_audit)
            continue

        unknown_tokens = tokens - _ALLOWED_MISMATCH_TOKENS
        if unknown_tokens:
            case_audit["decision_reason"] = "contains_non_interface_failure_tokens"
            failed_cases.append(case_audit)
            continue

        spec = spec_by_id.get(case_id)
        if spec is None:
            case_audit["decision_reason"] = "testcase_spec_not_found"
            failed_cases.append(case_audit)
            continue

        stdout_ok = True
        if "stdout_mismatch" in tokens:
            stdout_ok = _collapse_whitespace(case_result.get("stdout")) == _collapse_whitespace(
                spec.expected_stdout
            )

        stderr_ok = True
        if "stderr_mismatch" in tokens:
            stderr_ok = _collapse_whitespace(case_result.get("stderr")) == _collapse_whitespace(
                spec.expected_stderr
            )

        if stdout_ok and stderr_ok and tokens:
            case_audit["eligible"] = True
            case_audit["decision_reason"] = "whitespace_only_interface_mismatch"
            whitespace_only_failures.append(case_id)
        else:
            case_audit["decision_reason"] = "output_difference_not_whitespace_only"

        failed_cases.append(case_audit)

    if not failed_cases:
        return {
            "eligible": False,
            "reason": "no_failed_testcases_to_analyze",
            "comparison_mode": None,
            "shim_source": None,
            "analyzed_at": _now_iso(),
            "failed_testcases": [],
        }

    all_failed_eligible = all(bool(case.get("eligible")) for case in failed_cases)
    if not all_failed_eligible:
        return {
            "eligible": False,
            "reason": "detected_non_shimmable_failure",
            "comparison_mode": None,
            "shim_source": None,
            "analyzed_at": _now_iso(),
            "failed_testcases": failed_cases,
        }

    shim_source = (
        "# shim_policy: whitespace_normalized_output_compare\n"
        "# Applied only after AI_ANALYZING classified failures as interface-level whitespace mismatches.\n"
    )
    return {
        "eligible": True,
        "reason": "all_failed_cases_are_whitespace_only_interface_mismatches",
        "comparison_mode": "whitespace_normalized",
        "shim_source": shim_source,
        "analyzed_at": _now_iso(),
        "failed_testcases": failed_cases,
        "retry_count": 1,
    }
