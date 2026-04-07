"""Execution adapter boundary for code-evaluator jobs.

This phase includes an opt-in local Python executor so the lifecycle can be
validated end-to-end before microVM orchestration is wired in.
"""

from __future__ import annotations

import subprocess
import shlex
import sys
import tempfile
import io
import tarfile
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.services.code_eval.contracts import AttemptResult, CodeEvalJobRequest
from app.services.code_eval.microvm_executor import execute_microvm_backend

settings = get_settings()


def _normalize_text(value: str) -> str:
    return value.replace("\r\n", "\n").rstrip("\n")


def _collapse_whitespace(value: str) -> str:
    return " ".join(value.split())


def _outputs_equivalent(actual: str, expected: str, comparison_mode: str) -> bool:
    if comparison_mode == "whitespace_normalized":
        return _collapse_whitespace(actual) == _collapse_whitespace(expected)
    return _normalize_text(actual) == _normalize_text(expected)


def _safe_write_files(root: Path, files: dict[str, str]) -> None:
    root = root.resolve()
    for relative_path, content in files.items():
        rel = Path(relative_path)
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError(f"Unsafe path in source/files payload: {relative_path}")

        target = (root / rel).resolve()
        if root not in target.parents and target != root:
            raise ValueError(f"Path escapes sandbox root: {relative_path}")

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


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


def _run_single_testcase(
    request: CodeEvalJobRequest,
    case_dir: Path,
    case_index: int,
    comparison_mode: str,
) -> dict[str, Any]:
    testcase = request.testcases[case_index]
    _safe_write_files(case_dir, request.source_files)
    _safe_write_files(case_dir, testcase.files)

    entrypoint = (case_dir / request.entrypoint).resolve()
    if not entrypoint.exists():
        return {
            "testcase_id": testcase.testcase_id,
            "passed": False,
            "weight": float(testcase.weight),
            "awarded_score": 0.0,
            "exit_code": -2,
            "stdout": "",
            "stderr": f"Entrypoint not found in source_files: {request.entrypoint}",
            "failure_reason": "entrypoint_missing",
            "output_truncated": False,
        }

    cmd = [sys.executable, request.entrypoint]
    if testcase.argv:
        cmd.extend(testcase.argv)

    stdin_value = testcase.stdin if testcase.input_mode.value == "stdin" else None

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
        timeout_hit = False
    except subprocess.TimeoutExpired as exc:
        exit_code = -1
        stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
        timeout_hit = True
        stderr = (stderr + "\n" if stderr else "") + (
            f"Execution timed out after {request.quota.timeout_seconds:.2f}s"
        )

    stdout, stderr, output_truncated = _truncate_output(
        stdout,
        stderr,
        request.quota.max_output_kb,
    )

    expected_exit = testcase.expected_exit_code
    exit_ok = exit_code == expected_exit
    stdout_ok = (
        True
        if testcase.expected_stdout is None
        else _outputs_equivalent(stdout, testcase.expected_stdout, comparison_mode)
    )
    stderr_ok = (
        True
        if testcase.expected_stderr is None
        else _outputs_equivalent(stderr, testcase.expected_stderr, comparison_mode)
    )

    passed = bool(exit_ok and stdout_ok and stderr_ok)
    reasons: list[str] = []
    if timeout_hit:
        reasons.append("timeout")
    if not exit_ok:
        reasons.append(f"exit_code_expected_{expected_exit}_got_{exit_code}")
    if not stdout_ok:
        reasons.append("stdout_mismatch")
    if not stderr_ok:
        reasons.append("stderr_mismatch")
    if output_truncated:
        reasons.append("output_truncated")

    awarded_score = float(testcase.weight) if passed else 0.0

    return {
        "testcase_id": testcase.testcase_id,
        "passed": passed,
        "weight": float(testcase.weight),
        "awarded_score": awarded_score,
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "failure_reason": "|".join(reasons) if reasons else None,
        "output_truncated": output_truncated,
    }


def _resolve_docker_image(request: CodeEvalJobRequest) -> str:
    if request.environment.image_reference and request.environment.image_reference.strip():
        return request.environment.image_reference.strip()
    if request.environment.freeze_key and request.environment.freeze_key.strip():
        return request.environment.freeze_key.strip()
    return settings.code_eval_docker_default_image.strip()


