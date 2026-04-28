#!/usr/bin/env python
"""Firecracker guest-agent using length-prefixed JSON frames.

This implementation intentionally targets Python 2.7+ and Python 3.x so it can
run inside minimal Ubuntu 18.04 Firecracker rootfs images that may not have
python3 preinstalled.
"""

from __future__ import print_function

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import ctypes
import select


PY2 = sys.version_info[0] == 2
AF_VSOCK_FAMILY = getattr(socket, "AF_VSOCK", 40)
VMADDR_CID_ANY = getattr(socket, "VMADDR_CID_ANY", 4294967295)
try:
    text_type = unicode  # type: ignore[name-defined]
except NameError:
    text_type = str


def _to_bytes(value):
    if isinstance(value, bytes):
        return value
    if PY2 and isinstance(value, str):
        return value
    return value.encode("utf-8")


def _to_text(value):
    if value is None:
        return ""
    if PY2:
        if isinstance(value, text_type):
            return value
        if isinstance(value, str):
            return value.decode("utf-8", "replace")
        return text_type(value)

    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def _read_exact(sock, total):
    chunks = []
    remaining = int(total)
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise RuntimeError("stream closed while reading frame")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _recv_frame(sock):
    header = _read_exact(sock, 4)
    if PY2:
        size = 0
        for ch in bytearray(header):
            size = (size << 8) | int(ch)
    else:
        size = int.from_bytes(header, "big")

    if size <= 0 or size > 8 * 1024 * 1024:
        raise RuntimeError("invalid frame size: {}".format(size))

    body = _read_exact(sock, size)
    payload = json.loads(_to_text(body))
    if not isinstance(payload, dict):
        raise RuntimeError("frame payload must be JSON object")
    return payload


def _send_frame(sock, payload):
    body = _to_bytes(json.dumps(payload))
    size = len(body)
    if PY2:
        header = "".join(chr((size >> shift) & 0xFF) for shift in (24, 16, 8, 0))
    else:
        header = size.to_bytes(4, "big")
    sock.sendall(_to_bytes(header))
    sock.sendall(body)


def _normalize_text(value):
    return _to_text(value).replace("\r\n", "\n").rstrip("\n")


def _collapse_whitespace(value):
    return " ".join(_to_text(value).split())


def _outputs_equivalent(actual, expected, comparison_mode):
    if comparison_mode == "whitespace_normalized":
        return _collapse_whitespace(actual) == _collapse_whitespace(expected)
    return _normalize_text(actual) == _normalize_text(expected)


def _safe_write_files(root, files):
    root = os.path.realpath(root)
    for relative_path, content in files.items():
        rel = _to_text(relative_path)
        if rel.startswith("/") or ".." in rel.split("/"):
            raise ValueError("unsafe path in payload: {}".format(rel))

        target = os.path.realpath(os.path.join(root, rel))
        if not (target == root or target.startswith(root + os.sep)):
            raise ValueError("path escapes sandbox root: {}".format(rel))

        target_dir = os.path.dirname(target)
        if target_dir and not os.path.exists(target_dir):
            os.makedirs(target_dir)

        with open(target, "w") as fh:
            fh.write(_to_text(content).encode("utf-8") if PY2 else _to_text(content))


def _truncate_output(stdout, stderr, max_output_kb):
    max_bytes = int(max_output_kb) * 1024
    out_bytes = _to_bytes(_to_text(stdout))
    err_bytes = _to_bytes(_to_text(stderr))

    if len(out_bytes) + len(err_bytes) <= max_bytes:
        return _to_text(stdout), _to_text(stderr), False

    if len(out_bytes) >= max_bytes:
        return _to_text(out_bytes[:max_bytes]), "", True

    remaining = max_bytes - len(out_bytes)
    return _to_text(stdout), _to_text(err_bytes[:remaining]), True


def _which(executable):
    if not executable:
        return None
    if os.path.isabs(executable):
        if os.path.isfile(executable) and os.access(executable, os.X_OK):
            return executable
        return None

    path_env = os.getenv("PATH", "")
    for entry in path_env.split(os.pathsep):
        entry = entry.strip()
        if not entry:
            continue
        candidate = os.path.join(entry, executable)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def _split_dependency_values(raw_value):
    if raw_value is None:
        return []

    if isinstance(raw_value, list):
        values = [_to_text(item) for item in raw_value]
    else:
        text = _to_text(raw_value).strip()
        if not text:
            return []

        values = []
        if text.startswith("["):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    values.extend(_to_text(item) for item in parsed)
                else:
                    values.append(text)
            except Exception:
                values.append(text)
        else:
            values.extend(text.replace(",", "\n").splitlines())

    deps = []
    seen = set()
    for value in values:
        dep = _to_text(value).strip()
        if not dep or dep.startswith("#"):
            continue
        if dep not in seen:
            seen.add(dep)
            deps.append(dep)
    return deps


