"""MicroVM execution adapter boundary.

This module defines a stable adapter interface for future Firecracker/snapshot
integration while allowing current pipelines to run through controlled fallback
backends.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.config import get_settings
from app.services.code_eval.contracts import AttemptResult, CodeEvalJobRequest
from app.services.code_eval.firecracker_runtime import execute_firecracker_vsock_backend

settings = get_settings()


def _runtime_bridge_headers() -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    api_key = settings.code_eval_microvm_runtime_bridge_api_key.strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _runtime_bridge_error(
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
    bridge_status_code: int | None = None,
) -> tuple[AttemptResult, dict[str, Any]]:
    return AttemptResult(
        stage=stage,
        passed=False,
        exit_code=exit_code,
        stderr=stderr,
        score=0.0,
        shim_used=shim_used,
        shim_source=shim_source,
    ), {
        "executor": "microvm_adapter",
        "adapter_ready": False,
        "adapter_enabled": True,
        "runtime_mode": runtime_mode,
        "comparison_mode": comparison_mode,
        "shim_used": shim_used,
        "shim_source": shim_source,
        "reason": reason,
        "requested_runtime": request.environment.runtime,
        "freeze_key": request.environment.freeze_key,
        "network_requested": request.quota.network_enabled,
        "bridge_url": settings.code_eval_microvm_runtime_bridge_url,
        "bridge_status_code": bridge_status_code,
    }


def _execute_runtime_bridge(
    request: CodeEvalJobRequest,
    *,
    stage: str,
    comparison_mode: str,
    shim_used: bool,
    shim_source: str | None,
    runtime_mode: str,
) -> tuple[AttemptResult, dict[str, Any]]:
    bridge_url = settings.code_eval_microvm_runtime_bridge_url.strip()
    if not bridge_url:
        return _runtime_bridge_error(
            stage=stage,
            shim_used=shim_used,
            shim_source=shim_source,
            runtime_mode=runtime_mode,
            reason="runtime_bridge_not_configured",
            exit_code=14,
            stderr=(
                "MicroVM runtime bridge URL is not configured. "
                "Set CODE_EVAL_MICROVM_RUNTIME_BRIDGE_URL for runtime_bridge mode."
            ),
            request=request,
            comparison_mode=comparison_mode,
        )

    payload = {
        "stage": stage,
        "comparison_mode": comparison_mode,
        "shim_used": shim_used,
        "shim_source": shim_source,
        "request": request.model_dump(mode="json"),
    }

    try:
        with httpx.Client(
            timeout=float(settings.code_eval_microvm_runtime_bridge_timeout_seconds),
            verify=bool(settings.code_eval_microvm_runtime_bridge_verify_tls),
        ) as client:
            response = client.post(
                bridge_url,
                headers=_runtime_bridge_headers(),
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
    except httpx.HTTPStatusError as exc:
        return _runtime_bridge_error(
            stage=stage,
            shim_used=shim_used,
            shim_source=shim_source,
            runtime_mode=runtime_mode,
            reason="runtime_bridge_http_error",
            exit_code=15,
            stderr=(
                "MicroVM runtime bridge returned HTTP error: "
                f"status={exc.response.status_code} body={exc.response.text}"
            ),
            request=request,
            comparison_mode=comparison_mode,
            bridge_status_code=exc.response.status_code,
        )
    except Exception as exc:
        return _runtime_bridge_error(
            stage=stage,
            shim_used=shim_used,
            shim_source=shim_source,
            runtime_mode=runtime_mode,
            reason="runtime_bridge_unreachable",
            exit_code=15,
            stderr=f"MicroVM runtime bridge request failed: {exc}",
            request=request,
            comparison_mode=comparison_mode,
        )

    if not isinstance(body, dict):
        return _runtime_bridge_error(
            stage=stage,
            shim_used=shim_used,
            shim_source=shim_source,
            runtime_mode=runtime_mode,
            reason="runtime_bridge_invalid_response",
            exit_code=16,
            stderr="MicroVM runtime bridge response must be a JSON object.",
            request=request,
            comparison_mode=comparison_mode,
        )

    passed_raw = body.get("passed")
    score_raw = body.get("score", 0.0)
    exit_code_raw = body.get("exit_code")

    if not isinstance(passed_raw, bool):
        return _runtime_bridge_error(
            stage=stage,
            shim_used=shim_used,
            shim_source=shim_source,
            runtime_mode=runtime_mode,
            reason="runtime_bridge_invalid_response",
            exit_code=16,
            stderr="MicroVM runtime bridge response must include boolean field 'passed'.",
            request=request,
            comparison_mode=comparison_mode,
        )

    try:
        score = float(score_raw)
    except Exception:
        return _runtime_bridge_error(
            stage=stage,
            shim_used=shim_used,
            shim_source=shim_source,
            runtime_mode=runtime_mode,
            reason="runtime_bridge_invalid_response",
            exit_code=16,
            stderr="MicroVM runtime bridge response field 'score' must be numeric.",
            request=request,
            comparison_mode=comparison_mode,
        )

    exit_code: int | None = None
    if exit_code_raw is not None:
        try:
            exit_code = int(exit_code_raw)
        except Exception:
            return _runtime_bridge_error(
                stage=stage,
                shim_used=shim_used,
                shim_source=shim_source,
                runtime_mode=runtime_mode,
                reason="runtime_bridge_invalid_response",
                exit_code=16,
                stderr="MicroVM runtime bridge response field 'exit_code' must be integer or null.",
                request=request,
                comparison_mode=comparison_mode,
            )

    stdout = body.get("stdout") or ""
    stderr = body.get("stderr") or ""
    artifacts = body.get("artifacts")
    if artifacts is None or not isinstance(artifacts, dict):
        artifacts = {}

    return AttemptResult(
        stage=stage,
        passed=passed_raw,
        exit_code=exit_code,
        stdout=str(stdout),
        stderr=str(stderr),
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
        "reason": "runtime_bridge_executed",
        "requested_runtime": request.environment.runtime,
        "freeze_key": request.environment.freeze_key,
        "network_requested": request.quota.network_enabled,
        "bridge_url": bridge_url,
        "bridge_artifacts": artifacts,
        "bridge_response": {
            "passed": passed_raw,
            "score": score,
            "exit_code": exit_code,
        },
    }


def execute_microvm_backend(
    request: CodeEvalJobRequest,
    *,
    stage: str,
    comparison_mode: str,
    shim_used: bool,
    shim_source: str | None,
) -> tuple[AttemptResult, dict[str, Any]]:
    """Attempt microVM execution via adapter boundary.

    Current behavior is intentionally non-executing until the Firecracker/vsock
    runtime integration is implemented.
    """
    runtime_mode = settings.code_eval_microvm_runtime_mode.strip().lower()

    if not settings.code_eval_microvm_enable_adapter:
        return AttemptResult(
            stage=stage,
            passed=False,
            exit_code=10,
            stderr=(
                "MicroVM adapter is disabled. "
                "Set CODE_EVAL_MICROVM_ENABLE_ADAPTER=true to enable adapter mode."
            ),
            score=0.0,
            shim_used=shim_used,
            shim_source=shim_source,
        ), {
            "executor": "microvm_adapter",
            "adapter_ready": False,
            "adapter_enabled": False,
            "runtime_mode": runtime_mode,
            "comparison_mode": comparison_mode,
            "shim_used": shim_used,
            "shim_source": shim_source,
            "reason": "adapter_disabled",
            "requested_runtime": request.environment.runtime,
            "freeze_key": request.environment.freeze_key,
            "network_requested": request.quota.network_enabled,
        }

    if runtime_mode in {"pilot_local", "pilot_docker"}:
        delegate_backend = "local" if runtime_mode == "pilot_local" else "docker"
        return AttemptResult(
            stage=stage,
            passed=False,
            exit_code=0,
            stderr="",
            score=0.0,
            shim_used=shim_used,
            shim_source=shim_source,
        ), {
            "executor": "microvm_adapter",
            "adapter_ready": True,
            "adapter_enabled": True,
            "runtime_mode": runtime_mode,
            "delegate_backend": delegate_backend,
            "comparison_mode": comparison_mode,
            "shim_used": shim_used,
            "shim_source": shim_source,
            "reason": "pilot_delegate_ready",
            "requested_runtime": request.environment.runtime,
            "freeze_key": request.environment.freeze_key,
            "network_requested": request.quota.network_enabled,
        }

    if runtime_mode == "runtime_bridge":
        return _execute_runtime_bridge(
            request,
            stage=stage,
            comparison_mode=comparison_mode,
            shim_used=shim_used,
            shim_source=shim_source,
            runtime_mode=runtime_mode,
        )

    if runtime_mode == "firecracker_vsock":
        return execute_firecracker_vsock_backend(
            request,
            stage=stage,
            comparison_mode=comparison_mode,
            shim_used=shim_used,
            shim_source=shim_source,
            runtime_mode=runtime_mode,
        )

    if runtime_mode not in {"pending", ""}:
        return AttemptResult(
            stage=stage,
            passed=False,
            exit_code=13,
            stderr=(
                "MicroVM adapter runtime mode is invalid. "
                f"Got '{settings.code_eval_microvm_runtime_mode}', expected one of: "
                "pending, pilot_local, pilot_docker, runtime_bridge, firecracker_vsock."
            ),
            score=0.0,
            shim_used=shim_used,
            shim_source=shim_source,
        ), {
            "executor": "microvm_adapter",
            "adapter_ready": False,
            "adapter_enabled": True,
            "runtime_mode": runtime_mode,
            "comparison_mode": comparison_mode,
            "shim_used": shim_used,
            "shim_source": shim_source,
            "reason": "invalid_runtime_mode",
            "requested_runtime": request.environment.runtime,
            "freeze_key": request.environment.freeze_key,
            "network_requested": request.quota.network_enabled,
        }

    return AttemptResult(
        stage=stage,
        passed=False,
        exit_code=11,
        stderr=(
            "MicroVM adapter boundary is enabled, but runtime execution integration "
            "is not implemented yet (snapshot manager/vsock guest agent pending)."
        ),
        score=0.0,
        shim_used=shim_used,
        shim_source=shim_source,
    ), {
        "executor": "microvm_adapter",
        "adapter_ready": False,
        "adapter_enabled": True,
        "runtime_mode": runtime_mode,
        "comparison_mode": comparison_mode,
        "shim_used": shim_used,
        "shim_source": shim_source,
        "reason": "runtime_integration_pending",
        "requested_runtime": request.environment.runtime,
        "freeze_key": request.environment.freeze_key,
        "network_requested": request.quota.network_enabled,
    }
