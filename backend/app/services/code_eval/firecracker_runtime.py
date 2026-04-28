"""Firecracker snapshot + vsock runtime executor for code-eval microVM mode.

This module restores a Firecracker VM from snapshot, resumes it, then sends a
length-prefixed JSON execution request to an in-guest vsock agent.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.services.code_eval.contracts import AttemptResult, CodeEvalJobRequest

settings = get_settings()


def _acquire_serial_lock(lock_path: Path, timeout_seconds: float) -> int:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + max(timeout_seconds, 1.0)
    while time.monotonic() < deadline:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
            os.write(fd, str(os.getpid()).encode("ascii", errors="ignore"))
            return fd
        except FileExistsError:
            time.sleep(0.1)
    raise TimeoutError(f"Timed out acquiring runtime serial lock: {lock_path}")


def _release_serial_lock(lock_fd: int | None, lock_path: Path) -> None:
    if lock_fd is None:
        return
    try:
        os.close(lock_fd)
    except Exception:
        pass
    try:
        lock_path.unlink(missing_ok=True)
    except Exception:
        pass


def _sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def collect_firecracker_preflight() -> dict[str, Any]:
    firecracker_bin = settings.code_eval_microvm_firecracker_bin.strip()
    snapshot_vmstate = settings.code_eval_microvm_snapshot_vmstate_path.strip()
    snapshot_mem = settings.code_eval_microvm_snapshot_mem_path.strip()

    binary_configured = bool(firecracker_bin)
    binary_exists = False
    if binary_configured:
        binary_exists = bool(shutil.which(firecracker_bin) or Path(firecracker_bin).exists())

    snapshot_vmstate_configured = bool(snapshot_vmstate)
    snapshot_vmstate_exists = bool(snapshot_vmstate and Path(snapshot_vmstate).exists())

    snapshot_mem_configured = bool(snapshot_mem)
    snapshot_mem_exists = bool(snapshot_mem and Path(snapshot_mem).exists())

    checks = {
        "firecracker_binary_configured": binary_configured,
        "firecracker_binary_exists": binary_exists,
        "snapshot_vmstate_configured": snapshot_vmstate_configured,
        "snapshot_vmstate_exists": snapshot_vmstate_exists,
        "snapshot_mem_configured": snapshot_mem_configured,
        "snapshot_mem_exists": snapshot_mem_exists,
        "kvm_available": Path("/dev/kvm").exists(),
        "unix_socket_supported": hasattr(socket, "AF_UNIX"),
    }
    issues = [name for name, ok in checks.items() if not ok]
    return {
        "ready": not issues,
        "checks": checks,
        "issues": issues,
        "config": {
            "firecracker_bin": firecracker_bin,
            "snapshot_vmstate_path": snapshot_vmstate,
            "snapshot_mem_path": snapshot_mem,
            "vsock_guest_cid": int(settings.code_eval_microvm_vsock_guest_cid),
            "vsock_port": int(settings.code_eval_microvm_vsock_port),
            "vsock_uds_path": settings.code_eval_microvm_vsock_uds_path,
            "host_vsock_transport": "unix_connect_command",
        },
    }


def _runtime_error(
    *,
    stage: str,
    shim_used: bool,
    shim_source: str | None,
    runtime_mode: str,
    reason: str,
    exit_code: int,
    stderr: str,
    request: CodeEvalJobRequest,
    comparison_mode: str,
    adapter_ready: bool = False,
    extra: dict[str, Any] | None = None,
) -> tuple[AttemptResult, dict[str, Any]]:
    artifacts = {
        "executor": "microvm_adapter",
        "adapter_ready": adapter_ready,
        "adapter_enabled": True,
        "runtime_mode": runtime_mode,
        "comparison_mode": comparison_mode,
        "shim_used": shim_used,
        "shim_source": shim_source,
        "reason": reason,
        "requested_runtime": request.environment.runtime,
        "freeze_key": request.environment.freeze_key,
        "network_requested": request.quota.network_enabled,
    }
    if extra:
        artifacts.update(extra)

    return AttemptResult(
        stage=stage,
        passed=False,
        exit_code=exit_code,
        stderr=stderr,
        score=0.0,
        shim_used=shim_used,
        shim_source=shim_source,
    ), artifacts


def _read_exact(sock: socket.socket, total: int) -> bytes:
    chunks: list[bytes] = []
    remaining = total
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise RuntimeError("vsock stream closed before full frame was received")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _send_frame(sock: socket.socket, payload: dict[str, Any]) -> None:
    body = json.dumps(payload).encode("utf-8")
    if len(body) > 8 * 1024 * 1024:
        raise RuntimeError("vsock frame too large (>8MB)")
    sock.sendall(len(body).to_bytes(4, "big"))
    sock.sendall(body)


def _recv_frame(sock: socket.socket) -> dict[str, Any]:
    header = _read_exact(sock, 4)
    size = int.from_bytes(header, "big")
    if size <= 0 or size > 8 * 1024 * 1024:
        raise RuntimeError(f"Invalid vsock frame size: {size}")
    body = _read_exact(sock, size)
    decoded = json.loads(body.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise RuntimeError("vsock response must be a JSON object")
    return decoded


def _recv_line(sock: socket.socket, *, max_bytes: int = 256) -> str:
    data = bytearray()
    while len(data) < max_bytes:
        chunk = sock.recv(1)
        if not chunk:
            break
        data.extend(chunk)
        if chunk == b"\n":
            break

    if not data or data[-1:] != b"\n":
        raise RuntimeError("Unexpected Firecracker vsock proxy handshake response.")

    return data.decode("utf-8", errors="replace").rstrip("\r\n")


def _connect_guest_vsock_proxy(
    uds_path: Path,
    port: int,
    timeout_seconds: float,
) -> socket.socket:
    proxy = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    proxy.settimeout(timeout_seconds)
    proxy.connect(str(uds_path))
    proxy.sendall(f"CONNECT {port}\n".encode("ascii"))
    ack = _recv_line(proxy)
    if not ack.startswith("OK "):
        proxy.close()
        raise RuntimeError(f"Firecracker vsock proxy refused CONNECT request: {ack}")
    return proxy


def _connect_guest_vsock_proxy_with_retry(
    uds_path: Path,
    port: int,
    *,
    total_timeout_seconds: float,
) -> socket.socket:
    deadline = time.monotonic() + max(total_timeout_seconds, 0.5)
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        remaining = max(deadline - time.monotonic(), 0.1)
        attempt_timeout = min(max(remaining, 0.1), 1.0)
        try:
            return _connect_guest_vsock_proxy(
                uds_path,
                port,
                timeout_seconds=attempt_timeout,
            )
        except Exception as exc:
            last_error = exc
            time.sleep(0.15)

    if last_error is not None:
        raise RuntimeError(
            "Timed out waiting for guest vsock listener readiness: "
            f"{last_error}"
        ) from last_error

    raise RuntimeError("Timed out waiting for guest vsock listener readiness.")


def _wait_for_path(path: Path, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.05)
    raise TimeoutError(f"Timed out waiting for path: {path}")


def _firecracker_api_request(
    api_socket_path: Path,
    method: str,
    request_path: str,
    payload: dict[str, Any] | None,
    timeout_seconds: float,
) -> tuple[int, str]:
    body = b""
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")

    request_head = (
        f"{method} {request_path} HTTP/1.1\r\n"
        "Host: localhost\r\n"
        "Accept: application/json\r\n"
        "Content-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Connection: close\r\n"
        "\r\n"
    ).encode("utf-8")

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout_seconds)
        sock.connect(str(api_socket_path))
        sock.sendall(request_head)
        if body:
            sock.sendall(body)

        buffer = bytearray()
        while b"\r\n\r\n" not in buffer:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buffer.extend(chunk)

        raw_head, sep, remainder = bytes(buffer).partition(b"\r\n\r\n")
        if not sep:
            raise RuntimeError("Malformed Firecracker API response: missing header terminator")

        header_lines = raw_head.splitlines()
        status_line = header_lines[0].decode("utf-8", errors="replace") if header_lines else ""
        headers: dict[str, str] = {}
        for line in header_lines[1:]:
            key_raw, _, value_raw = line.partition(b":")
            if not _:
                continue
            key = key_raw.decode("utf-8", errors="replace").strip().lower()
            value = value_raw.decode("utf-8", errors="replace").strip()
            headers[key] = value

        body_raw = bytearray(remainder)
        content_length = 0
        try:
            content_length = int(headers.get("content-length", "0") or "0")
        except ValueError:
            content_length = 0

        if content_length > len(body_raw):
            remaining = content_length - len(body_raw)
            while remaining > 0:
                chunk = sock.recv(min(4096, remaining))
                if not chunk:
                    break
                body_raw.extend(chunk)
                remaining -= len(chunk)

    parts = status_line.split(" ")
    if len(parts) < 2:
        raise RuntimeError(f"Unexpected Firecracker API response: {status_line or '<empty>'}")

    try:
        status_code = int(parts[1])
    except ValueError as exc:
        raise RuntimeError(f"Invalid Firecracker API status line: {status_line}") from exc

    body_text = bytes(body_raw).decode("utf-8", errors="replace")
    return status_code, body_text


def _terminate_process(proc: subprocess.Popen[Any] | None) -> str:
    if proc is None:
        return ""

    stderr_text = ""
    try:
        proc.terminate()
        _, stderr = proc.communicate(timeout=2)
        if isinstance(stderr, str):
            stderr_text = stderr
    except Exception:
        try:
            proc.kill()
            _, stderr = proc.communicate(timeout=1)
            if isinstance(stderr, str):
                stderr_text = stderr
        except Exception:
            pass
    return stderr_text


def execute_firecracker_vsock_backend(
    request: CodeEvalJobRequest,
    *,
    stage: str,
    comparison_mode: str,
    shim_used: bool,
    shim_source: str | None,
    runtime_mode: str,
) -> tuple[AttemptResult, dict[str, Any]]:
    firecracker_bin = settings.code_eval_microvm_firecracker_bin.strip()
    snapshot_vmstate = (
        (request.environment.snapshot_vmstate_path or "").strip()
        or settings.code_eval_microvm_snapshot_vmstate_path.strip()
    )
    snapshot_mem = (
        (request.environment.snapshot_mem_path or "").strip()
        or settings.code_eval_microvm_snapshot_mem_path.strip()
    )
    expected_vmstate_sha = (request.environment.snapshot_vmstate_sha256 or "").strip().lower()
    expected_mem_sha = (request.environment.snapshot_mem_sha256 or "").strip().lower()
    preflight = collect_firecracker_preflight()

    if not firecracker_bin:
        return _runtime_error(
            stage=stage,
            shim_used=shim_used,
            shim_source=shim_source,
            runtime_mode=runtime_mode,
            reason="firecracker_binary_not_configured",
            exit_code=17,
            stderr="CODE_EVAL_MICROVM_FIRECRACKER_BIN is not configured.",
            request=request,
            comparison_mode=comparison_mode,
            extra={"firecracker_preflight": preflight},
        )

    if not shutil.which(firecracker_bin) and not Path(firecracker_bin).exists():
        return _runtime_error(
            stage=stage,
            shim_used=shim_used,
            shim_source=shim_source,
            runtime_mode=runtime_mode,
            reason="firecracker_binary_missing",
            exit_code=17,
            stderr=f"Firecracker binary not found: {firecracker_bin}",
            request=request,
            comparison_mode=comparison_mode,
            extra={"firecracker_preflight": preflight},
        )

    if not snapshot_vmstate or not Path(snapshot_vmstate).exists():
        return _runtime_error(
            stage=stage,
            shim_used=shim_used,
            shim_source=shim_source,
            runtime_mode=runtime_mode,
            reason="snapshot_vmstate_missing",
            exit_code=18,
            stderr=(
                "Firecracker snapshot vmstate file is missing. "
                "Set CODE_EVAL_MICROVM_SNAPSHOT_VMSTATE_PATH to an existing snapshot file."
            ),
            request=request,
            comparison_mode=comparison_mode,
            extra={"firecracker_preflight": preflight},
        )

    if not snapshot_mem or not Path(snapshot_mem).exists():
        return _runtime_error(
            stage=stage,
            shim_used=shim_used,
            shim_source=shim_source,
            runtime_mode=runtime_mode,
            reason="snapshot_mem_missing",
            exit_code=18,
            stderr=(
                "Firecracker snapshot memory file is missing. "
                "Set CODE_EVAL_MICROVM_SNAPSHOT_MEM_PATH to an existing snapshot memory file."
            ),
            request=request,
            comparison_mode=comparison_mode,
            extra={"firecracker_preflight": preflight},
        )

    if expected_vmstate_sha:
        actual_vmstate_sha = _sha256_file(Path(snapshot_vmstate)).lower()
        if actual_vmstate_sha != expected_vmstate_sha:
            return _runtime_error(
                stage=stage,
                shim_used=shim_used,
                shim_source=shim_source,
                runtime_mode=runtime_mode,
                reason="snapshot_vmstate_checksum_mismatch",
                exit_code=23,
                stderr=(
                    "Snapshot vmstate checksum mismatch for selected environment artifact. "
                    f"expected={expected_vmstate_sha} actual={actual_vmstate_sha}"
                ),
                request=request,
                comparison_mode=comparison_mode,
                extra={"firecracker_preflight": preflight},
            )

    if expected_mem_sha:
        actual_mem_sha = _sha256_file(Path(snapshot_mem)).lower()
        if actual_mem_sha != expected_mem_sha:
            return _runtime_error(
                stage=stage,
                shim_used=shim_used,
                shim_source=shim_source,
                runtime_mode=runtime_mode,
                reason="snapshot_mem_checksum_mismatch",
                exit_code=23,
                stderr=(
                    "Snapshot memory checksum mismatch for selected environment artifact. "
                    f"expected={expected_mem_sha} actual={actual_mem_sha}"
                ),
                request=request,
                comparison_mode=comparison_mode,
                extra={"firecracker_preflight": preflight},
            )

    if settings.code_eval_microvm_force_no_network and request.quota.network_enabled:
        return _runtime_error(
            stage=stage,
            shim_used=shim_used,
            shim_source=shim_source,
            runtime_mode=runtime_mode,
            reason="network_not_allowed",
            exit_code=22,
            stderr=(
                "MicroVM runtime enforces network isolation. "
                "Set request.quota.network_enabled=false for this environment."
            ),
            request=request,
            comparison_mode=comparison_mode,
            extra={"firecracker_preflight": preflight},
        )

    if not Path("/dev/kvm").exists():
        return _runtime_error(
            stage=stage,
            shim_used=shim_used,
            shim_source=shim_source,
            runtime_mode=runtime_mode,
            reason="kvm_unavailable",
            exit_code=19,
            stderr="/dev/kvm is not available in this runtime environment.",
            request=request,
            comparison_mode=comparison_mode,
            extra={"firecracker_preflight": preflight},
        )

    run_id = uuid.uuid4().hex
    socket_dir = Path(settings.code_eval_microvm_api_socket_dir).resolve()
    run_dir = Path(settings.code_eval_microvm_runtime_workdir).resolve() / run_id
    serial_lock_path = Path(settings.code_eval_microvm_serial_lock_file).resolve()
    api_socket = socket_dir / f"{run_id}.sock"
    vsock_proxy_socket = run_dir / "guest_vsock.sock"
    fallback_vsock_socket = Path(settings.code_eval_microvm_vsock_uds_path).resolve()
    active_vsock_socket = vsock_proxy_socket
    vsock_override_supported = True

    proc: subprocess.Popen[Any] | None = None
    serial_lock_fd: int | None = None
    firecracker_stderr = ""
    runtime_step = "init"

    try:
        runtime_step = "acquire_runtime_lock"
        serial_lock_fd = _acquire_serial_lock(
            serial_lock_path,
            timeout_seconds=settings.code_eval_microvm_firecracker_api_timeout_seconds,
        )

        socket_dir.mkdir(parents=True, exist_ok=True)
        run_dir.mkdir(parents=True, exist_ok=True)
        fallback_vsock_socket.parent.mkdir(parents=True, exist_ok=True)
        try:
            fallback_vsock_socket.unlink(missing_ok=True)
        except Exception:
            pass

        runtime_step = "launch_firecracker"
        proc = subprocess.Popen(
            [firecracker_bin, "--api-sock", str(api_socket)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(run_dir),
        )

        runtime_step = "wait_api_socket"
        _wait_for_path(api_socket, settings.code_eval_microvm_firecracker_api_timeout_seconds)

        runtime_step = "snapshot_load"
        load_payload = {
            "snapshot_path": snapshot_vmstate,
            "mem_backend": {
                "backend_path": snapshot_mem,
                "backend_type": "File",
            },
            "enable_diff_snapshots": False,
            "resume_vm": True,
            "vsock_override": {
                "uds_path": str(vsock_proxy_socket),
            },
        }
        status, body_text = _firecracker_api_request(
            api_socket,
            "PUT",
            "/snapshot/load",
            load_payload,
            timeout_seconds=settings.code_eval_microvm_firecracker_api_timeout_seconds,
        )
        if status not in {200, 204}:
            override_not_supported = status == 400 and "vsock_override" in body_text
            if not override_not_supported:
                raise RuntimeError(
                    f"Firecracker snapshot load failed: status={status} body={body_text}"
                )

            vsock_override_supported = False
            active_vsock_socket = fallback_vsock_socket
            load_payload = {
                "snapshot_path": snapshot_vmstate,
                "mem_backend": {
                    "backend_path": snapshot_mem,
                    "backend_type": "File",
                },
                "enable_diff_snapshots": False,
                "resume_vm": True,
            }
            status, body_text = _firecracker_api_request(
                api_socket,
                "PUT",
                "/snapshot/load",
                load_payload,
                timeout_seconds=settings.code_eval_microvm_firecracker_api_timeout_seconds,
            )
            if status not in {200, 204}:
                raise RuntimeError(
                    f"Firecracker snapshot load failed (fallback mode): status={status} body={body_text}"
                )

        envelope = {
            "protocol_version": "v1",
            "stage": stage,
            "comparison_mode": comparison_mode,
            "shim_used": shim_used,
            "shim_source": shim_source,
            "request": request.model_dump(mode="json"),
        }

        connect_timeout_seconds = max(
            settings.code_eval_microvm_vsock_connect_timeout_seconds,
            1.0,
        )
        response_timeout_seconds = max(
            request.quota.timeout_seconds,
            settings.code_eval_microvm_vsock_connect_timeout_seconds,
        )
        runtime_step = "wait_vsock_proxy_socket"
        _wait_for_path(active_vsock_socket, settings.code_eval_microvm_firecracker_api_timeout_seconds)

        runtime_step = "vsock_connect_handshake"
        with _connect_guest_vsock_proxy_with_retry(
            active_vsock_socket,
            int(settings.code_eval_microvm_vsock_port),
            total_timeout_seconds=connect_timeout_seconds,
        ) as vsock:
            vsock.settimeout(response_timeout_seconds)
            runtime_step = "vsock_send_request"
            _send_frame(vsock, envelope)
            runtime_step = "vsock_receive_response"
            response = _recv_frame(vsock)

        runtime_step = "validate_guest_response"

        passed_raw = response.get("passed")
        score_raw = response.get("score", 0.0)
        exit_code_raw = response.get("exit_code")

        if not isinstance(passed_raw, bool):
            raise RuntimeError("Guest agent response must include boolean field 'passed'.")

        try:
            score = float(score_raw)
        except Exception as exc:
            raise RuntimeError("Guest agent response field 'score' must be numeric.") from exc

        exit_code: int | None = None
        if exit_code_raw is not None:
            try:
                exit_code = int(exit_code_raw)
            except Exception as exc:
                raise RuntimeError(
                    "Guest agent response field 'exit_code' must be integer or null."
                ) from exc

        stdout = str(response.get("stdout") or "")
        stderr = str(response.get("stderr") or "")
        guest_artifacts = response.get("artifacts")
        if guest_artifacts is None or not isinstance(guest_artifacts, dict):
            guest_artifacts = {}

        return AttemptResult(
            stage=stage,
            passed=passed_raw,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            score=score,
            shim_used=shim_used,
            shim_source=shim_source,
        ), {
            "executor": "microvm_adapter",
            "adapter_ready": True,
            "adapter_enabled": True,
            "runtime_mode": runtime_mode,
            "comparison_mode": comparison_mode,
            "shim_used": shim_used,
            "shim_source": shim_source,
            "reason": "firecracker_vsock_executed",
            "requested_runtime": request.environment.runtime,
            "freeze_key": request.environment.freeze_key,
            "network_requested": request.quota.network_enabled,
            "firecracker": {
                "api_socket": str(api_socket),
                "snapshot_vmstate_path": snapshot_vmstate,
                "snapshot_mem_path": snapshot_mem,
                "runtime_lock": str(serial_lock_path),
                "vsock_guest_cid": int(settings.code_eval_microvm_vsock_guest_cid),
                "vsock_port": int(settings.code_eval_microvm_vsock_port),
                "vsock_proxy_socket": str(active_vsock_socket),
                "vsock_override_supported": vsock_override_supported,
            },
            "guest_artifacts": guest_artifacts,
            "guest_response": {
                "passed": passed_raw,
                "score": score,
                "exit_code": exit_code,
            },
        }

    except Exception as exc:
        return _runtime_error(
            stage=stage,
            shim_used=shim_used,
            shim_source=shim_source,
            runtime_mode=runtime_mode,
            reason="firecracker_runtime_error",
            exit_code=21,
            stderr=f"Firecracker snapshot/vsock execution failed at step={runtime_step}: {exc}",
            request=request,
            comparison_mode=comparison_mode,
            extra={
                "firecracker": {
                    "api_socket": str(api_socket),
                    "snapshot_vmstate_path": snapshot_vmstate,
                    "snapshot_mem_path": snapshot_mem,
                    "runtime_lock": str(serial_lock_path),
                },
                "firecracker_preflight": preflight,
            },
        )
    finally:
        firecracker_stderr = _terminate_process(proc)
        try:
            if api_socket.exists():
                api_socket.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            if run_dir.exists():
                for item in run_dir.iterdir():
                    if item.is_file():
                        item.unlink(missing_ok=True)
                run_dir.rmdir()
        except Exception:
            pass

        if firecracker_stderr:
            stderr_path = run_dir.parent / f"{run_id}.firecracker.stderr.log"
            try:
                stderr_path.parent.mkdir(parents=True, exist_ok=True)
                with stderr_path.open("w", encoding="utf-8") as fh:
                    fh.write(firecracker_stderr)
            except Exception:
                pass

        _release_serial_lock(serial_lock_fd, serial_lock_path)
