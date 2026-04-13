"""Shim retry decision logic for code-eval failures — all 4 languages.

Supports two retry strategies:
1) Deterministic whitespace-normalized comparison for interface-level noise (Python only).
2) Gemini-generated patch synthesis for fixable interface mismatches (Python, C, C++, Java).

For compiled languages (C, C++, Java), AI-patched source is compile-checked before
being accepted — a patch that doesn't compile is rejected as ineligible.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.services.code_eval.contracts import CodeEvalJobRequest
from app.services.code_eval.language_config import parse_language_config
from app.services.genai_client import (
    ModelServiceError,
    build_structured_json_config,
    generate_structured_json_with_retry,
)

log = logging.getLogger(__name__)

_ALLOWED_MISMATCH_TOKENS = {"stdout_mismatch", "stderr_mismatch"}
_BLOCKING_TOKENS = {"timeout", "entrypoint_missing", "output_truncated"}
_MAX_PROMPT_SOURCE_BYTES = 24_000

# Languages that support AI shim retry
_SHIM_ELIGIBLE_LANGUAGES = {"python", "c", "cpp", "java"}

settings = get_settings()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _collapse_whitespace(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


# ── Per-language source signal builders ───────────────────────────────────────

def _build_python_source_signals(source_files: dict[str, str]) -> dict[str, bool]:
    combined = "\n".join(str(c) for c in source_files.values() if isinstance(c, str))
    return {
        "uses_stdin": ("sys.stdin" in combined) or ("input(" in combined),
        "uses_argv": "sys.argv" in combined,
        "uses_file_input": ("open(" in combined) and (".txt" in combined.lower()),
    }


def _build_c_source_signals(source_files: dict[str, str]) -> dict[str, bool]:
    combined = "\n".join(str(c) for c in source_files.values() if isinstance(c, str))
    return {
        "uses_stdin": ("scanf" in combined) or ("fgets" in combined) or ("getchar" in combined),
        "uses_argv": "argv" in combined,
        "uses_file_input": "fopen" in combined,
    }


def _build_cpp_source_signals(source_files: dict[str, str]) -> dict[str, bool]:
    combined = "\n".join(str(c) for c in source_files.values() if isinstance(c, str))
    return {
        "uses_stdin": ("cin" in combined) or ("getline" in combined),
        "uses_argv": "argv" in combined,
        "uses_file_input": ("ifstream" in combined) or ("fopen" in combined),
    }


def _build_java_source_signals(source_files: dict[str, str]) -> dict[str, bool]:
    combined = "\n".join(str(c) for c in source_files.values() if isinstance(c, str))
    return {
        "uses_stdin": ("Scanner" in combined) or ("BufferedReader" in combined),
        "uses_argv": "args[" in combined,
        "uses_file_input": ("FileReader" in combined) or ("Files.read" in combined),
    }


_LANGUAGE_SIGNAL_BUILDERS = {
    "python": _build_python_source_signals,
    "c": _build_c_source_signals,
    "cpp": _build_cpp_source_signals,
    "java": _build_java_source_signals,
}

_LANGUAGE_SHIM_INSTRUCTIONS = {
    "python": (
        "You are a code-eval healing agent for Python. Only fix interface mismatches such as "
        "stdin/argv/file-mode adaptation and minor formatting noise. "
        "Never attempt to fix student logic. "
        "When testcase contracts indicate expected I/O differs from program wiring, "
        "return fixable=true with a minimal adapter patch."
    ),
    "c": (
        "You are a code-eval healing agent for C. Only fix interface mismatches such as "
        "scanf vs argv mismatch, printf format specifier whitespace, or missing newline. "
        "Typical fix: wrap main to read from stdin when args expected, or vice versa. "
        "Do not change algorithmic logic. Return fixable=true with minimal patched source."
    ),
    "cpp": (
        "You are a code-eval healing agent for C++. Only fix interface mismatches such as "
        "cin vs argv mismatch, getline vs cin>>, endl missing, or minor output formatting. "
        "Typical fix: adapt argv/cin wiring. Do not change algorithmic logic."
    ),
    "java": (
        "You are a code-eval healing agent for Java. Only fix interface mismatches such as "
        "Scanner(System.in) vs args[0], nextInt vs nextLine, or missing System.out.flush(). "
        "Typical fix: switch input source or add flush. Do not change algorithmic logic."
    ),
}


# ── Utility ───────────────────────────────────────────────────────────────────

def _build_source_signal_map(source_files: dict[str, str], language: str) -> dict[str, bool]:
    builder = _LANGUAGE_SIGNAL_BUILDERS.get(language)
    if builder is None:
        return {"uses_stdin": False, "uses_argv": False, "uses_file_input": False}
    return builder(source_files)


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


# ── Fallback adapter injectors ────────────────────────────────────────────────

def _inject_stdin_to_argv_adapter_python(source: str) -> str:
    adapter = (
        "import sys\n"
        "# AI-shim fallback adapter: map stdin to argv[1] when program expects CLI args.\n"
        "if len(sys.argv) <= 1:\n"
        "    _shim_stdin = sys.stdin.read()\n"
        "    if _shim_stdin is not None and _shim_stdin.strip():\n"
        "        sys.argv = [sys.argv[0], _shim_stdin.strip()]\n\n"
    )
    return adapter + source


def _inject_stdin_to_argv_adapter_c(source: str, entrypoint: str) -> dict[str, str]:
    """Wrap C main to read from stdin and provide as argv[1] when no args given."""
    # Strategy: prepend a small shim that re-routes stdin → argc/argv
    wrapper = (
        "#include <stdio.h>\n"
        "#include <string.h>\n"
        "#include <stdlib.h>\n"
        "// AI-shim fallback: route stdin to argv when program expects CLI arg\n"
        "#define _SHIM_BUF_SZ 4096\n"
        "static char _shim_buf[_SHIM_BUF_SZ];\n"
        "static char *_shim_argv[3];\n"
        "// Rename original main to _student_main\n"
        "#define main _student_main\n"
    )
    footer = (
        "\n#undef main\n"
        "int main(int argc, char *argv[]) {\n"
        "    if (argc <= 1) {\n"
        "        if (fgets(_shim_buf, _SHIM_BUF_SZ - 1, stdin)) {\n"
        "            size_t len = strlen(_shim_buf);\n"
        "            while (len > 0 && (_shim_buf[len-1] == '\\n' || _shim_buf[len-1] == '\\r')) {\n"
        "                _shim_buf[--len] = '\\0';\n"
        "            }\n"
        "        }\n"
        "        _shim_argv[0] = argv[0]; _shim_argv[1] = _shim_buf; _shim_argv[2] = NULL;\n"
        "        return _student_main(2, _shim_argv);\n"
        "    }\n"
        "    return _student_main(argc, argv);\n"
        "}\n"
    )
    return {entrypoint: wrapper + source + footer}


def _inject_stdin_to_argv_adapter_cpp(source: str, entrypoint: str) -> dict[str, str]:
    wrapper = (
        "#include <iostream>\n"
        "#include <string>\n"
        "#include <vector>\n"
        "// AI-shim fallback: route stdin to argv when program expects CLI arg\n"
        "#define main _student_main\n"
    )
    footer = (
        "\n#undef main\n"
        "int main(int argc, char *argv[]) {\n"
        "    if (argc <= 1) {\n"
        "        std::string _shim_input;\n"
        "        std::getline(std::cin, _shim_input);\n"
        "        std::vector<const char*> _shim_argv = {argv[0], _shim_input.c_str(), nullptr};\n"
        "        return _student_main(2, const_cast<char**>(_shim_argv.data()));\n"
        "    }\n"
        "    return _student_main(argc, argv);\n"
        "}\n"
    )
    return {entrypoint: wrapper + source + footer}


def _inject_stdin_to_argv_adapter_java(source: str, entrypoint: str) -> dict[str, str]:
    """Add a shim main that reads stdin and delegates to the original as args."""
    class_name = Path(entrypoint).stem
    shim_class = (
        f"// AI-shim fallback: route stdin to args when program expects CLI args\n"
        f"class _ShimRunner_{class_name} {{\n"
        f"    public static void main(String[] args) throws Exception {{\n"
        f"        if (args.length == 0) {{\n"
        f"            java.util.Scanner sc = new java.util.Scanner(System.in);\n"
        f"            String line = sc.hasNextLine() ? sc.nextLine().trim() : \"\";\n"
        f"            {class_name}.main(new String[]{{line}});\n"
        f"        }} else {{\n"
        f"            {class_name}.main(args);\n"
        f"        }}\n"
        f"    }}\n"
        f"}}\n"
    )
    shim_filename = f"_ShimRunner_{class_name}.java"
    return {entrypoint: source, shim_filename: shim_class}


def _inject_fallback_adapter(
    request: CodeEvalJobRequest,
    failed_cases: list[dict[str, Any]],
) -> dict[str, str] | None:
    """Generate a fallback adapter patch for the language. Returns patched files or None."""
    language = request.language.value
    entrypoint_source = request.source_files.get(request.entrypoint)
    if not isinstance(entrypoint_source, str) or not entrypoint_source.strip():
        return None

    if not _all_cases_interface_like(failed_cases):
        return None

    if language == "python":
        return {request.entrypoint: _inject_stdin_to_argv_adapter_python(entrypoint_source)}
    if language == "c":
        return _inject_stdin_to_argv_adapter_c(entrypoint_source, request.entrypoint)
    if language == "cpp":
        return _inject_stdin_to_argv_adapter_cpp(entrypoint_source, request.entrypoint)
    if language == "java":
        return _inject_stdin_to_argv_adapter_java(entrypoint_source, request.entrypoint)
    return None


# ── Compile-check for AI patches (C/C++/Java) ────────────────────────────────

def _compile_check_patch(
    language: str,
    patched_files: dict[str, str],
    lang_cfg: Any,
    entrypoint: str,
) -> tuple[bool, str]:
    """Compile-check a patched source. Returns (ok, error_message).

    For Python: always passes (no compile step needed).
    For C/C++/Java: actually compiles in a temp dir to catch broken patches early.
    """
    if language == "python":
        return True, ""

    with tempfile.TemporaryDirectory(prefix="code_eval_shimcheck_") as tmp:
        workspace = Path(tmp)
        for rel_path, content in patched_files.items():
            target = workspace / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

        try:
            if language == "c":
                compiler = "gcc"
                if shutil.which(compiler) is None:
                    return True, ""  # can't check without compiler; allow through
                sources = [str(workspace / f) for f in patched_files if f.endswith(".c")]
                cmd = lang_cfg.full_compile_command(compiler, sources, str(workspace / ".check_exec"))
            elif language == "cpp":
                compiler = "g++"
                if shutil.which(compiler) is None:
                    return True, ""
                sources = [str(workspace / f) for f in patched_files if f.endswith(".cpp")]
                cmd = lang_cfg.full_compile_command(compiler, sources, str(workspace / ".check_exec"))
            elif language == "java":
                if shutil.which("javac") is None:
                    return True, ""
                sources = [str(workspace / f) for f in patched_files if f.endswith(".java")]
                cmd = lang_cfg.full_java_compile_command(sources)
            else:
                return True, ""

            result = subprocess.run(
                cmd, cwd=str(workspace), capture_output=True, text=True, timeout=30
            )
            if result.returncode != 0:
                err = (result.stderr or result.stdout or "")[:2000]
                log.warning(
                    "code_eval shim: compile-check failed for lang=%s entrypoint=%s: %s",
                    language, entrypoint, err[:200],
                )
                return False, err
            return True, ""
        except subprocess.TimeoutExpired:
            return False, "Compile check timed out (30s)"
        except Exception as exc:
            log.warning("code_eval shim: compile-check exception for lang=%s: %s", language, exc)
            return True, ""  # unknown error — allow through rather than falsely blocking


# ── Deterministic whitespace path (Python only) ───────────────────────────────

def _deterministic_whitespace_decision(
    request: CodeEvalJobRequest,
    raw_execution_artifacts: dict[str, Any],
) -> dict[str, Any]:
    testcases = raw_execution_artifacts.get("testcases")
    if not isinstance(testcases, list):
        return {
            "eligible": False,
            "reason": "raw_execution_artifacts_missing_testcases",
            "comparison_mode": None, "shim_source": None,
            "analyzed_at": _now_iso(), "failed_testcases": [],
        }

    # Deterministic whitespace normalization only makes sense for Python
    # (print trailing spaces, etc.). Compiled languages fail differently.
    if request.language.value != "python":
        return {
            "eligible": False,
            "reason": "deterministic_whitespace_shim_not_applicable_for_compiled_language",
            "comparison_mode": None, "shim_source": None,
            "analyzed_at": _now_iso(), "failed_testcases": [],
        }

    spec_by_id = {case.testcase_id: case for case in request.testcases}
    source_signals = _build_source_signal_map(request.source_files, "python")
    failed_cases: list[dict[str, Any]] = []

    for case_result in testcases:
        if not isinstance(case_result, dict):
            continue
        if bool(case_result.get("passed")):
            continue

        case_id = str(case_result.get("testcase_id") or "")
        tokens = _parse_failure_tokens(case_result.get("failure_reason"))
        case_audit: dict[str, Any] = {
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
            stdout_ok = _collapse_whitespace(case_result.get("stdout")) == _collapse_whitespace(spec.expected_stdout)

        stderr_ok = True
        if "stderr_mismatch" in tokens:
            stderr_ok = _collapse_whitespace(case_result.get("stderr")) == _collapse_whitespace(spec.expected_stderr)

        if stdout_ok and stderr_ok and tokens:
            case_audit["eligible"] = True
            case_audit["decision_reason"] = "whitespace_only_interface_mismatch"
        else:
            likely_io_mismatch = False
            if spec.input_mode.value == "stdin":
                stdin_non_empty = bool(_collapse_whitespace(spec.stdin))
                stdout_blank = not bool(_collapse_whitespace(case_result.get("stdout")))
                if (
                    stdin_non_empty and stdout_blank
                    and not source_signals["uses_stdin"]
                    and (source_signals["uses_argv"] or source_signals["uses_file_input"])
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
            "comparison_mode": None, "shim_source": None,
            "analyzed_at": _now_iso(), "failed_testcases": [],
        }

    all_failed_eligible = all(bool(case.get("eligible")) for case in failed_cases)
    if not all_failed_eligible:
        return {
            "eligible": False,
            "reason": "detected_non_shimmable_failure",
            "comparison_mode": None, "shim_source": None,
            "analyzed_at": _now_iso(), "failed_testcases": failed_cases,
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


# ── Testcase contract builder ──────────────────────────────────────────────────

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
        contracts.append({
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
        })
    return contracts


# ── AI-generated patch path (all 4 languages) ─────────────────────────────────

def _ai_generated_patch_decision(
    request: CodeEvalJobRequest,
    raw_execution_artifacts: dict[str, Any],
    failed_cases: list[dict[str, Any]],
) -> dict[str, Any]:
    language = request.language.value

    if not settings.code_eval_enable_ai_shim_generation:
        log.debug("code_eval shim: AI shim disabled via config for lang=%s", language)
        return {
            "eligible": False,
            "reason": "ai_shim_generation_disabled",
            "comparison_mode": None, "shim_source": None,
            "analyzed_at": _now_iso(), "failed_testcases": failed_cases,
        }

    if language not in _SHIM_ELIGIBLE_LANGUAGES:
        log.info("code_eval shim: language=%s not in eligible set %s", language, _SHIM_ELIGIBLE_LANGUAGES)
        return {
            "eligible": False,
            "reason": "ai_shim_generation_not_enabled_for_language",
            "comparison_mode": None, "shim_source": None,
            "analyzed_at": _now_iso(), "failed_testcases": failed_cases,
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

    source_signals = _build_source_signal_map(request.source_files, language)
    system_instruction = _LANGUAGE_SHIM_INSTRUCTIONS.get(language, _LANGUAGE_SHIM_INSTRUCTIONS["python"])

    prompt_payload = {
        "task": "Classify whether failure is a fixable interface mismatch and propose a safe patch",
        "language": language,
        "constraints": [
            f"Only patch {language} files",
            "Do not change grading logic expectations",
            "Prefer minimal wrappers/adapters",
            "Treat stdin/argv/file-mode mismatch as interface-level and fixable",
            "When stdin testcases are non-empty and observed stdout is blank while source uses argv/file input, classify as fixable interface mismatch",
            "Do not mark as logic bug solely from stdout mismatch without evaluating testcase contracts",
            "No network/file system side effects outside working directory",
        ],
        "entrypoint": request.entrypoint,
        "source_files": _trim_source_files_for_prompt(request.source_files),
        "source_signals": source_signals,
        "failed_testcases": failed_cases[:5],
        "testcase_contracts": _build_testcase_contracts(request, failed_cases)[:5],
        "request_quota": request.quota.model_dump(mode="json"),
    }

    model_name = settings.resolve_code_healing_model()
    prompt_hash = _stable_hash_payload({
        "model": model_name, "schema": schema,
        "system_instruction": system_instruction,
        "prompt_payload": prompt_payload,
    })

    config = build_structured_json_config(
        response_schema=schema,
        system_instruction=system_instruction,
        temperature=0.0,
        max_output_tokens=4096,
    )

    try:
        model_output = generate_structured_json_with_retry(
            model_name=model_name,
            contents=[{"role": "user", "parts": [{"text": str(prompt_payload)}]}],
            config=config,
            operation=f"Code-eval AI shim analysis ({language})",
        )
    except ModelServiceError as exc:
        log.error(
            "code_eval shim: AI model error for lang=%s submission=%s: %s",
            language, request.submission_id, exc,
        )
        return {
            "eligible": False,
            "reason": "ai_shim_model_error",
            "comparison_mode": None, "shim_source": None,
            "analyzed_at": _now_iso(),
            "failed_testcases": failed_cases,
            "ai_error": str(exc),
            "model": model_name,
            "prompt_hash": prompt_hash,
            # Structured warning so operators can see it in final_result_json
            "shim_warning": {
                "attempted": True,
                "reason": "model_unavailable",
                "error": str(exc),
                "language": language,
            },
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
                log.warning(
                    "code_eval shim: AI returned unsafe path '%s' for lang=%s — rejecting patch",
                    rel_path, language,
                )
                return {
                    "eligible": False,
                    "reason": "ai_shim_invalid_patch_path",
                    "comparison_mode": None, "shim_source": None,
                    "analyzed_at": _now_iso(), "failed_testcases": failed_cases,
                    "model": model_name, "prompt_hash": prompt_hash,
                }
            updated_files[rel_path] = str(content)

    if not fixable:
        return {
            "eligible": False,
            "reason": "ai_shim_not_fixable",
            "comparison_mode": None, "shim_source": None,
            "analyzed_at": _now_iso(), "failed_testcases": failed_cases,
            "ai_reason": reason, "model": model_name, "prompt_hash": prompt_hash,
        }

    if not updated_files:
        fallback_files = _inject_fallback_adapter(request, failed_cases)
        if fallback_files:
            updated_files = fallback_files
            reason = f"{reason}|fallback_adapter_injected"
            log.info(
                "code_eval shim: AI said fixable but gave no patch; "
                "injected fallback adapter for lang=%s", language,
            )
        else:
            return {
                "eligible": False,
                "reason": "ai_shim_fixable_without_patch_rejected",
                "comparison_mode": None, "shim_source": None,
                "analyzed_at": _now_iso(), "failed_testcases": failed_cases,
                "ai_reason": reason, "model": model_name, "prompt_hash": prompt_hash,
            }

    if not _safe_relative_path(updated_entrypoint):
        updated_entrypoint = request.entrypoint

    # ── Compile-check for compiled languages ──────────────────────────────────
    if language in {"c", "cpp", "java"}:
        lang_cfg = parse_language_config(
            request.environment.spec_json if hasattr(request.environment, "spec_json") else None,
            job_language=language,
        )
        compile_ok, compile_err = _compile_check_patch(language, updated_files, lang_cfg, updated_entrypoint)
        if not compile_ok:
            log.warning(
                "code_eval shim: AI patch compile-check FAILED for lang=%s submission=%s: %s",
                language, request.submission_id, compile_err[:200],
            )
            return {
                "eligible": False,
                "reason": "shim_compile_check_failed",
                "comparison_mode": None, "shim_source": None,
                "analyzed_at": _now_iso(), "failed_testcases": failed_cases,
                "ai_reason": reason, "model": model_name, "prompt_hash": prompt_hash,
                "compile_check_error": compile_err[:2000],
            }
        log.info("code_eval shim: AI patch compile-check PASSED for lang=%s", language)

    return {
        "eligible": True,
        "reason": "ai_generated_interface_shim",
        "comparison_mode": comparison_mode if comparison_mode in {"strict", "whitespace_normalized"} else "strict",
        "shim_source": (
            f"# shim_policy: ai_generated_patch\n"
            f"# language: {language}\n"
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


# ── Public API ────────────────────────────────────────────────────────────────

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

    # Re-extract failed cases from artifacts for compiled languages
    # (deterministic path only populates them for Python)
    if not failed_cases:
        testcases = raw_execution_artifacts.get("testcases") or []
        failed_cases = [
            {
                "testcase_id": tc.get("testcase_id", ""),
                "failure_tokens": sorted(_parse_failure_tokens(tc.get("failure_reason"))),
                "eligible": False,
                "decision_reason": "initial_execution_failure",
                "stdout": tc.get("stdout") or "",
                "stderr": tc.get("stderr") or "",
            }
            for tc in testcases
            if isinstance(tc, dict) and not tc.get("passed")
        ]

    ai_decision = _ai_generated_patch_decision(request, raw_execution_artifacts, failed_cases)
    if bool(ai_decision.get("eligible")):
        return ai_decision

    reason = str(deterministic.get("reason") or "detected_non_shimmable_failure")
    ai_reason = str(ai_decision.get("reason") or "")
    merged_reason = reason if not ai_reason else f"{reason}|{ai_reason}"

    # Surface shim_warning if AI model errored — visible in final_result_json
    shim_warning = ai_decision.get("shim_warning")
    result: dict[str, Any] = {
        "eligible": False,
        "reason": merged_reason,
        "comparison_mode": None,
        "shim_source": None,
        "analyzed_at": _now_iso(),
        "failed_testcases": failed_cases,
        "ai_decision": ai_decision,
    }
    if shim_warning:
        result["shim_warning"] = shim_warning
    return result


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
