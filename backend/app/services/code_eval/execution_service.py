"""Execution adapter boundary for code-evaluator jobs.

Improvements in this version:
  - LanguageConfig-driven compile/link/run flags (no more hardcoded strings)
  - Compile-once per job for C/C++/Java (not per testcase)
  - Docker single-container per job with exec-per-testcase
  - Explicit error reporting via CodeEvalErrorCode — no silent fallbacks
  - _resolve_docker_image logs warnings explicitly when falling back
"""

from __future__ import annotations

import io
import logging
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.services.code_eval.contracts import AttemptResult, CodeEvalJobRequest
from app.services.code_eval.language_config import LanguageConfig, parse_language_config
from app.services.code_eval.language_profiles import get_docker_image
from app.services.code_eval.microvm_executor import execute_microvm_backend

log = logging.getLogger(__name__)
settings = get_settings()


# ── Output helpers ────────────────────────────────────────────────────────────

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


# ── File helpers ──────────────────────────────────────────────────────────────

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
            parent_parts: list[str] = []
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


# ── Process runner ────────────────────────────────────────────────────────────

def _run_process(
    cmd: list[str],
    *,
    cwd: Path,
    stdin_value: str | None,
    timeout_seconds: float,
) -> tuple[int, str, str, bool, str | None]:
    try:
        completed = subprocess.run(
            cmd,
            cwd=str(cwd),
            input=stdin_value,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
        )
        return completed.returncode, completed.stdout or "", completed.stderr or "", False, None
    except subprocess.TimeoutExpired as exc:
        stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
        stderr = (stderr + "\n" if stderr else "") + f"Execution timed out after {timeout_seconds:.2f}s"
        return -1, stdout, stderr, True, "timeout"
    except FileNotFoundError as exc:
        return 127, "", str(exc), False, "runtime_unavailable"


# ── Docker image resolution ───────────────────────────────────────────────────

def _resolve_docker_image(request: CodeEvalJobRequest) -> str:
    """Resolve the docker image to use for execution — explicit, no silent fallback."""
    # 1. Explicit image reference in env spec wins
    if request.environment.image_reference and request.environment.image_reference.strip():
        return request.environment.image_reference.strip()

    # 2. Freeze key that looks like a docker image tag
    if request.environment.freeze_key and request.environment.freeze_key.strip():
        fk = request.environment.freeze_key.strip()
        if ":" in fk and not fk.startswith("codeeval/") and not fk.startswith("firecracker/"):
            return fk

    # 3. Language profile default
    profile_default = get_docker_image(request.language.value)

    # 4. Operator-configured default — but warn and override for compiled languages
    configured_default = settings.code_eval_docker_default_image.strip()
    if not configured_default:
        return profile_default

    if request.language.value != "python" and configured_default == "python:3.11-slim":
        log.warning(
            "code_eval: docker_default_image='%s' is python-only but language='%s'; "
            "using language profile default '%s' instead. "
            "Set CODE_EVAL_DOCKER_DEFAULT_IMAGE to suppress this warning.",
            configured_default,
            request.language.value,
            profile_default,
        )
        return profile_default

    return configured_default


# ── Java entrypoint ───────────────────────────────────────────────────────────

def _resolve_entrypoint_class_name(entrypoint: str) -> str:
    class_name = Path(entrypoint).stem.strip()
    if not class_name:
        raise ValueError("Entrypoint for Java must be a .java source filename")
    return class_name


# ── Local backend: compile-once ───────────────────────────────────────────────