def _resolve_python_exec(request):
    requested_runtime = ""
    strict_runtime = _to_text(os.getenv("CODE_EVAL_GUEST_AGENT_STRICT_RUNTIME", "false")).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    environment = request.get("environment")
    if isinstance(environment, dict):
        requested_runtime = _to_text(environment.get("runtime") or "").strip().lower()

    override_exec = _to_text(os.getenv("CODE_EVAL_GUEST_AGENT_PYTHON_EXEC") or "").strip()
    if override_exec:
        resolved = _which(override_exec)
        if not resolved:
            raise RuntimeError("Configured CODE_EVAL_GUEST_AGENT_PYTHON_EXEC is unavailable: {}".format(override_exec))
        return resolved, requested_runtime

    candidates = []
    if requested_runtime.startswith("python-3") or requested_runtime.startswith("py3"):
        candidates = ["/usr/bin/python3", "python3"]
        for candidate in candidates:
            resolved = _which(candidate)
            if resolved:
                return resolved, requested_runtime
        if strict_runtime:
            raise RuntimeError(
                "Requested runtime {} is unavailable in guest image. Install python3 or disable strict runtime."
                .format(requested_runtime)
            )
        candidates = ["/usr/bin/python2.7", "python2.7"]
    elif requested_runtime.startswith("python-2") or requested_runtime.startswith("py2"):
        candidates = ["/usr/bin/python2.7", "python2.7", "python2"]
    else:
        candidates = ["/usr/bin/python3", "python3", "/usr/bin/python2.7", "python2.7"]

    for candidate in candidates:
        resolved = _which(candidate)
        if resolved:
            return resolved, requested_runtime

    fallback = _which(sys.executable)
    if fallback:
        return fallback, requested_runtime

    raise RuntimeError(
        "No compatible Python interpreter found for requested runtime='{}'".format(requested_runtime or "auto")
    )


def _extract_python_dependencies(request):
    environment = request.get("environment")
    if not isinstance(environment, dict):
        return []

    manifest = environment.get("manifest")
    if not isinstance(manifest, dict):
        return []

    deps = []
    for key in ("pip", "pip_packages", "requirements", "requirements_txt"):
        deps.extend(_split_dependency_values(manifest.get(key)))

    unique = []
    seen = set()
    for dep in deps:
        if dep not in seen:
            seen.add(dep)
            unique.append(dep)
    return unique


def _ensure_python_dependencies(python_exec, dependencies, sandbox_root, timeout_seconds):
    if not dependencies:
        return None

    allow_dynamic_installs = _to_text(
        os.getenv("CODE_EVAL_GUEST_AGENT_ALLOW_DYNAMIC_PIP", "false")
    ).strip().lower() in ("1", "true", "yes", "on")
    if not allow_dynamic_installs:
        raise RuntimeError(
            "Dynamic dependency installation is disabled in guest runtime. "
            "Pre-bake dependencies into the environment snapshot."
        )

    dep_dir = os.path.join(sandbox_root, "deps")
    if not os.path.exists(dep_dir):
        os.makedirs(dep_dir)

    pip_check_exit, _pip_check_out, pip_check_err, pip_check_timeout = _run_subprocess(
        [python_exec, "-m", "pip", "--version"],
        sandbox_root,
        None,
        max(timeout_seconds, 10.0),
    )
    if pip_check_timeout or pip_check_exit != 0:
        raise RuntimeError(
            "pip is unavailable for interpreter {}: {}".format(
                python_exec,
                (_to_text(pip_check_err) or "pip check failed").strip(),
            )
        )

    install_timeout = max(30.0, timeout_seconds * (1 + len(dependencies)))
    install_cmd = [
        python_exec,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-input",
        "--target",
        dep_dir,
    ] + list(dependencies)

    install_exit, install_out, install_err, install_timeout_hit = _run_subprocess(
        install_cmd,
        sandbox_root,
        None,
        install_timeout,
    )
    if install_timeout_hit:
        raise RuntimeError(
            "dependency installation timed out after {:.1f}s".format(install_timeout)
        )
    if install_exit != 0:
        message = (_to_text(install_err) or _to_text(install_out) or "pip install failed").strip()
        raise RuntimeError("dependency installation failed: {}".format(message[:800]))

    return dep_dir


