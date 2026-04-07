"""Shim retry decision logic for code-eval failures.

Supports two retry strategies:
1) Deterministic whitespace-normalized comparison for interface-level noise.
2) Optional Gemini-generated patch synthesis for fixable Python interface mismatches.
"""

from __future__ import annotations

import hashlib
import json
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


def _build_source_signal_map(source_files: dict[str, str]) -> dict[str, bool]:
    combined = "\n".join(str(content) for content in source_files.values() if isinstance(content, str))
    lower = combined.lower()
    return {
        "uses_stdin": ("sys.stdin" in combined) or ("input(" in combined),
        "uses_argv": "sys.argv" in combined,
        "uses_file_input": ("open(" in combined) and (".txt" in lower),
    }


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


def _stable_hash_payload(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _all_cases_interface_like(failed_cases: list[dict[str, Any]]) -> bool:
    if not failed_cases:
        return False
    allowed = {"potential_interface_io_mismatch", "whitespace_only_interface_mismatch"}
    return all(str(case.get("decision_reason") or "") in allowed for case in failed_cases)


def _inject_stdin_to_argv_adapter(source: str) -> str:
    adapter = (
        "import sys\n"
        "# AI-shim fallback adapter: map stdin to argv[1] when program expects CLI args.\n"
        "if len(sys.argv) <= 1:\n"
        "    _shim_stdin = sys.stdin.read()\n"
        "    if _shim_stdin is not None and _shim_stdin.strip():\n"
        "        sys.argv = [sys.argv[0], _shim_stdin.strip()]\n\n"
    )
    return adapter + source


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
    source_signals = _build_source_signal_map(request.source_files)
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
            likely_io_mismatch = False
            if spec.input_mode.value == "stdin":
                stdin_non_empty = bool(_collapse_whitespace(spec.stdin))
                stdout_blank = not bool(_collapse_whitespace(case_result.get("stdout")))
                if stdin_non_empty and stdout_blank and not source_signals["uses_stdin"] and (
                    source_signals["uses_argv"] or source_signals["uses_file_input"]
                ):
                    likely_io_mismatch = True

            if likely_io_mismatch:
                case_audit["decision_reason"] = "potential_interface_io_mismatch"
                case_audit["io_mismatch_signals"] = source_signals
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


def _build_testcase_contracts(
    request: CodeEvalJobRequest,
    failed_cases: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_id = {case.testcase_id: case for case in request.testcases}
    contracts: list[dict[str, Any]] = []
    for failed in failed_cases:
        case_id = str(failed.get("testcase_id") or "")
        spec = by_id.get(case_id)
        if spec is None:
            continue
        contracts.append(
            {
                "testcase_id": case_id,
                "input_mode": spec.input_mode.value,
                "stdin": spec.stdin,
                "argv": list(spec.argv),
                "files": dict(spec.files),
                "expected_stdout": spec.expected_stdout,
                "expected_stderr": spec.expected_stderr,
                "expected_exit_code": spec.expected_exit_code,
                "raw_stdout": failed.get("stdout"),
                "raw_stderr": failed.get("stderr"),
                "failure_tokens": failed.get("failure_tokens") or [],
                "decision_reason": failed.get("decision_reason"),
            }
        )
    return contracts


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
        "task": "Classify whether failure is a fixable interface mismatch and propose a safe patch",
        "constraints": [
            "Only patch Python files",
            "Do not change grading logic expectations",
            "Prefer minimal wrappers/adapters",
            "Treat stdin/argv/file-mode mismatch as interface-level and fixable when contracts indicate I/O adaptation",
            "When stdin testcases are non-empty and observed stdout is blank while source uses argv/file input, classify as fixable interface mismatch",
            "Do not mark as logic bug solely from stdout mismatch without evaluating testcase contracts",
            "No network/file system side effects outside working directory",
        ],
        "entrypoint": request.entrypoint,
        "source_files": _trim_source_files_for_prompt(request.source_files),
        "failed_testcases": failed_cases[:5],
        "testcase_contracts": _build_testcase_contracts(request, failed_cases)[:5],
        "request_quota": request.quota.model_dump(mode="json"),
    }
    model_name = settings.resolve_code_healing_model()
    prompt_hash = _stable_hash_payload(
        {
            "model": model_name,
            "schema": schema,
            "system_instruction": (
                "You are a code-eval healing agent. Only fix interface mismatches such as stdin/argv/file-mode "
                "adaptation and minor OCR noise. Never attempt to fix student logic."
            ),
            "prompt_payload": prompt_payload,
        }
    )

    config = build_structured_json_config(
        response_schema=schema,
        system_instruction=(
            "You are a code-eval healing agent. Only fix interface mismatches such as stdin/argv/file-mode "
            "adaptation and minor OCR noise. Never attempt to fix student logic. "
            "When testcase contracts indicate expected I/O differs from program wiring, return fixable=true with a minimal adapter patch."
        ),
        temperature=0.0,
        max_output_tokens=4096,
    )

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
            "model": model_name,
            "prompt_hash": prompt_hash,
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
                    "model": model_name,
                    "prompt_hash": prompt_hash,
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
            "model": model_name,
            "prompt_hash": prompt_hash,
        }

    if not updated_files:
        if _all_cases_interface_like(failed_cases):
            original_entrypoint_source = request.source_files.get(request.entrypoint)
            if isinstance(original_entrypoint_source, str) and original_entrypoint_source.strip():
                updated_files = {
                    request.entrypoint: _inject_stdin_to_argv_adapter(original_entrypoint_source)
                }
                reason = f"{reason}|fallback_adapter_patch"
            else:
                return {
                    "eligible": False,
                    "reason": "ai_shim_fixable_without_patch_rejected",
                    "comparison_mode": None,
                    "shim_source": None,
                    "analyzed_at": _now_iso(),
                    "failed_testcases": failed_cases,
                    "ai_reason": reason,
                    "model": model_name,
                    "prompt_hash": prompt_hash,
                }
        else:
            return {
                "eligible": False,
                "reason": "ai_shim_fixable_without_patch_rejected",
                "comparison_mode": None,
                "shim_source": None,
                "analyzed_at": _now_iso(),
                "failed_testcases": failed_cases,
                "ai_reason": reason,
                "model": model_name,
                "prompt_hash": prompt_hash,
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
        "model": model_name,
        "prompt_hash": prompt_hash,
        "decision": {
            "fixable": fixable,
            "comparison_mode": comparison_mode,
            "confidence": model_output.get("confidence"),
            "updated_entrypoint": updated_entrypoint,
            "patched_files_count": len(updated_files),
        },
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
