"""Environment freeze/build orchestration tasks for code-eval environment versions."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone

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


def _validate_and_resolve_freeze_key(env: CodeEvalEnvironmentVersion) -> tuple[str, str]:
    mode = str((env.spec_json or {}).get("mode") or "manifest").strip().lower()

    if mode == "image_reference":
        image_reference = str((env.spec_json or {}).get("image_reference") or "").strip()
        if not image_reference:
            raise ValueError("image_reference mode requires spec_json.image_reference")

        if settings.code_eval_docker_auto_pull:
            import docker

            client = docker.from_env()
            client.ping()
            client.images.pull(image_reference)

        return image_reference, f"Validated image reference mode using image={image_reference}"

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
        return freeze_key, f"Computed deterministic freeze key for mode={mode}: {freeze_key}"

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

        freeze_key, detail = _validate_and_resolve_freeze_key(env)

        env.freeze_key = freeze_key
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