def _resolve_commands(language, entrypoint, argv, python_exec):
    lang = _to_text(language).strip().lower()
    if lang == "python":
        return None, [python_exec, entrypoint] + list(argv)

    if lang == "c":
        compile_cmd = ["gcc", entrypoint, "-O2", "-std=c11", "-o", ".codeeval_exec"]
        run_cmd = ["./.codeeval_exec"] + list(argv)
        return compile_cmd, run_cmd

    if lang == "cpp":
        compile_cmd = ["g++", entrypoint, "-O2", "-std=c++17", "-o", ".codeeval_exec"]
        run_cmd = ["./.codeeval_exec"] + list(argv)
        return compile_cmd, run_cmd

    if lang == "java":
        class_name = os.path.splitext(os.path.basename(entrypoint))[0]
        if not class_name:
            raise ValueError("Invalid Java entrypoint")
        compile_cmd = ["javac", entrypoint]
        run_cmd = ["java", "-cp", ".", class_name] + list(argv)
        return compile_cmd, run_cmd

    raise ValueError("guest agent does not support language '{}'".format(lang))


def _run_subprocess(cmd, cwd, stdin_value, timeout_seconds, env_overrides=None):
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env_overrides,
    )

    input_bytes = None
    if stdin_value is not None:
        input_bytes = _to_bytes(_to_text(stdin_value))

    deadline = time.time() + float(timeout_seconds)
    stdout_chunks = []
    stderr_chunks = []

    if input_bytes is not None:
        try:
            proc.stdin.write(input_bytes)
        except Exception:
            pass
    try:
        proc.stdin.close()
    except Exception:
        pass

    timeout_hit = False
    while True:
        if proc.poll() is not None:
            break
        if time.time() >= deadline:
            timeout_hit = True
            try:
                proc.kill()
            except Exception:
                pass
            break
        time.sleep(0.05)

    try:
        proc.wait()
    except Exception:
        pass

    out = b""
    err = b""
    try:
        if proc.stdout is not None:
            out = proc.stdout.read() or b""
    except Exception:
        out = b""
    try:
        if proc.stderr is not None:
            err = proc.stderr.read() or b""
    except Exception:
        err = b""

    stdout_chunks.append(out)
    stderr_chunks.append(err)

    stdout_text = _to_text(b"".join(stdout_chunks))
    stderr_text = _to_text(b"".join(stderr_chunks))
    return int(proc.returncode if proc.returncode is not None else -1), stdout_text, stderr_text, timeout_hit