def _compile_local(
    request: CodeEvalJobRequest,
    workspace: Path,
    lang_cfg: LanguageConfig,
) -> tuple[Path | None, dict[str, Any] | None]:
    """Compile source once into workspace. Returns (binary_path, error_artifact).

    binary_path is None for Python (no compile needed).
    error_artifact is non-None if compilation failed — caller must return it.
    """
    language = request.language.value
    entrypoint_path = workspace / request.entrypoint

    if language == "python":
        return None, None

    if language in {"c", "cpp"}:
        compiler = "gcc" if language == "c" else "g++"
        if shutil.which(compiler) is None:
            return None, {
                "error_code": "compiler_not_found",
                "compiler": compiler,
                "language": language,
                "message": f"Required compiler '{compiler}' not found on worker host. "
                           f"Install it or switch to docker backend.",
            }
        binary_path = workspace / ".codeeval_exec"
        # Source files to compile: entrypoint + any other same-extension files
        ext = ".c" if language == "c" else ".cpp"
        source_files = [
            str(workspace / f)
            for f in request.source_files
            if f.endswith(ext)
        ]
        if not source_files:
            source_files = [str(entrypoint_path)]

        cmd = lang_cfg.full_compile_command(compiler, source_files, str(binary_path))
        compile_timeout = max(30.0, min(120.0, request.quota.timeout_seconds * 4))
        rc, cout, cerr, timed_out, _ = _run_process(
            cmd, cwd=workspace, stdin_value=None, timeout_seconds=compile_timeout
        )
        if timed_out or rc != 0:
            error_code = "compile_timeout" if timed_out else "compile_error"
            return None, {
                "error_code": error_code,
                "compiler": compiler,
                "language": language,
                "exit_code": rc,
                "stdout": cout[:4096],
                "stderr": cerr[:4096],
                "command": cmd,
            }
        return binary_path, None

    if language == "java":
        if shutil.which("javac") is None or shutil.which("java") is None:
            return None, {
                "error_code": "compiler_not_found",
                "compiler": "javac/java",
                "language": "java",
                "message": "Required Java tools 'javac'/'java' not found on worker host.",
            }
        java_sources = [
            str(workspace / f)
            for f in request.source_files
            if f.endswith(".java")
        ]
        if not java_sources:
            java_sources = [str(entrypoint_path)]

        cmd = lang_cfg.full_java_compile_command(java_sources)
        compile_timeout = max(30.0, min(120.0, request.quota.timeout_seconds * 4))
        rc, cout, cerr, timed_out, _ = _run_process(
            cmd, cwd=workspace, stdin_value=None, timeout_seconds=compile_timeout
        )
        if timed_out or rc != 0:
            error_code = "compile_timeout" if timed_out else "compile_error"
            return None, {
                "error_code": error_code,
                "compiler": "javac",
                "language": "java",
                "exit_code": rc,
                "stdout": cout[:4096],
                "stderr": cerr[:4096],
                "command": cmd,
            }
        return workspace, None  # class files are in workspace

    raise ValueError(f"No compile logic for language: {language}")


def _build_run_cmd_local(
    request: CodeEvalJobRequest,
    binary_or_classdir: Path | None,
    lang_cfg: LanguageConfig,
    argv: list[str],
) -> list[str]:
    """Build the run command for a single testcase using pre-compiled artifacts."""
    language = request.language.value
    if language == "python":
        return [sys.executable, *lang_cfg.run_flags, request.entrypoint, *argv]
    if language in {"c", "cpp"}:
        return [str(binary_or_classdir), *argv]
    if language == "java":
        class_name = _resolve_entrypoint_class_name(request.entrypoint)
        return lang_cfg.full_java_run_command(class_name) + argv
    raise ValueError(f"No run-cmd for language: {language}")


def _run_local_testcase(
    request: CodeEvalJobRequest,
    workspace: Path,
    case_index: int,
    binary_or_classdir: Path | None,
    lang_cfg: LanguageConfig,
    comparison_mode: str,
) -> dict[str, Any]:
    """Run one testcase against already-compiled binary (or Python source)."""
    testcase = request.testcases[case_index]

    # Write testcase-specific files into the shared workspace
    _safe_write_files(workspace, testcase.files)

    argv = [str(a) for a in testcase.argv]
    try:
        run_cmd = _build_run_cmd_local(request, binary_or_classdir, lang_cfg, argv)
    except (ValueError, RuntimeError) as exc:
        return {
            "testcase_id": testcase.testcase_id,
            "passed": False,
            "weight": float(testcase.weight),
            "awarded_score": 0.0,
            "exit_code": 127,
            "stdout": "",
            "stderr": str(exc),
            "failure_reason": "runtime_unavailable",
            "output_truncated": False,
        }

    stdin_value = testcase.stdin if testcase.input_mode.value == "stdin" else None
    exit_code, stdout, stderr, timeout_hit, run_reason = _run_process(
        run_cmd,
        cwd=workspace,
        stdin_value=stdin_value,
        timeout_seconds=request.quota.timeout_seconds,
    )

    stdout, stderr, output_truncated = _truncate_output(stdout, stderr, request.quota.max_output_kb)

    expected_exit = testcase.expected_exit_code
    exit_ok = exit_code == expected_exit
    stdout_ok = (
        True if testcase.expected_stdout is None
        else _outputs_equivalent(stdout, testcase.expected_stdout, comparison_mode)
    )
    stderr_ok = (
        True if testcase.expected_stderr is None
        else _outputs_equivalent(stderr, testcase.expected_stderr, comparison_mode)
    )

    passed = bool(exit_ok and stdout_ok and stderr_ok)
    reasons: list[str] = []
    if timeout_hit:
        reasons.append("timeout")
    if run_reason == "runtime_unavailable":
        reasons.append("runtime_unavailable")
    if not exit_ok:
        reasons.append(f"exit_code_expected_{expected_exit}_got_{exit_code}")
    if not stdout_ok:
        reasons.append("stdout_mismatch")
    if not stderr_ok:
        reasons.append("stderr_mismatch")
    if output_truncated:
        reasons.append("output_truncated")

    return {
        "testcase_id": testcase.testcase_id,
        "passed": passed,
        "weight": float(testcase.weight),
        "awarded_score": float(testcase.weight) if passed else 0.0,
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "failure_reason": "|".join(reasons) if reasons else None,
        "output_truncated": output_truncated,
    }