def _validate_relative_file_map(files: dict[str, str]) -> None:
    for relative_path in files.keys():
        rel = Path(relative_path)
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError(f"Unsafe path in source/files payload: {relative_path}")


def _build_workspace_archive(files: dict[str, str]) -> bytes:
    _validate_relative_file_map(files)

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        added_dirs: set[str] = set()
        for rel_path, content in files.items():
            normalized = str(Path(rel_path).as_posix())
            tar_name = f"workspace/{normalized}"

            parent = Path(tar_name).parent
            parent_parts = []
            for part in parent.parts:
                parent_parts.append(part)
                dir_name = "/".join(parent_parts)
                if dir_name and dir_name not in added_dirs:
                    dir_info = tarfile.TarInfo(name=dir_name)
                    dir_info.type = tarfile.DIRTYPE
                    dir_info.mode = 0o755
                    archive.addfile(dir_info)
                    added_dirs.add(dir_name)

            payload = content.encode("utf-8")
            file_info = tarfile.TarInfo(name=tar_name)
            file_info.size = len(payload)
            file_info.mode = 0o644
            archive.addfile(file_info, io.BytesIO(payload))

    return buffer.getvalue()


def _run_single_testcase_docker(
    request: CodeEvalJobRequest,
    case_index: int,
    docker_image: str,
    docker_client: Any,
    comparison_mode: str,
) -> dict[str, Any]:
    testcase = request.testcases[case_index]

    staged_files: dict[str, str] = dict(request.source_files)
    staged_files.update(testcase.files)

    if request.entrypoint not in staged_files:
        return {
            "testcase_id": testcase.testcase_id,
            "passed": False,
            "weight": float(testcase.weight),
            "awarded_score": 0.0,
            "exit_code": -2,
            "stdout": "",
            "stderr": f"Entrypoint not found in source_files: {request.entrypoint}",
            "failure_reason": "entrypoint_missing",
            "output_truncated": False,
        }

    command: list[str] | str
    if testcase.input_mode.value == "stdin":
        staged_files[".stdin.txt"] = testcase.stdin or ""
        quoted_args = " ".join(shlex.quote(arg) for arg in testcase.argv)
        shell_cmd = f"python {shlex.quote(request.entrypoint)}"
        if quoted_args:
            shell_cmd = f"{shell_cmd} {quoted_args}"
        shell_cmd = f"{shell_cmd} < /workspace/.stdin.txt"
        command = ["/bin/sh", "-lc", shell_cmd]
    else:
        command = ["python", request.entrypoint, *testcase.argv]

    timeout_hit = False
    timeout_message = ""
    stdout = ""
    stderr = ""
    exit_code = -1
    container = None

    try:
        container = docker_client.containers.create(
            image=docker_image,
            command=command,
            working_dir="/workspace",
            network_disabled=(
                settings.code_eval_docker_force_no_network
                or not request.quota.network_enabled
            ),
            mem_limit=f"{int(request.quota.memory_mb)}m",
            tty=False,
            stdin_open=False,
        )
        archive_bytes = _build_workspace_archive(staged_files)
        container.put_archive("/", archive_bytes)
        container.start()
        wait_result = container.wait(timeout=request.quota.timeout_seconds)
        exit_code = int(wait_result.get("StatusCode", 1))
    except Exception as exc:
        timeout_hit = True
        timeout_message = (
            f"Execution timed out/failed after {request.quota.timeout_seconds:.2f}s: {exc}"
        )
        if container is not None:
            try:
                container.kill()
            except Exception:
                pass
    finally:
        if container is not None:
            try:
                stdout_bytes = container.logs(stdout=True, stderr=False) or b""
                stderr_bytes = container.logs(stdout=False, stderr=True) or b""
                stdout = stdout_bytes.decode("utf-8", errors="replace")
                stderr = stderr_bytes.decode("utf-8", errors="replace")
            except Exception:
                pass
            try:
                container.remove(force=True)
            except Exception:
                pass

    if timeout_hit and timeout_message:
        stderr = (stderr + "\n" if stderr else "") + timeout_message

    stdout, stderr, output_truncated = _truncate_output(
        stdout,
        stderr,
        request.quota.max_output_kb,
    )

    expected_exit = testcase.expected_exit_code
    exit_ok = exit_code == expected_exit
    stdout_ok = (
        True
        if testcase.expected_stdout is None
        else _outputs_equivalent(stdout, testcase.expected_stdout, comparison_mode)
    )
    stderr_ok = (
        True
        if testcase.expected_stderr is None
        else _outputs_equivalent(stderr, testcase.expected_stderr, comparison_mode)
    )

    passed = bool(exit_ok and stdout_ok and stderr_ok)
    reasons: list[str] = []
    if timeout_hit:
        reasons.append("timeout")
    if not exit_ok:
        reasons.append(f"exit_code_expected_{expected_exit}_got_{exit_code}")
    if not stdout_ok:
        reasons.append("stdout_mismatch")
    if not stderr_ok:
        reasons.append("stderr_mismatch")
    if output_truncated:
        reasons.append("output_truncated")

    awarded_score = float(testcase.weight) if passed else 0.0

    return {
        "testcase_id": testcase.testcase_id,
        "passed": passed,
        "weight": float(testcase.weight),
        "awarded_score": awarded_score,
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "failure_reason": "|".join(reasons) if reasons else None,
        "output_truncated": output_truncated,
    }


