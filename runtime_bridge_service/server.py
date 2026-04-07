"""Reference runtime bridge service for microVM adapter contract validation.

This service supports two executor modes behind the same `/execute` contract:
- local_reference: executes Python testcases in isolated temporary directories.
- microvm_transport: forwards execution to an external isolated runtime endpoint.
"""

from __future__ import annotations

import json
import os
import ssl
import subprocess
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field


class ExecutionQuota(BaseModel):
    timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    memory_mb: int = Field(default=256, ge=64, le=4096)
    max_output_kb: int = Field(default=256, ge=16, le=4096)
    network_enabled: bool = False


class TestCaseSpec(BaseModel):
    testcase_id: str
    weight: float = Field(default=1.0, gt=0)
    input_mode: str = "stdin"
    stdin: str | None = None
    argv: list[str] = Field(default_factory=list)
    files: dict[str, str] = Field(default_factory=dict)
    expected_stdout: str | None = None
    expected_stderr: str | None = None
    expected_exit_code: int = 0


class RuntimeEnvironmentSpec(BaseModel):
    mode: str = "manifest"
    runtime: str = "python-3.11"
    freeze_key: str | None = None
    image_reference: str | None = None


class RuntimeBridgeJobRequest(BaseModel):
    assignment_id: str
    submission_id: str
    language: str
    entrypoint: str
    source_files: dict[str, str]
    testcases: list[TestCaseSpec]
    environment: RuntimeEnvironmentSpec
    quota: ExecutionQuota = Field(default_factory=ExecutionQuota)


class RuntimeBridgeExecuteRequest(BaseModel):
    stage: str = "EXECUTING_RAW"
    comparison_mode: str = "strict"
    shim_used: bool = False
    shim_source: str | None = None
    request: RuntimeBridgeJobRequest


class RuntimeBridgeExecuteResponse(BaseModel):
    passed: bool
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    score: float = 0.0
    artifacts: dict[str, Any] = Field(default_factory=dict)


class RuntimeBridgeStatusOut(BaseModel):
    executor_mode: str
    microvm_transport: dict[str, Any]


app = FastAPI(title="AMGS Runtime Bridge", version="0.1.0")


def _parse_bool(raw: str | None, default: bool = False) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _executor_mode() -> str:
    return os.getenv("RUNTIME_BRIDGE_EXECUTOR_MODE", "local_reference").strip().lower()


def _microvm_execute_url() -> str:
    return os.getenv("RUNTIME_BRIDGE_MICROVM_EXECUTE_URL", "").strip()


def _microvm_api_key() -> str:
    return os.getenv("RUNTIME_BRIDGE_MICROVM_API_KEY", "").strip()


def _microvm_verify_tls() -> bool:
    return _parse_bool(os.getenv("RUNTIME_BRIDGE_MICROVM_VERIFY_TLS"), default=True)


def _microvm_timeout_seconds() -> float:
    raw = os.getenv("RUNTIME_BRIDGE_MICROVM_TIMEOUT_SECONDS", "30").strip()
    try:
        value = float(raw)
    except ValueError:
        value = 30.0
    return max(1.0, min(value, 120.0))


def _validate_executor_mode(mode: str) -> None:
    if mode in {"local_reference", "microvm_transport"}:
        return
    raise HTTPException(
        status_code=500,
        detail=(
            "Invalid runtime bridge executor mode. "
            "Supported: local_reference, microvm_transport"
        ),
    )


def _normalize_text(value: str) -> str:
    return value.replace("\r\n", "\n").rstrip("\n")


def _collapse_whitespace(value: str) -> str:
    return " ".join(value.split())


def _outputs_equivalent(actual: str, expected: str, comparison_mode: str) -> bool:
    if comparison_mode == "whitespace_normalized":
        return _collapse_whitespace(actual) == _collapse_whitespace(expected)
    return _normalize_text(actual) == _normalize_text(expected)


