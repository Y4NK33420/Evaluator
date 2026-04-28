"""Static analysis gate for code-eval submissions.

The goal is to reject obviously unsafe submissions before runtime execution.
This is a conservative allowlist/denylist layer, not a full sandbox substitute.
"""

from __future__ import annotations

import ast
import re
from typing import Any

from app.services.code_eval.contracts import CodeEvalJobRequest

_PY_FORBIDDEN_IMPORTS = {
    "subprocess",
    "socket",
    "multiprocessing",
    "ctypes",
}

_PY_FORBIDDEN_CALLS = {
    "os.system",
    "os.popen",
    "subprocess.Popen",
    "subprocess.run",
    "subprocess.call",
    "subprocess.check_output",
    "subprocess.check_call",
    "eval",
    "exec",
    "compile",
    "__import__",
}

_C_LIKE_FORBIDDEN_PATTERNS: list[tuple[str, str]] = [
    (r"\bsystem\s*\(", "system_call_forbidden"),
    (r"\bpopen\s*\(", "popen_forbidden"),
    (r"\bfork\s*\(", "fork_forbidden"),
    (r"\bexec[a-z]*\s*\(", "exec_forbidden"),
    (r"\bsocket\s*\(", "socket_forbidden"),
]

_JAVA_FORBIDDEN_PATTERNS: list[tuple[str, str]] = [
    (r"Runtime\s*\.\s*getRuntime\s*\(\s*\)\s*\.\s*exec\s*\(", "runtime_exec_forbidden"),
    (r"new\s+ProcessBuilder\s*\(", "process_builder_forbidden"),
    (r"java\.net\.", "java_network_forbidden"),
]


def _violation(file_path: str, line: int | None, rule: str, message: str) -> dict[str, Any]:
    return {
        "file": file_path,
        "line": line,
        "rule": rule,
        "message": message,
    }


def _qualified_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _qualified_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _python_file_analysis(file_path: str, source: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        findings.append(
            _violation(
                file_path,
                exc.lineno,
                "python_syntax_error",
                f"Python syntax error during static analysis: {exc.msg}",
            )
        )
        return findings

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in _PY_FORBIDDEN_IMPORTS:
                    findings.append(
                        _violation(
                            file_path,
                            getattr(node, "lineno", None),
                            "python_forbidden_import",
                            f"Forbidden import '{root}'",
                        )
                    )

        if isinstance(node, ast.ImportFrom):
            module_root = (node.module or "").split(".")[0]
            if module_root in _PY_FORBIDDEN_IMPORTS:
                findings.append(
                    _violation(
                        file_path,
                        getattr(node, "lineno", None),
                        "python_forbidden_import",
                        f"Forbidden import-from '{module_root}'",
                    )
                )

        if isinstance(node, ast.Call):
            fn_name = _qualified_name(node.func)
            if fn_name in _PY_FORBIDDEN_CALLS:
                findings.append(
                    _violation(
                        file_path,
                        getattr(node, "lineno", None),
                        "python_forbidden_call",
                        f"Forbidden call '{fn_name}'",
                    )
                )

            if fn_name == "open" and node.args:
                mode = "r"
                if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                    mode = str(node.args[1].value)
                for kw in node.keywords:
                    if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                        mode = str(kw.value.value)

                writes = any(flag in mode for flag in ("w", "a", "x", "+"))
                if writes and isinstance(node.args[0], ast.Constant):
                    target = str(node.args[0].value)
                    if target.startswith("/") and not target.startswith("/tmp/"):
                        findings.append(
                            _violation(
                                file_path,
                                getattr(node, "lineno", None),
                                "python_file_write_outside_tmp",
                                "File writes are only allowed under /tmp in strict mode",
                            )
                        )

    return findings


def _regex_scan(file_path: str, source: str, rules: list[tuple[str, str]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for pattern, rule in rules:
        for match in re.finditer(pattern, source):
            line = source.count("\n", 0, match.start()) + 1
            findings.append(
                _violation(
                    file_path,
                    line,
                    rule,
                    f"Forbidden pattern detected: {rule}",
                )
            )
    return findings


def run_static_analysis_gate(request: CodeEvalJobRequest) -> dict[str, Any]:
    language = request.language.value
    findings: list[dict[str, Any]] = []

    for file_path, source in request.source_files.items():
        if not isinstance(source, str):
            findings.append(
                _violation(file_path, None, "invalid_source_type", "Source file content must be text")
            )
            continue

        if language == "python":
            findings.extend(_python_file_analysis(file_path, source))
        elif language in {"c", "cpp"}:
            findings.extend(_regex_scan(file_path, source, _C_LIKE_FORBIDDEN_PATTERNS))
        elif language == "java":
            findings.extend(_regex_scan(file_path, source, _JAVA_FORBIDDEN_PATTERNS))

    return {
        "blocked": bool(findings),
        "language": language,
        "violations": findings,
    }