def _execute_local_backend(
    request: CodeEvalJobRequest,
    *,
    stage: str,
    comparison_mode: str,
    shim_used: bool,
    shim_source: str | None,
) -> tuple[AttemptResult, dict[str, Any]]:
    if not settings.code_eval_enable_local_execution:
        return AttemptResult(
            stage=stage,
            passed=False,
            exit_code=3,
            stderr=(
                "Local execution backend is disabled. "
                "Set CODE_EVAL_ENABLE_LOCAL_EXECUTION=true for controlled local runs."
            ),
            score=0.0,
            shim_used=shim_used,
            shim_source=shim_source,
        ), {
            "executor": "local_python_subprocess",
            "enabled": False,
            "comparison_mode": comparison_mode,
            "testcases": [],
        }

    if request.language.value != "python":
        return AttemptResult(
            stage=stage,
            passed=False,
            exit_code=4,
            stderr=(
                f"Language '{request.language.value}' is not yet supported by "
                "the local execution backend."
            ),
            score=0.0,
            shim_used=shim_used,
            shim_source=shim_source,
        ), {
            "executor": "local_python_subprocess",
            "enabled": True,
            "comparison_mode": comparison_mode,
            "testcases": [],
        }

    testcase_results: list[dict[str, Any]] = []
    total_score = 0.0
    max_score = float(sum(float(test.weight) for test in request.testcases))

    try:
        with tempfile.TemporaryDirectory(prefix="code_eval_local_") as tmp:
            tmp_root = Path(tmp)
            for idx in range(len(request.testcases)):
                case_dir = tmp_root / f"case_{idx + 1}"
                case_dir.mkdir(parents=True, exist_ok=True)
                case_result = _run_single_testcase(request, case_dir, idx, comparison_mode)
                testcase_results.append(case_result)
                total_score += float(case_result["awarded_score"])
    except Exception as exc:
        return AttemptResult(
            stage=stage,
            passed=False,
            exit_code=5,
            stderr=f"Local execution backend crashed: {exc}",
            score=0.0,
            shim_used=shim_used,
            shim_source=shim_source,
        ), {
            "executor": "local_python_subprocess",
            "enabled": True,
            "comparison_mode": comparison_mode,
            "testcases": testcase_results,
        }

    all_passed = all(bool(item.get("passed")) for item in testcase_results)
    passed_count = sum(1 for item in testcase_results if item.get("passed"))
    failed = [item for item in testcase_results if not item.get("passed")]
    summary_stderr = ""
    if failed:
        first_fail = failed[0]
        summary_stderr = (
            "Some testcases failed. "
            f"First failing testcase={first_fail.get('testcase_id')} "
            f"reason={first_fail.get('failure_reason') or 'unknown'}"
        )

    return AttemptResult(
        stage=stage,
        passed=all_passed,
        exit_code=0 if all_passed else 1,
        stdout=f"Passed {passed_count}/{len(testcase_results)} testcases.",
        stderr=summary_stderr,
        score=round(total_score, 6),
        shim_used=shim_used,
        shim_source=shim_source,
    ), {
        "executor": "local_python_subprocess",
        "enabled": True,
        "comparison_mode": comparison_mode,
        "shim_used": shim_used,
        "shim_source": shim_source,
        "network_enforced": False,
        "max_score": max_score,
        "earned_score": round(total_score, 6),
        "testcases": testcase_results,
        "warnings": [
            "Local executor is for controlled development use until containerized/microVM sandbox is integrated.",
        ],
    }


