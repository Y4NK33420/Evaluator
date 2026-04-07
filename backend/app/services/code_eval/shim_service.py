"""Shim retry decision logic for code-eval failures.

Supports two retry strategies:
1) Deterministic whitespace-normalized comparison for interface-level noise.
2) Optional Gemini-generated patch synthesis for fixable Python interface mismatches.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.config import get_settings
from app.services.code_eval.contracts import CodeEvalJobRequest
from app.services.genai_client import (
    ModelServiceError,
    build_structured_json_config,
    generate_structured_json_with_retry,
)

_ALLOWED_MISMATCH_TOKENS = {"stdout_mismatch", "stderr_mismatch"}
_BLOCKING_TOKENS = {"timeout", "entrypoint_missing", "output_truncated"}
_MAX_PROMPT_SOURCE_BYTES = 24_000

settings = get_settings()


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


def _safe_relative_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return bool(normalized) and not normalized.startswith("/") and ".." not in normalized.split("/")


def _trim_source_files_for_prompt(source_files: dict[str, str]) -> dict[str, str]:
    trimmed: dict[str, str] = {}
    total = 0
    for path in sorted(source_files.keys()):
        content = source_files[path]
        if not isinstance(content, str):
            continue
        encoded = content.encode("utf-8", errors="replace")
        remaining = _MAX_PROMPT_SOURCE_BYTES - total
        if remaining <= 0:
            break
        if len(encoded) > remaining:
            snippet = encoded[:remaining].decode("utf-8", errors="ignore")
            trimmed[path] = snippet + "\n# [truncated_for_prompt]"
            break
        trimmed[path] = content
        total += len(encoded)
    return trimmed


def _deterministic_whitespace_decision(
    request: CodeEvalJobRequest,
    raw_execution_artifacts: dict[str, Any],
) -> dict[str, Any]:
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
            "stdout": case_result.get("stdout") or "",
            "stderr": case_result.get("stderr") or "",
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
        "# Applied only for interface-level whitespace mismatches.\n"
    )
    return {
        "eligible": True,
        "reason": "all_failed_cases_are_whitespace_only_interface_mismatches",
        "comparison_mode": "whitespace_normalized",
        "shim_source": shim_source,
        "shim_strategy": "deterministic_whitespace_normalization",
        "analyzed_at": _now_iso(),
        "failed_testcases": failed_cases,
        "retry_count": 1,
    }


def _ai_generated_patch_decision(
    request: CodeEvalJobRequest,
    raw_execution_artifacts: dict[str, Any],
    failed_cases: list[dict[str, Any]],
) -> dict[str, Any]:
    if not settings.code_eval_enable_ai_shim_generation:
        return {
            "eligible": False,
            "reason": "ai_shim_generation_disabled",
            "comparison_mode": None,
            "shim_source": None,
            "analyzed_at": _now_iso(),
            "failed_testcases": failed_cases,
        }

    if request.language.value != "python":
        return {
            "eligible": False,
            "reason": "ai_shim_generation_not_enabled_for_language",
            "comparison_mode": None,
            "shim_source": None,
            "analyzed_at": _now_iso(),
            "failed_testcases": failed_cases,
        }

    schema = {
        "type": "OBJECT",
        "required": ["fixable", "reason", "comparison_mode", "updated_files", "updated_entrypoint"],
        "properties": {
            "fixable": {"type": "BOOLEAN"},
            "reason": {"type": "STRING"},
            "comparison_mode": {
                "type": "STRING",
                "enum": ["strict", "whitespace_normalized"],
            },
            "updated_entrypoint": {"type": "STRING"},
            "updated_files": {
                "type": "OBJECT",
                "additionalProperties": {"type": "STRING"},
            },
            "confidence": {"type": "NUMBER"},
        },
    }

    prompt_payload = {
        "task": "Classify if failure is a fixable interface mismatch and propose a safe patch",
        "constraints": [
            "Only patch Python files",
            "Do not change grading logic expectations",
            "Prefer minimal wrappers/adapters",
            "No network/file system side effects outside working directory",
        ],
        "entrypoint": request.entrypoint,
        "source_files": _trim_source_files_for_prompt(request.source_files),
        "failed_testcases": failed_cases[:5],
        "request_quota": request.quota.model_dump(mode="json"),
    }

    config = build_structured_json_config(
        response_schema=schema,
        system_instruction=(
            "You are a code-eval healing agent. Only fix interface mismatches such as stdin/argv/file-mode "
            "adaptation and minor OCR noise. Never attempt to fix student logic."
        ),
        temperature=0.0,
        max_output_tokens=4096,
    )

    model_name = settings.resolve_code_healing_model()
    try:
        model_output = generate_structured_json_with_retry(
            model_name=model_name,
            contents=[{"role": "user", "parts": [{"text": str(prompt_payload)}]}],
            config=config,
            operation="Code-eval AI shim analysis",
        )
    except ModelServiceError as exc:
        return {
            "eligible": False,
            "reason": "ai_shim_model_error",
            "comparison_mode": None,
            "shim_source": None,
            "analyzed_at": _now_iso(),
            "failed_testcases": failed_cases,
            "ai_error": str(exc),
        }

    fixable = bool(model_output.get("fixable"))
    reason = str(model_output.get("reason") or "")
    comparison_mode = str(model_output.get("comparison_mode") or "strict")
    updated_files_raw = model_output.get("updated_files")
    updated_entrypoint = str(model_output.get("updated_entrypoint") or request.entrypoint)

    updated_files: dict[str, str] = {}
    if isinstance(updated_files_raw, dict):
        for path, content in updated_files_raw.items():
            rel_path = str(path)
            if not _safe_relative_path(rel_path):
                return {
                    "eligible": False,
                    "reason": "ai_shim_invalid_patch_path",
                    "comparison_mode": None,
                    "shim_source": None,
                    "analyzed_at": _now_iso(),
                    "failed_testcases": failed_cases,
                }
            updated_files[rel_path] = str(content)

    if not fixable:
        return {
            "eligible": False,
            "reason": "ai_shim_not_fixable",
            "comparison_mode": None,
            "shim_source": None,
            "analyzed_at": _now_iso(),
            "failed_testcases": failed_cases,
            "ai_reason": reason,
        }

    if not updated_files:
        return {
            "eligible": False,
            "reason": "ai_shim_fixable_without_patch_rejected",
            "comparison_mode": None,
            "shim_source": None,
            "analyzed_at": _now_iso(),
            "failed_testcases": failed_cases,
            "ai_reason": reason,
        }

    if not _safe_relative_path(updated_entrypoint):
        updated_entrypoint = request.entrypoint

    return {
        "eligible": True,
        "reason": "ai_generated_interface_shim",
        "comparison_mode": comparison_mode if comparison_mode in {"strict", "whitespace_normalized"} else "strict",
        "shim_source": (
            "# shim_policy: ai_generated_patch\n"
            f"# model: {model_name}\n"
            f"# reason: {reason}\n"
        ),
        "shim_strategy": "ai_generated_patch",
        "analyzed_at": _now_iso(),
        "failed_testcases": failed_cases,
        "patched_source_files": updated_files,
        "patched_entrypoint": updated_entrypoint,
        "retry_count": 1,
        "ai_reason": reason,
    }


def analyze_for_retrying_shim(
    request: CodeEvalJobRequest,
    raw_execution_artifacts: dict[str, Any],
) -> dict[str, Any]:
    """Return shim retry decision and audit payload."""
    deterministic = _deterministic_whitespace_decision(request, raw_execution_artifacts)
    if bool(deterministic.get("eligible")):
        return deterministic

    failed_cases = deterministic.get("failed_testcases")
    if not isinstance(failed_cases, list):
        failed_cases = []

    ai_decision = _ai_generated_patch_decision(request, raw_execution_artifacts, failed_cases)
    if bool(ai_decision.get("eligible")):
        return ai_decision

    reason = str(deterministic.get("reason") or "detected_non_shimmable_failure")
    ai_reason = str(ai_decision.get("reason") or "")
    merged_reason = reason if not ai_reason else f"{reason}|{ai_reason}"
    return {
        "eligible": False,
        "reason": merged_reason,
        "comparison_mode": None,
        "shim_source": None,
        "analyzed_at": _now_iso(),
        "failed_testcases": failed_cases,
        "ai_decision": ai_decision,
    }


def build_retry_request_from_shim_decision(
    request: CodeEvalJobRequest,
    shim_decision: dict[str, Any] | None,
) -> CodeEvalJobRequest:
    if not shim_decision:
        return request

    patched_source_files = shim_decision.get("patched_source_files")
    patched_entrypoint = shim_decision.get("patched_entrypoint")

    if not isinstance(patched_source_files, dict) and not isinstance(patched_entrypoint, str):
        return request

    retry_request = request.model_copy(deep=True)

    if isinstance(patched_source_files, dict):
        for path, content in patched_source_files.items():
            rel_path = str(path)
            if _safe_relative_path(rel_path):
                retry_request.source_files[rel_path] = str(content)

    if isinstance(patched_entrypoint, str) and _safe_relative_path(patched_entrypoint):
        retry_request.entrypoint = patched_entrypoint

    return retry_request
