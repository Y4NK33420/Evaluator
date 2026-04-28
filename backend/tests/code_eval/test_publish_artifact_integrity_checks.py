"""Unit tests for environment publish artifact integrity checks."""

import hashlib

from app.api.v1.code_eval import _environment_artifact_integrity_checks
from app.models import CodeEvalEnvironmentReuseMode, CodeEvalEnvironmentStatus, CodeEvalEnvironmentVersion


def _env(spec_json: dict, freeze_key: str) -> CodeEvalEnvironmentVersion:
    return CodeEvalEnvironmentVersion(
        course_id="course-1",
        assignment_id=None,
        profile_key="python-basic",
        reuse_mode=CodeEvalEnvironmentReuseMode.course_reuse_with_assignment_overrides,
        spec_json=spec_json,
        freeze_key=freeze_key,
        status=CodeEvalEnvironmentStatus.ready,
        version_number=1,
        is_active=True,
        created_by="test",
    )


def test_non_snapshot_env_passes_integrity_gate():
    env = _env(
        spec_json={"mode": "manifest", "runtime": "python-3.11"},
        freeze_key="codeeval/course-1/course/python-basic:v1-abc123",
    )

    checks = _environment_artifact_integrity_checks(env)

    assert checks["artifact_integrity_checks_passed"] is True


def test_snapshot_env_missing_checksums_fails(tmp_path):
    vmstate = tmp_path / "python311.vmstate"
    mem = tmp_path / "python311.mem"
    vmstate.write_bytes(b"vmstate")
    mem.write_bytes(b"mem")

    env = _env(
        spec_json={
            "mode": "manifest",
            "snapshot_vmstate_path": str(vmstate),
            "snapshot_mem_path": str(mem),
        },
        freeze_key="firecracker/course-1/course/python-basic:v1-deadbeef",
    )

    checks = _environment_artifact_integrity_checks(env)

    assert checks["artifact_integrity_checks_passed"] is False
    assert checks["snapshot_vmstate_sha256_present"] is False
    assert checks["snapshot_mem_sha256_present"] is False


def test_snapshot_env_checksum_match_passes(tmp_path):
    vmstate = tmp_path / "python311.vmstate"
    mem = tmp_path / "python311.mem"
    vmstate.write_bytes(b"vmstate")
    mem.write_bytes(b"mem")

    vmstate_sha = hashlib.sha256(vmstate.read_bytes()).hexdigest()
    mem_sha = hashlib.sha256(mem.read_bytes()).hexdigest()

    env = _env(
        spec_json={
            "mode": "manifest",
            "snapshot_vmstate_path": str(vmstate),
            "snapshot_mem_path": str(mem),
            "snapshot_vmstate_sha256": vmstate_sha,
            "snapshot_mem_sha256": mem_sha,
        },
        freeze_key="firecracker/course-1/course/python-basic:v1-feedbeef",
    )

    checks = _environment_artifact_integrity_checks(env)

    assert checks["artifact_integrity_checks_passed"] is True
    assert checks["snapshot_vmstate_sha256_matches"] is True
    assert checks["snapshot_mem_sha256_matches"] is True