def _truncate_output(stdout: str, stderr: str, max_output_kb: int) -> tuple[str, str, bool]:
    max_bytes = int(max_output_kb) * 1024
    out_bytes = stdout.encode("utf-8", errors="replace")
    err_bytes = stderr.encode("utf-8", errors="replace")

    if len(out_bytes) + len(err_bytes) <= max_bytes:
        return stdout, stderr, False

    if len(out_bytes) >= max_bytes:
        return out_bytes[:max_bytes].decode("utf-8", errors="ignore"), "", True

    remaining = max_bytes - len(out_bytes)
    return stdout, err_bytes[:remaining].decode("utf-8", errors="ignore"), True


def _safe_write_files(root: Path, files: dict[str, str]) -> None:
    root = root.resolve()
    for relative_path, content in files.items():
        rel = Path(relative_path)
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError(f"Unsafe path in files payload: {relative_path}")

        target = (root / rel).resolve()
        if root not in target.parents and target != root:
            raise ValueError(f"Path escapes sandbox root: {relative_path}")

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def _resolve_local_reference_commands(
    language: str,
    entrypoint: str,
    argv: list[str],
    case_dir: Path,
) -> tuple[list[str] | None, list[str]]:
    if language == "python":
        return None, [sys.executable, entrypoint, *argv]
    if language == "c":
        if shutil.which("gcc") is None:
            raise RuntimeError("gcc is required for C execution")
        binary = case_dir / ".codeeval_exec"
        return ["gcc", entrypoint, "-O2", "-std=c11", "-o", str(binary)], [str(binary), *argv]
    if language == "cpp":
        if shutil.which("g++") is None:
            raise RuntimeError("g++ is required for C++ execution")
        binary = case_dir / ".codeeval_exec"
        return ["g++", entrypoint, "-O2", "-std=c++17", "-o", str(binary)], [str(binary), *argv]
    if language == "java":
        if shutil.which("javac") is None or shutil.which("java") is None:
            raise RuntimeError("javac and java are required for Java execution")
        class_name = Path(entrypoint).stem
        return ["javac", entrypoint], ["java", "-cp", str(case_dir), class_name, *argv]
    raise RuntimeError(f"Unsupported language: {language}")


def _authorize(authorization: str | None) -> None:
    expected_key = os.getenv("RUNTIME_BRIDGE_API_KEY", "").strip()
    if not expected_key:
        return

    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    prefix = "Bearer "
    if not authorization.startswith(prefix):
        raise HTTPException(status_code=401, detail="Invalid Authorization scheme")

    presented_key = authorization[len(prefix):].strip()
    if presented_key != expected_key:
        raise HTTPException(status_code=401, detail="Invalid runtime bridge API key")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "runtime-bridge"}


@app.get("/runtime/status", response_model=RuntimeBridgeStatusOut)
def runtime_status() -> RuntimeBridgeStatusOut:
    mode = _executor_mode()
    _validate_executor_mode(mode)
    return RuntimeBridgeStatusOut(
        executor_mode=mode,
        microvm_transport={
            "execute_url_configured": bool(_microvm_execute_url()),
            "api_key_configured": bool(_microvm_api_key()),
            "timeout_seconds": _microvm_timeout_seconds(),
            "verify_tls": _microvm_verify_tls(),
        },
    )