def _execute_docker_backend(
    request: CodeEvalJobRequest,
    *,
    stage: str,
    comparison_mode: str,
    shim_used: bool,
    shim_source: str | None,
) -> tuple[AttemptResult, dict[str, Any]]:
    if request.language.value != "python":
        return AttemptResult(
            stage=stage,
            passed=False,
            exit_code=4,
            stderr=(
                f"Language '{request.language.value}' is not yet supported by "
                "the docker execution backend."
            ),
            score=0.0,
            shim_used=shim_used,
            shim_source=shim_source,
        ), {
            "executor": "docker_python",
            "enabled": True,
            "comparison_mode": comparison_mode,
            "testcases": [],
        }

    try:
        import docker
        docker_client = docker.from_env()
        docker_client.ping()
    except Exception as exc:
        return AttemptResult(
            stage=stage,
            passed=False,
            exit_code=6,
            stderr=(
                "Docker backend selected, but docker socket/SDK is not reachable from worker. "
                f"Details: {exc}"
            ),
            score=0.0,
            shim_used=shim_used,
            shim_source=shim_source,
        ), {
            "executor": "docker_python",
            "enabled": False,
            "comparison_mode": comparison_mode,
            "testcases": [],
        }

    docker_image = _resolve_docker_image(request)
    if settings.code_eval_docker_auto_pull:
        try:
            docker_client.images.pull(docker_image)
        except Exception as exc:
            return AttemptResult(
                stage=stage,
                passed=False,
                exit_code=9,
                stderr=(
                    f"Failed to pull docker image '{docker_image}' for code evaluation: {exc}"
                ),
                score=0.0,
                shim_used=shim_used,
                shim_source=shim_source,
            ), {
                "executor": "docker_python",
                "enabled": False,
                "comparison_mode": comparison_mode,
                "image": docker_image,
                "testcases": [],
            }

    testcase_results: list[dict[str, Any]] = []
    total_score = 0.0
    max_score = float(sum(float(test.weight) for test in request.testcases))

    try:
        for idx in range(len(request.testcases)):
            case_result = _run_single_testcase_docker(
                request,
                idx,
                docker_image,
                docker_client,
                comparison_mode,
            )
            testcase_results.append(case_result)
            total_score += float(case_result["awarded_score"])
    except Exception as exc:
        return AttemptResult(
            stage=stage,
            passed=False,
            exit_code=7,
            stderr=f"Docker execution backend crashed: {exc}",
            score=0.0,
            shim_used=shim_used,
            shim_source=shim_source,
        ), {
            "executor": "docker_python",
            "enabled": True,
            "comparison_mode": comparison_mode,
            "image": docker_image,
            "testcases": testcase_results,
        }

    all_passed = all(bool(item.get("passed")) for item in testcase_results)
    passed_count = sum(1 for item in testcase_results if item.get("passed"))
    failed = [item for item in testcase_results if not item.get("passed")]
    summary_stderr = ""
    if failed:
        first_fail = failed[0]
        summary_stderr = (
            "Some testcases failed. "
            f"First failing testcase={first_fail.get('testcase_id')} "
            f"reason={first_fail.get('failure_reason') or 'unknown'}"
        )

    return AttemptResult(
        stage=stage,
        passed=all_passed,
        exit_code=0 if all_passed else 1,
        stdout=f"Passed {passed_count}/{len(testcase_results)} testcases.",
        stderr=summary_stderr,
        score=round(total_score, 6),
        shim_used=shim_used,
        shim_source=shim_source,
    ), {
        "executor": "docker_python",
        "enabled": True,
        "image": docker_image,
        "comparison_mode": comparison_mode,
        "shim_used": shim_used,
        "shim_source": shim_source,
        "network_enforced": settings.code_eval_docker_force_no_network or not request.quota.network_enabled,
        "max_score": max_score,
        "earned_score": round(total_score, 6),
        "testcases": testcase_results,
        "warnings": [
            "Docker backend is an intermediate isolation layer before microVM snapshot execution.",
        ],
    }