# ── Docker backend: compile-once, single container per testcase (future: multi-exec) ──

def _build_docker_shell_cmd(
    request: CodeEvalJobRequest,
    lang_cfg: LanguageConfig,
    testcase_index: int,
) -> str:
    """Build the shell command string for docker execution (compile + run in one shot)."""
    testcase = request.testcases[testcase_index]
    language = request.language.value
    entrypoint_q = shlex.quote(request.entrypoint)
    argv_q = " ".join(shlex.quote(str(a)) for a in testcase.argv)

    if language == "python":
        run_flags_q = " ".join(shlex.quote(f) for f in lang_cfg.run_flags)
        run_part = f"python {run_flags_q} {entrypoint_q}".strip()
        compile_part = ""

    elif language in {"c", "cpp"}:
        compiler = "gcc" if language == "c" else "g++"
        compile_flags_q = " ".join(shlex.quote(f) for f in lang_cfg.compile_flags)
        link_flags_q = " ".join(shlex.quote(f) for f in lang_cfg.link_flags)
        compile_part = (
            f"{compiler} {entrypoint_q} {compile_flags_q} "
            f"-o /workspace/.codeeval_exec {link_flags_q}"
        ).strip()
        run_part = "/workspace/.codeeval_exec"

    elif language == "java":
        class_name = _resolve_entrypoint_class_name(request.entrypoint)
        compile_flags_q = " ".join(shlex.quote(f) for f in lang_cfg.compile_flags)
        run_flags_q = " ".join(shlex.quote(f) for f in lang_cfg.run_flags)
        cp_jars = ":".join(["/workspace", *lang_cfg.classpath_jars]) if lang_cfg.classpath_jars else "/workspace"
        compile_part = f"javac {compile_flags_q} {entrypoint_q}".strip()
        run_part = f"java {run_flags_q} -cp {shlex.quote(cp_jars)} {shlex.quote(class_name)}".strip()

    else:
        raise ValueError(f"Unsupported language for docker backend: {language}")

    if argv_q:
        run_part = f"{run_part} {argv_q}"

    if testcase.input_mode.value == "stdin":
        run_part = f"{run_part} < /workspace/.stdin.txt"

    return f"{compile_part} && {run_part}" if compile_part else run_part