def _run_request(payload):
    comparison_mode = _to_text(payload.get("comparison_mode") or "strict")
    request = payload.get("request")
    if not isinstance(request, dict):
        raise ValueError("missing request object")

    language = _to_text(request.get("language") or "").lower()

    source_files = request.get("source_files") or {}
    if not isinstance(source_files, dict):
        raise ValueError("request.source_files must be an object")

    testcases = request.get("testcases") or []
    if not isinstance(testcases, list) or not testcases:
        return {
            "passed": False,
            "exit_code": 2,
            "stdout": "",
            "stderr": "No testcases configured.",
            "score": 0.0,
            "artifacts": {"engine": "firecracker_guest_agent", "testcases": []},
        }

    entrypoint = _to_text(request.get("entrypoint") or "")
    if not entrypoint:
        raise ValueError("request.entrypoint is required")

    quota = request.get("quota") or {}
    timeout_seconds = float(quota.get("timeout_seconds", 5.0))
    max_output_kb = int(quota.get("max_output_kb", 256))

    requested_runtime = ""
    environment = request.get("environment")
    if isinstance(environment, dict):
        requested_runtime = _to_text(environment.get("runtime") or "").strip().lower()

    python_exec = None
    dependencies = []
    if language == "python":
        python_exec, requested_runtime = _resolve_python_exec(request)
        dependencies = _extract_python_dependencies(request)

    testcase_results = []
    total_score = 0.0
    sandbox_root = tempfile.mkdtemp(prefix="guest_agent_case_")
    dependency_dir = None
    exec_env = None

    try:
        if language == "python":
            dependency_dir = _ensure_python_dependencies(
                python_exec,
                dependencies,
                sandbox_root,
                timeout_seconds,
            )
            if dependency_dir:
                exec_env = dict(os.environ)
                existing_pythonpath = _to_text(exec_env.get("PYTHONPATH") or "").strip()
                exec_env["PYTHONPATH"] = (
                    dependency_dir + (os.pathsep + existing_pythonpath if existing_pythonpath else "")
                )

        for idx, testcase in enumerate(testcases):
            if not isinstance(testcase, dict):
                continue

            case_dir = os.path.join(sandbox_root, "case_{}".format(idx + 1))
            if not os.path.exists(case_dir):
                os.makedirs(case_dir)

            files = testcase.get("files") or {}
            if not isinstance(files, dict):
                files = {}

            _safe_write_files(case_dir, source_files)
            _safe_write_files(case_dir, files)

            testcase_id = _to_text(testcase.get("testcase_id") or "tc_{}".format(idx + 1))
            weight = float(testcase.get("weight", 1.0))

            resolved_entrypoint = os.path.realpath(os.path.join(case_dir, entrypoint))
            if not os.path.exists(resolved_entrypoint):
                testcase_results.append(
                    {
                        "testcase_id": testcase_id,
                        "passed": False,
                        "weight": weight,
                        "awarded_score": 0.0,
                        "exit_code": -2,
                        "stdout": "",
                        "stderr": "Entrypoint not found: {}".format(entrypoint),
                        "failure_reason": "entrypoint_missing",
                    }
                )
                continue

            argv = testcase.get("argv") or []
            if not isinstance(argv, list):
                argv = []

            compile_cmd, run_cmd = _resolve_commands(
                language,
                entrypoint,
                [_to_text(a) for a in argv],
                python_exec,
            )

            if compile_cmd is not None:
                compile_timeout = max(2.0, min(20.0, timeout_seconds))
                compile_exit, compile_out, compile_err, compile_timeout_hit = _run_subprocess(
                    compile_cmd,
                    case_dir,
                    None,
                    compile_timeout,
                    env_overrides=None,
                )
                if compile_timeout_hit or compile_exit != 0:
                    compile_out, compile_err, compile_output_truncated = _truncate_output(
                        compile_out,
                        compile_err,
                        max_output_kb,
                    )
                    reasons = ["compile_timeout" if compile_timeout_hit else "compile_error"]
                    if compile_output_truncated:
                        reasons.append("output_truncated")
                    testcase_results.append(
                        {
                            "testcase_id": testcase_id,
                            "passed": False,
                            "weight": weight,
                            "awarded_score": 0.0,
                            "exit_code": int(compile_exit),
                            "stdout": compile_out,
                            "stderr": compile_err,
                            "failure_reason": "|".join(reasons),
                        }
                    )
                    continue

            input_mode = _to_text(testcase.get("input_mode") or "stdin")
            stdin_value = _to_text(testcase.get("stdin") or "") if input_mode == "stdin" else None

            exit_code, stdout, stderr, timeout_hit = _run_subprocess(
                run_cmd,
                case_dir,
                stdin_value,
                timeout_seconds,
                env_overrides=exec_env,
            )

            if timeout_hit:
                stderr = (stderr + "\n" if stderr else "") + (
                    "Execution timed out after {:.2f}s".format(timeout_seconds)
                )

            stdout, stderr, output_truncated = _truncate_output(stdout, stderr, max_output_kb)

            expected_stdout = testcase.get("expected_stdout")
            expected_stderr = testcase.get("expected_stderr")
            expected_exit_code = int(testcase.get("expected_exit_code", 0))

            exit_ok = exit_code == expected_exit_code
            stdout_ok = True if expected_stdout is None else _outputs_equivalent(stdout, _to_text(expected_stdout), comparison_mode)
            stderr_ok = True if expected_stderr is None else _outputs_equivalent(stderr, _to_text(expected_stderr), comparison_mode)

            passed = bool(exit_ok and stdout_ok and stderr_ok)
            reasons = []
            if timeout_hit:
                reasons.append("timeout")
            if not exit_ok:
                reasons.append("exit_code_expected_{}_got_{}".format(expected_exit_code, exit_code))
            if not stdout_ok:
                reasons.append("stdout_mismatch")
            if not stderr_ok:
                reasons.append("stderr_mismatch")
            if output_truncated:
                reasons.append("output_truncated")

            awarded = weight if passed else 0.0
            total_score += awarded
            testcase_results.append(
                {
                    "testcase_id": testcase_id,
                    "passed": passed,
                    "weight": weight,
                    "awarded_score": awarded,
                    "exit_code": exit_code,
                    "stdout": stdout,
                    "stderr": stderr,
                    "failure_reason": "|".join(reasons) if reasons else None,
                }
            )
    finally:
        shutil.rmtree(sandbox_root, ignore_errors=True)

    all_passed = all(bool(tc.get("passed")) for tc in testcase_results)
    passed_count = sum(1 for tc in testcase_results if bool(tc.get("passed")))
    failed = [tc for tc in testcase_results if not bool(tc.get("passed"))]

    summary_stderr = ""
    if failed:
        first_fail = failed[0]
        summary_stderr = (
            "Some testcases failed. "
            + "First failing testcase={} reason={}".format(
                first_fail.get("testcase_id"), first_fail.get("failure_reason") or "unknown"
            )
        )

    return {
        "passed": all_passed,
        "exit_code": 0 if all_passed else 1,
        "stdout": "Guest agent passed {}/{} testcases.".format(passed_count, len(testcase_results)),
        "stderr": summary_stderr,
        "score": round(total_score, 6),
        "artifacts": {
            "engine": "firecracker_guest_agent",
            "language": language,
            "comparison_mode": comparison_mode,
            "requested_runtime": requested_runtime or "auto",
            "python_exec": python_exec,
            "dependencies": dependencies,
            "dependency_dir": dependency_dir,
            "testcase_count": len(testcase_results),
            "testcases": testcase_results,
        },
    }