def execute_code_eval_job(
    request: CodeEvalJobRequest,
    *,
    stage: str = "EXECUTING_RAW",
    comparison_mode: str = "strict",
    shim_used: bool = False,
    shim_source: str | None = None,
) -> tuple[AttemptResult, dict[str, Any]]:
    """Execute code-eval request using the configured execution backend."""
    if not request.testcases:
        return AttemptResult(
            stage=stage,
            passed=False,
            exit_code=2,
            stderr="No testcases were configured for this job.",
            score=0.0,
            shim_used=shim_used,
            shim_source=shim_source,
        ), {
            "executor": "local_python_subprocess",
            "comparison_mode": comparison_mode,
            "testcases": [],
        }

    backend = settings.code_eval_execution_backend.strip().lower()
    if backend == "local":
        return _execute_local_backend(
            request,
            stage=stage,
            comparison_mode=comparison_mode,
            shim_used=shim_used,
            shim_source=shim_source,
        )
    if backend == "docker":
        return _execute_docker_backend(
            request,
            stage=stage,
            comparison_mode=comparison_mode,
            shim_used=shim_used,
            shim_source=shim_source,
        )
    if backend == "microvm":
        microvm_attempt, microvm_artifacts = execute_microvm_backend(
            request,
            stage=stage,
            comparison_mode=comparison_mode,
            shim_used=shim_used,
            shim_source=shim_source,
        )

        delegate_backend = str(microvm_artifacts.get("delegate_backend") or "").strip().lower()
        if bool(microvm_artifacts.get("adapter_ready")) and delegate_backend in {"local", "docker"}:
            if delegate_backend == "local":
                delegate_attempt, delegate_artifacts = _execute_local_backend(
                    request,
                    stage=stage,
                    comparison_mode=comparison_mode,
                    shim_used=shim_used,
                    shim_source=shim_source,
                )
            else:
                delegate_attempt, delegate_artifacts = _execute_docker_backend(
                    request,
                    stage=stage,
                    comparison_mode=comparison_mode,
                    shim_used=shim_used,
                    shim_source=shim_source,
                )

            return delegate_attempt, {
                **delegate_artifacts,
                "executor": "microvm_adapter",
                "microvm_adapter": microvm_artifacts,
                "delegate_backend": delegate_backend,
                "fallback_used": False,
            }

        adapter_ready = bool(microvm_artifacts.get("adapter_ready"))
        if adapter_ready or not settings.code_eval_microvm_allow_fallback:
            return microvm_attempt, microvm_artifacts

        fallback_backend = settings.code_eval_microvm_fallback_backend.strip().lower()
        if fallback_backend == "local":
            fallback_attempt, fallback_artifacts = _execute_local_backend(
                request,
                stage=stage,
                comparison_mode=comparison_mode,
                shim_used=shim_used,
                shim_source=shim_source,
            )
        elif fallback_backend == "docker":
            fallback_attempt, fallback_artifacts = _execute_docker_backend(
                request,
                stage=stage,
                comparison_mode=comparison_mode,
                shim_used=shim_used,
                shim_source=shim_source,
            )
        else:
            return AttemptResult(
                stage=stage,
                passed=False,
                exit_code=12,
                stderr=(
                    "MicroVM fallback backend is invalid. "
                    f"Got '{settings.code_eval_microvm_fallback_backend}', "
                    "supported fallback values are local or docker."
                ),
                score=0.0,
                shim_used=shim_used,
                shim_source=shim_source,
            ), {
                "executor": "microvm_adapter",
                "adapter_ready": False,
                "comparison_mode": comparison_mode,
                "microvm_adapter": microvm_artifacts,
                "fallback_backend": settings.code_eval_microvm_fallback_backend,
            }

        return fallback_attempt, {
            **fallback_artifacts,
            "microvm_adapter": microvm_artifacts,
            "fallback_backend": fallback_backend,
            "fallback_used": True,
        }

    return AttemptResult(
        stage=stage,
        passed=False,
        exit_code=8,
        stderr=(
            f"Unknown code-eval execution backend '{settings.code_eval_execution_backend}'. "
            "Supported values: local, docker, microvm."
        ),
        score=0.0,
        shim_used=shim_used,
        shim_source=shim_source,
    ), {
        "executor": "unknown",
        "enabled": False,
        "comparison_mode": comparison_mode,
        "testcases": [],
    }