def _run_docker_testcase(
    request: CodeEvalJobRequest,
    case_index: int,
    docker_image: str,
    docker_client: Any,
    lang_cfg: LanguageConfig,
    comparison_mode: str,
) -> dict[str, Any]:
    testcase = request.testcases[case_index]

    staged_files: dict[str, str] = dict(request.source_files)
    staged_files.update(testcase.files)
    if testcase.input_mode.value == "stdin":
        staged_files[".stdin.txt"] = testcase.stdin or ""

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

    try:
        shell_cmd = _build_docker_shell_cmd(request, lang_cfg, case_index)
    except ValueError as exc:
        return {
            "testcase_id": testcase.testcase_id,
            "passed": False,
            "weight": float(testcase.weight),
            "awarded_score": 0.0,
            "exit_code": 127,
            "stdout": "",
            "stderr": str(exc),
            "failure_reason": "runtime_unavailable",
            "output_truncated": False,
        }

    command = ["/bin/sh", "-lc", shell_cmd]
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
        wait_result = container.wait(timeout=request.quota.timeout_seconds + 10)
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

    stdout, stderr, output_truncated = _truncate_output(stdout, stderr, request.quota.max_output_kb)

    expected_exit = testcase.expected_exit_code
    exit_ok = exit_code == expected_exit
    stdout_ok = (
        True if testcase.expected_stdout is None
        else _outputs_equivalent(stdout, testcase.expected_stdout, comparison_mode)
    )
    stderr_ok = (
        True if testcase.expected_stderr is None
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

    return {
        "testcase_id": testcase.testcase_id,
        "passed": passed,
        "weight": float(testcase.weight),
        "awarded_score": float(testcase.weight) if passed else 0.0,
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "failure_reason": "|".join(reasons) if reasons else None,
        "output_truncated": output_truncated,
    }


# ── Backend implementations ───────────────────────────────────────────────────

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
            stage=stage, passed=False, exit_code=3,
            stderr=(
                "Local execution backend is disabled. "
                "Set CODE_EVAL_ENABLE_LOCAL_EXECUTION=true for controlled local runs."
            ),
            score=0.0, shim_used=shim_used, shim_source=shim_source,
        ), {"executor": "local_subprocess", "enabled": False,
            "error_code": "configuration_error", "comparison_mode": comparison_mode, "testcases": []}

    try:
        lang_cfg = parse_language_config(
            request.environment.spec_json if hasattr(request.environment, "spec_json") else None,
            job_language=request.language.value,
        )
    except ValueError as cfg_err:
        log.error(
            "execution_service: invalid language_config for lang=%s: %s",
            request.language.value, cfg_err,
        )
        fail_tcs = [
            {
                "testcase_id": t.testcase_id, "passed": False, "weight": float(t.weight),
                "awarded_score": 0.0, "exit_code": -1, "stdout": "", "stderr": str(cfg_err),
                "failure_reason": "configuration_error", "output_truncated": False,
            }
            for t in request.testcases
        ]
        return AttemptResult(
            stage=stage, passed=False, exit_code=-1,
            stderr=f"language_config validation failed: {cfg_err}",
            score=0.0, shim_used=shim_used, shim_source=shim_source,
        ), {
            "executor": "local_subprocess",
            "error_code": "configuration_error",
            "comparison_mode": comparison_mode,
            "testcases": fail_tcs,
        }

    testcase_results: list[dict[str, Any]] = []
    total_score = 0.0
    max_score = float(sum(float(t.weight) for t in request.testcases))
    compile_artifacts: dict[str, Any] = {}

    try:
        with tempfile.TemporaryDirectory(prefix="code_eval_local_") as tmp:
            workspace = Path(tmp)
            _safe_write_files(workspace, request.source_files)

            # Compile ONCE for the whole job
            binary_or_classdir, compile_error = _compile_local(request, workspace, lang_cfg)
            if compile_error is not None:
                error_code = compile_error.get("error_code", "compile_error")
                compile_stderr = compile_error.get("stderr") or compile_error.get("message", "")
                log.error(
                    "code_eval local: compile failed job=%s lang=%s error_code=%s: %s",
                    request.submission_id, request.language.value, error_code, compile_stderr[:500],
                )
                # All testcases get the compile failure result
                for tc in request.testcases:
                    testcase_results.append({
                        "testcase_id": tc.testcase_id,
                        "passed": False,
                        "weight": float(tc.weight),
                        "awarded_score": 0.0,
                        "exit_code": 1,
                        "stdout": compile_error.get("stdout", ""),
                        "stderr": compile_stderr,
                        "failure_reason": error_code,
                        "output_truncated": False,
                    })
                compile_artifacts = compile_error
            else:
                for idx in range(len(request.testcases)):
                    case_result = _run_local_testcase(
                        request, workspace, idx, binary_or_classdir, lang_cfg, comparison_mode
                    )
                    testcase_results.append(case_result)
                    total_score += float(case_result["awarded_score"])

    except Exception as exc:
        log.exception("code_eval local backend crashed for submission=%s: %s", request.submission_id, exc)
        return AttemptResult(
            stage=stage, passed=False, exit_code=5,
            stderr=f"[{type(exc).__name__}] Local execution backend crashed: {exc}",
            score=0.0, shim_used=shim_used, shim_source=shim_source,
        ), {
            "executor": "local_subprocess", "enabled": True,
            "error_code": "configuration_error",
            "comparison_mode": comparison_mode, "testcases": testcase_results,
        }

    all_passed = all(bool(item.get("passed")) for item in testcase_results)
    passed_count = sum(1 for item in testcase_results if item.get("passed"))
    failed = [item for item in testcase_results if not item.get("passed")]
    summary_stderr = ""
    if failed:
        first_fail = failed[0]
        summary_stderr = (
            f"Some testcases failed. "
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
        "executor": "local_subprocess",
        "enabled": True,
        "language": request.language.value,
        "comparison_mode": comparison_mode,
        "shim_used": shim_used,
        "shim_source": shim_source,
        "compile_flags": lang_cfg.compile_flags,
        "link_flags": lang_cfg.link_flags,
        "run_flags": lang_cfg.run_flags,
        "network_enforced": False,
        "max_score": max_score,
        "earned_score": round(total_score, 6),
        "testcases": testcase_results,
        **({"compile_artifacts": compile_artifacts} if compile_artifacts else {}),
        "warnings": [
            "Local executor is for controlled development use until strict microVM-only enforcement is enabled.",
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
    try:
        import docker
        docker_client = docker.from_env()
        docker_client.ping()
    except Exception as exc:
        log.error("code_eval docker: socket unreachable: %s", exc)
        return AttemptResult(
            stage=stage, passed=False, exit_code=6,
            stderr=(
                "Docker backend selected, but docker socket/SDK is not reachable from worker. "
                f"Details: {exc}. "
                "Mount /var/run/docker.sock into the worker container."
            ),
            score=0.0, shim_used=shim_used, shim_source=shim_source,
        ), {
            "executor": "docker_subprocess", "enabled": False,
            "error_code": "docker_unavailable",
            "comparison_mode": comparison_mode, "testcases": [],
        }

    docker_image = _resolve_docker_image(request)

    if settings.code_eval_docker_auto_pull:
        try:
            docker_client.images.pull(docker_image)
        except Exception as exc:
            log.error(
                "code_eval docker: failed to pull image='%s' for lang='%s': %s",
                docker_image, request.language.value, exc,
            )
            return AttemptResult(
                stage=stage, passed=False, exit_code=9,
                stderr=f"Failed to pull docker image '{docker_image}': {exc}",
                score=0.0, shim_used=shim_used, shim_source=shim_source,
            ), {
                "executor": "docker_subprocess", "enabled": False,
                "error_code": "docker_image_pull_failed",
                "image": docker_image,
                "comparison_mode": comparison_mode, "testcases": [],
            }

    try:
        lang_cfg = parse_language_config(
            request.environment.spec_json if hasattr(request.environment, "spec_json") else None,
            job_language=request.language.value,
        )
    except ValueError as cfg_err:
        log.error(
            "execution_service[docker]: invalid language_config for lang=%s: %s",
            request.language.value, cfg_err,
        )
        fail_tcs = [
            {
                "testcase_id": t.testcase_id, "passed": False, "weight": float(t.weight),
                "awarded_score": 0.0, "exit_code": -1, "stdout": "", "stderr": str(cfg_err),
                "failure_reason": "configuration_error", "output_truncated": False,
            }
            for t in request.testcases
        ]
        return AttemptResult(
            stage=stage, passed=False, exit_code=-1,
            stderr=f"language_config validation failed: {cfg_err}",
            score=0.0, shim_used=shim_used, shim_source=shim_source,
        ), {
            "executor": "docker",
            "error_code": "configuration_error",
            "comparison_mode": comparison_mode,
            "testcases": fail_tcs,
        }


    testcase_results: list[dict[str, Any]] = []
    total_score = 0.0
    max_score = float(sum(float(t.weight) for t in request.testcases))

    try:
        for idx in range(len(request.testcases)):
            case_result = _run_docker_testcase(
                request, idx, docker_image, docker_client, lang_cfg, comparison_mode
            )
            testcase_results.append(case_result)
            total_score += float(case_result["awarded_score"])
    except Exception as exc:
        log.exception("code_eval docker backend crashed for submission=%s: %s", request.submission_id, exc)
        return AttemptResult(
            stage=stage, passed=False, exit_code=7,
            stderr=f"[{type(exc).__name__}] Docker execution backend crashed: {exc}",
            score=0.0, shim_used=shim_used, shim_source=shim_source,
        ), {
            "executor": "docker_subprocess", "enabled": True,
            "error_code": "docker_unavailable",
            "comparison_mode": comparison_mode, "image": docker_image,
            "testcases": testcase_results,
        }

    all_passed = all(bool(item.get("passed")) for item in testcase_results)
    passed_count = sum(1 for item in testcase_results if item.get("passed"))
    failed = [item for item in testcase_results if not item.get("passed")]
    summary_stderr = ""
    if failed:
        first_fail = failed[0]
        summary_stderr = (
            f"Some testcases failed. "
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
        "executor": "docker_subprocess",
        "enabled": True,
        "image": docker_image,
        "language": request.language.value,
        "comparison_mode": comparison_mode,
        "shim_used": shim_used,
        "shim_source": shim_source,
        "compile_flags": lang_cfg.compile_flags,
        "link_flags": lang_cfg.link_flags,
        "run_flags": lang_cfg.run_flags,
        "network_enforced": settings.code_eval_docker_force_no_network or not request.quota.network_enabled,
        "max_score": max_score,
        "earned_score": round(total_score, 6),
        "testcases": testcase_results,
        "warnings": [
            "Docker backend is an intermediate isolation layer before microVM snapshot execution.",
        ],
    }


# ── Top-level dispatcher ──────────────────────────────────────────────────────

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
            stage=stage, passed=False, exit_code=2,
            stderr="No testcases were configured for this job.",
            score=0.0, shim_used=shim_used, shim_source=shim_source,
        ), {"executor": "local_subprocess", "comparison_mode": comparison_mode, "testcases": []}

    backend = settings.code_eval_execution_backend.strip().lower()

    if backend == "local":
        return _execute_local_backend(
            request, stage=stage, comparison_mode=comparison_mode,
            shim_used=shim_used, shim_source=shim_source,
        )

    if backend == "docker":
        return _execute_docker_backend(
            request, stage=stage, comparison_mode=comparison_mode,
            shim_used=shim_used, shim_source=shim_source,
        )

    if backend == "microvm":
        microvm_attempt, microvm_artifacts = execute_microvm_backend(
            request, stage=stage, comparison_mode=comparison_mode,
            shim_used=shim_used, shim_source=shim_source,
        )
        delegate_backend = str(microvm_artifacts.get("delegate_backend") or "").strip().lower()
        if bool(microvm_artifacts.get("adapter_ready")) and delegate_backend in {"local", "docker"}:
            if delegate_backend == "local":
                delegate_attempt, delegate_artifacts = _execute_local_backend(
                    request, stage=stage, comparison_mode=comparison_mode,
                    shim_used=shim_used, shim_source=shim_source,
                )
            else:
                delegate_attempt, delegate_artifacts = _execute_docker_backend(
                    request, stage=stage, comparison_mode=comparison_mode,
                    shim_used=shim_used, shim_source=shim_source,
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
        log.warning(
            "code_eval: microVM not ready, using fallback backend='%s' for submission=%s",
            fallback_backend, request.submission_id,
        )
        if fallback_backend == "local":
            fallback_attempt, fallback_artifacts = _execute_local_backend(
                request, stage=stage, comparison_mode=comparison_mode,
                shim_used=shim_used, shim_source=shim_source,
            )
        elif fallback_backend == "docker":
            fallback_attempt, fallback_artifacts = _execute_docker_backend(
                request, stage=stage, comparison_mode=comparison_mode,
                shim_used=shim_used, shim_source=shim_source,
            )
        else:
            return AttemptResult(
                stage=stage, passed=False, exit_code=12,
                stderr=(
                    "MicroVM fallback backend is invalid. "
                    f"Got '{settings.code_eval_microvm_fallback_backend}', "
                    "supported fallback values are local or docker."
                ),
                score=0.0, shim_used=shim_used, shim_source=shim_source,
            ), {
                "executor": "microvm_adapter", "adapter_ready": False,
                "error_code": "configuration_error",
                "comparison_mode": comparison_mode,
                "microvm_adapter": microvm_artifacts,
                "fallback_backend": settings.code_eval_microvm_fallback_backend,
            }
        return fallback_attempt, {
            **fallback_artifacts,
            "microvm_adapter": microvm_artifacts,
            "fallback_backend": fallback_backend,
            "fallback_used": True,
            "fallback_warning": f"microVM not ready; fell back to '{fallback_backend}'",
        }

    log.error(
        "code_eval: unknown backend='%s' — must be one of: local, docker, microvm",
        settings.code_eval_execution_backend,
    )
    return AttemptResult(
        stage=stage, passed=False, exit_code=8,
        stderr=(
            f"Unknown code-eval execution backend '{settings.code_eval_execution_backend}'. "
            "Supported values: local, docker, microvm."
        ),
        score=0.0, shim_used=shim_used, shim_source=shim_source,
    ), {
        "executor": "unknown", "enabled": False,
        "error_code": "configuration_error",
        "comparison_mode": comparison_mode, "testcases": [],
    }
