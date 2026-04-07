"""Environment freeze/build orchestration tasks for code-eval environment versions."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.models import CodeEvalEnvironmentStatus, CodeEvalEnvironmentVersion
from app.workers.celery_app import celery_app

log = logging.getLogger(__name__)
settings = get_settings()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_log(existing: str | None, line: str) -> str:
    prefix = (existing or "").strip()
    if prefix:
        return f"{prefix}\n{line}"
    return line


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _validate_existing_snapshot_artifacts(
    env: CodeEvalEnvironmentVersion,
    *,
    vmstate_path: Path,
    mem_path: Path,
) -> tuple[str, str, dict]:
    if not vmstate_path.exists():
        raise ValueError(f"snapshot vmstate artifact does not exist: {vmstate_path}")
    if not mem_path.exists():
        raise ValueError(f"snapshot memory artifact does not exist: {mem_path}")

    vmstate_sha = _sha256_file(vmstate_path)
    mem_sha = _sha256_file(mem_path)
    combined = hashlib.sha256(f"{vmstate_sha}:{mem_sha}".encode("utf-8")).hexdigest()[:16]
    scope = env.assignment_id or "course"
    freeze_key = (
        f"firecracker/{env.course_id}/{scope}/{env.profile_key}:"
        f"v{env.version_number}-{combined}"
    )
    detail = (
        "Validated snapshot artifacts and computed freeze key "
        f"(vmstate_sha256={vmstate_sha[:12]}..., mem_sha256={mem_sha[:12]}...)."
    )
    spec_updates = {
        "snapshot_vmstate_path": str(vmstate_path),
        "snapshot_mem_path": str(mem_path),
        "snapshot_vmstate_sha256": vmstate_sha,
        "snapshot_mem_sha256": mem_sha,
    }
    return freeze_key, detail, spec_updates


def _build_snapshot_with_script(env: CodeEvalEnvironmentVersion) -> tuple[Path, Path, str]:
    script_raw = str((env.spec_json or {}).get("snapshot_build_script") or "").strip()
    script_path = Path(script_raw or settings.code_eval_microvm_env_build_script).resolve()
    if not script_path.exists():
        raise ValueError(f"Snapshot build script not found: {script_path}")

    snapshot_dir = Path(
        str((env.spec_json or {}).get("snapshot_dir") or settings.code_eval_microvm_env_build_snapshot_dir)
    ).resolve()
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    name_prefix = str(settings.code_eval_microvm_env_build_snapshot_name_prefix or "codeeval").strip()
    snapshot_name = f"{name_prefix}-{env.id[:8]}-v{env.version_number}"
    vmstate = snapshot_dir / f"{snapshot_name}.vmstate"
    mem = snapshot_dir / f"{snapshot_name}.mem"

    env_vars = os.environ.copy()
    env_vars["SNAPSHOT_DIR"] = str(snapshot_dir)
    env_vars["SNAPSHOT_NAME"] = snapshot_name

    completed = subprocess.run(
        [str(script_path)],
        env=env_vars,
        text=True,
        capture_output=True,
        timeout=1800,
        check=False,
    )
    if completed.returncode != 0:
        stderr = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(
            f"Snapshot build script failed (exit={completed.returncode}): {stderr[:2000]}"
        )

    return vmstate, mem, f"Snapshot build script completed via {script_path}"


def _validate_and_resolve_freeze_key(env: CodeEvalEnvironmentVersion) -> tuple[str, str, dict]:
    mode = str((env.spec_json or {}).get("mode") or "manifest").strip().lower()
    strategy = settings.code_eval_microvm_env_build_strategy.strip().lower()

    if mode == "image_reference":
        image_reference = str((env.spec_json or {}).get("image_reference") or "").strip()
        if not image_reference:
            raise ValueError("image_reference mode requires spec_json.image_reference")

        if settings.code_eval_docker_auto_pull:
            import docker

            client = docker.from_env()
            client.ping()
            client.images.pull(image_reference)

        return image_reference, f"Validated image reference mode using image={image_reference}", {}

    if mode in {"manifest", "lockfile"} and strategy == "firecracker_snapshot":
        vmstate, mem, detail = _build_snapshot_with_script(env)
        freeze_key, freeze_detail, spec_updates = _validate_existing_snapshot_artifacts(
            env,
            vmstate_path=vmstate,
            mem_path=mem,
        )
        return freeze_key, f"{detail}. {freeze_detail}", spec_updates

    if mode in {"manifest", "lockfile"} and strategy == "snapshot_validate":
        vmstate_raw = str((env.spec_json or {}).get("snapshot_vmstate_path") or "").strip()
        mem_raw = str((env.spec_json or {}).get("snapshot_mem_path") or "").strip()
        if not vmstate_raw or not mem_raw:
            raise ValueError(
                "snapshot_validate strategy requires spec_json.snapshot_vmstate_path and spec_json.snapshot_mem_path"
            )
        return _validate_existing_snapshot_artifacts(
            env,
            vmstate_path=Path(vmstate_raw).resolve(),
            mem_path=Path(mem_raw).resolve(),
        )

    if mode in {"manifest", "lockfile"}:
        canonical = {
            "course_id": env.course_id,
            "assignment_id": env.assignment_id,
            "profile_key": env.profile_key,
            "version_number": env.version_number,
            "spec_json": env.spec_json,
        }
        payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
        scope = env.assignment_id or "course"
        freeze_key = f"codeeval/{env.course_id}/{scope}/{env.profile_key}:v{env.version_number}-{digest}"
        detail = (
            "Computed deterministic freeze key "
            f"for mode={mode} strategy={strategy}: {freeze_key}"
        )
        return freeze_key, detail, {}

    raise ValueError(f"Unsupported environment spec mode: {mode}")


@celery_app.task(
    name="app.workers.code_eval_env_tasks.run_code_eval_environment_build_task",
    bind=True,
    max_retries=0,
)
def run_code_eval_environment_build_task(
    self,
    environment_version_id: str,
    force_rebuild: bool = False,
    triggered_by: str | None = None,
):
    """Build/freeze one environment version and persist freeze metadata."""
    db: Session = SessionLocal()
    try:
        env = db.get(CodeEvalEnvironmentVersion, environment_version_id)
        if env is None:
            log.error("Code-eval environment version %s not found", environment_version_id)
            return

        env.status = CodeEvalEnvironmentStatus.building
        env.build_logs = _append_log(
            env.build_logs,
            f"[{_now_iso()}] Build started. force_rebuild={force_rebuild} triggered_by={triggered_by or 'system'}",
        )
        if force_rebuild:
            env.freeze_key = None
        db.commit()

        freeze_key, detail, spec_updates = _validate_and_resolve_freeze_key(env)

        env.freeze_key = freeze_key
        if spec_updates:
            spec_json = dict(env.spec_json or {})
            spec_json.update(spec_updates)
            env.spec_json = spec_json
        env.status = CodeEvalEnvironmentStatus.ready
        env.build_logs = _append_log(env.build_logs, f"[{_now_iso()}] {detail}")
        env.build_logs = _append_log(env.build_logs, f"[{_now_iso()}] Build completed successfully.")
        db.commit()

        log.info(
            "Environment build completed for %s (freeze_key=%s)",
            environment_version_id,
            freeze_key,
        )

    except Exception as exc:
        db.rollback()
        log.exception("Environment build failed for %s: %s", environment_version_id, exc)
        try:
            env = db.get(CodeEvalEnvironmentVersion, environment_version_id)
            if env is not None:
                env.status = CodeEvalEnvironmentStatus.failed
                env.build_logs = _append_log(
                    env.build_logs,
                    f"[{_now_iso()}] Build failed: {exc}",
                )
                db.commit()
        except Exception:
            db.rollback()
            log.exception("Failed to persist failed state for %s", environment_version_id)
    finally:
        db.close()