class _FDConnection(object):
    def __init__(self, fd):
        self.fd = int(fd)

    def recv(self, nbytes):
        return os.read(self.fd, int(nbytes))

    def sendall(self, data):
        buf = _to_bytes(data)
        sent = 0
        total = len(buf)
        while sent < total:
            sent_now = os.write(self.fd, buf[sent:])
            if sent_now <= 0:
                raise RuntimeError("failed to write to connection")
            sent += sent_now

    def close(self):
        try:
            os.close(self.fd)
        except Exception:
            pass


class _SockAddrVM(ctypes.Structure):
    _fields_ = [
        ("svm_family", ctypes.c_ushort),
        ("svm_reserved1", ctypes.c_ushort),
        ("svm_port", ctypes.c_uint),
        ("svm_cid", ctypes.c_uint),
        ("svm_zero", ctypes.c_ubyte * 4),
    ]


def _vsock_bind_py2(server_sock, port):
    libc = ctypes.CDLL(None, use_errno=True)
    fd = int(server_sock.fileno())

    addr = _SockAddrVM()
    addr.svm_family = int(AF_VSOCK_FAMILY)
    addr.svm_reserved1 = 0
    addr.svm_port = int(port)
    addr.svm_cid = int(VMADDR_CID_ANY)
    addr.svm_zero = (ctypes.c_ubyte * 4)(0, 0, 0, 0)

    ret = libc.bind(fd, ctypes.byref(addr), ctypes.sizeof(addr))
    if ret != 0:
        err = ctypes.get_errno()
        raise RuntimeError("vsock bind failed errno={}".format(err))


def _vsock_accept_py2(server_sock):
    libc = ctypes.CDLL(None, use_errno=True)
    fd = int(server_sock.fileno())

    peer = _SockAddrVM()
    peer_len = ctypes.c_uint(ctypes.sizeof(peer))
    conn_fd = libc.accept(fd, ctypes.byref(peer), ctypes.byref(peer_len))
    if conn_fd < 0:
        err = ctypes.get_errno()
        raise RuntimeError("vsock accept failed errno={}".format(err))
    return _FDConnection(conn_fd)


def _serve_vsock(port):
    rebind_interval = float(os.getenv("CODE_EVAL_GUEST_AGENT_REBIND_SECONDS", "5"))
    if rebind_interval < 1.0:
        rebind_interval = 1.0

    while True:
        server = socket.socket(AF_VSOCK_FAMILY, socket.SOCK_STREAM)
        try:
            if PY2:
                _vsock_bind_py2(server, port)
            else:
                server.bind((VMADDR_CID_ANY, int(port)))
            server.listen(16)

            print("Guest agent listening on vsock port {}".format(port))
            try:
                sys.stdout.flush()
            except Exception:
                pass

            started = time.time()
            while True:
                if time.time() - started >= rebind_interval:
                    break

                ready, _, _ = select.select([server], [], [], 1.0)
                if not ready:
                    continue

                if PY2:
                    conn = _vsock_accept_py2(server)
                else:
                    conn, _addr = server.accept()

                try:
                    payload = _recv_frame(conn)
                    result = _run_request(payload)
                except Exception as exc:
                    result = {
                        "passed": False,
                        "exit_code": 99,
                        "stdout": "",
                        "stderr": "Guest agent error: {}".format(exc),
                        "score": 0.0,
                        "artifacts": {"engine": "firecracker_guest_agent", "error": True},
                    }

                try:
                    _send_frame(conn, result)
                finally:
                    conn.close()
        finally:
            try:
                server.close()
            except Exception:
                pass


def main():
    port = int(os.getenv("CODE_EVAL_GUEST_AGENT_PORT", "7000"))
    _serve_vsock(port)


if __name__ == "__main__":
    main()