def _execute_local_reference(body: RuntimeBridgeExecuteRequest) -> RuntimeBridgeExecuteResponse:
    request = body.request
    language = request.language.lower().strip()

    if not request.testcases:
        return RuntimeBridgeExecuteResponse(
            passed=False,
            exit_code=2,
            stderr="No testcases were configured for this bridge execution.",
            score=0.0,
            artifacts={
                "engine": "runtime_bridge_reference",
                "executor_mode": "local_reference",
                "testcases": [],
            },
        )

    testcase_results: list[dict[str, Any]] = []
    total_score = 0.0

    try:
        with tempfile.TemporaryDirectory(prefix="runtime_bridge_") as tmp:
            root = Path(tmp)
            for idx, testcase in enumerate(request.testcases):
                case_dir = root / f"case_{idx + 1}"
                case_dir.mkdir(parents=True, exist_ok=True)
                _safe_write_files(case_dir, request.source_files)
                _safe_write_files(case_dir, testcase.files)

                entrypoint = (case_dir / request.entrypoint).resolve()
                if not entrypoint.exists():
                    testcase_results.append(
                        {
                            "testcase_id": testcase.testcase_id,
                            "passed": False,
                            "weight": float(testcase.weight),
                            "awarded_score": 0.0,
                            "exit_code": -2,
                            "stdout": "",
                            "stderr": f"Entrypoint not found: {request.entrypoint}",
                            "failure_reason": "entrypoint_missing",
                        }
                    )
                    continue

                cmd = [sys.executable, request.entrypoint, *testcase.argv]
                stdin_value = testcase.stdin if testcase.input_mode == "stdin" else None

                compile_cmd, cmd = _resolve_local_reference_commands(
                    language,
                    request.entrypoint,
                    [str(arg) for arg in testcase.argv],
                    case_dir,
                )

                if compile_cmd is not None:
                    try:
                        compile_result = subprocess.run(
                            compile_cmd,
                            cwd=str(case_dir),
                            text=True,
                            capture_output=True,
                            timeout=max(2.0, min(request.quota.timeout_seconds, 20.0)),
                        )
                        if compile_result.returncode != 0:
                            testcase_results.append(
                                {
                                    "testcase_id": testcase.testcase_id,
                                    "passed": False,
                                    "weight": float(testcase.weight),
                                    "awarded_score": 0.0,
                                    "exit_code": compile_result.returncode,
                                    "stdout": compile_result.stdout or "",
                                    "stderr": compile_result.stderr or "",
                                    "failure_reason": "compile_error",
                                }
                            )
                            continue
                    except subprocess.TimeoutExpired:
                        testcase_results.append(
                            {
                                "testcase_id": testcase.testcase_id,
                                "passed": False,
                                "weight": float(testcase.weight),
                                "awarded_score": 0.0,
                                "exit_code": -1,
                                "stdout": "",
                                "stderr": "Compilation timed out",
                                "failure_reason": "compile_timeout",
                            }
                        )
                        continue

                timeout_hit = False
                try:
                    completed = subprocess.run(
                        cmd,
                        cwd=str(case_dir),
                        input=stdin_value,
                        text=True,
                        capture_output=True,
                        timeout=request.quota.timeout_seconds,
                    )
                    exit_code = completed.returncode
                    stdout = completed.stdout or ""
                    stderr = completed.stderr or ""
                except subprocess.TimeoutExpired as exc:
                    timeout_hit = True
                    exit_code = -1
                    stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
                    stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
                    stderr = (stderr + "\n" if stderr else "") + (
                        f"Execution timed out after {request.quota.timeout_seconds:.2f}s"
                    )

                stdout, stderr, output_truncated = _truncate_output(
                    stdout,
                    stderr,
                    request.quota.max_output_kb,
                )

                exit_ok = exit_code == testcase.expected_exit_code
                stdout_ok = (
                    True
                    if testcase.expected_stdout is None
                    else _outputs_equivalent(stdout, testcase.expected_stdout, body.comparison_mode)
                )
                stderr_ok = (
                    True
                    if testcase.expected_stderr is None
                    else _outputs_equivalent(stderr, testcase.expected_stderr, body.comparison_mode)
                )

                passed = bool(exit_ok and stdout_ok and stderr_ok)
                reasons: list[str] = []
                if timeout_hit:
                    reasons.append("timeout")
                if not exit_ok:
                    reasons.append(f"exit_code_expected_{testcase.expected_exit_code}_got_{exit_code}")
                if not stdout_ok:
                    reasons.append("stdout_mismatch")
                if not stderr_ok:
                    reasons.append("stderr_mismatch")
                if output_truncated:
                    reasons.append("output_truncated")

                awarded_score = float(testcase.weight) if passed else 0.0
                total_score += awarded_score

                testcase_results.append(
                    {
                        "testcase_id": testcase.testcase_id,
                        "passed": passed,
                        "weight": float(testcase.weight),
                        "awarded_score": awarded_score,
                        "exit_code": exit_code,
                        "stdout": stdout,
                        "stderr": stderr,
                        "failure_reason": "|".join(reasons) if reasons else None,
                    }
                )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Bridge execution failed: {exc}") from exc

    all_passed = all(bool(item.get("passed")) for item in testcase_results)
    passed_count = sum(1 for item in testcase_results if bool(item.get("passed")))
    failed = [item for item in testcase_results if not bool(item.get("passed"))]

    summary_stderr = ""
    if failed:
        first_fail = failed[0]
        summary_stderr = (
            "Some testcases failed. "
            f"First failing testcase={first_fail.get('testcase_id')} "
            f"reason={first_fail.get('failure_reason') or 'unknown'}"
        )

    return RuntimeBridgeExecuteResponse(
        passed=all_passed,
        exit_code=0 if all_passed else 1,
        stdout=f"Bridge passed {passed_count}/{len(testcase_results)} testcases.",
        stderr=summary_stderr,
        score=round(total_score, 6),
        artifacts={
            "engine": "runtime_bridge_reference",
            "executor_mode": "local_reference",
            "language": language,
            "comparison_mode": body.comparison_mode,
            "shim_used": body.shim_used,
            "runtime": request.environment.runtime,
            "testcase_count": len(testcase_results),
            "testcases": testcase_results,
        },
    )


def _execute_microvm_transport(body: RuntimeBridgeExecuteRequest) -> RuntimeBridgeExecuteResponse:
    execute_url = _microvm_execute_url()
    if not execute_url:
        raise HTTPException(
            status_code=503,
            detail=(
                "MicroVM transport mode requires RUNTIME_BRIDGE_MICROVM_EXECUTE_URL"
            ),
        )

    headers = {"Content-Type": "application/json"}
    api_key = _microvm_api_key()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = json.dumps(body.model_dump(mode="json")).encode("utf-8")
    req = urlrequest.Request(execute_url, data=payload, headers=headers, method="POST")

    context: ssl.SSLContext | None = None
    if not _microvm_verify_tls():
        context = ssl._create_unverified_context()

    try:
        with urlrequest.urlopen(  # nosec: B310 - controlled URL from operator config
            req,
            timeout=_microvm_timeout_seconds(),
            context=context,
        ) as response:
            response_text = response.read().decode("utf-8", errors="replace")
    except urlerror.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        raise HTTPException(
            status_code=502,
            detail=(
                "MicroVM transport upstream returned HTTP error: "
                f"status={exc.code} body={body_text[:1024]}"
            ),
        ) from exc
    except urlerror.URLError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"MicroVM transport upstream unreachable: {exc.reason}",
        ) from exc
    except TimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail=(
                "MicroVM transport upstream timed out after "
                f"{_microvm_timeout_seconds():.2f}s"
            ),
        ) from exc

    try:
        parsed = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=502,
            detail="MicroVM transport upstream returned non-JSON response",
        ) from exc

    try:
        result = RuntimeBridgeExecuteResponse.model_validate(parsed)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"MicroVM transport upstream response validation failed: {exc}",
        ) from exc

    merged_artifacts = dict(result.artifacts or {})
    merged_artifacts.setdefault("engine", "runtime_bridge_microvm_transport")
    merged_artifacts["executor_mode"] = "microvm_transport"
    merged_artifacts["downstream_url"] = execute_url
    result.artifacts = merged_artifacts
    return result


@app.post("/execute", response_model=RuntimeBridgeExecuteResponse)
def execute(
    body: RuntimeBridgeExecuteRequest,
    authorization: str | None = Header(default=None),
) -> RuntimeBridgeExecuteResponse:
    _authorize(authorization)

    mode = _executor_mode()
    _validate_executor_mode(mode)
    if mode == "microvm_transport":
        return _execute_microvm_transport(body)
    return _execute_local_reference(body)
