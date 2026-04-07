"""Code evaluator phase-1 APIs: environment versions, approvals, and job lifecycle."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import (
    Assignment,
    Submission,
    CodeEvalApprovalRecord,
    CodeEvalApprovalArtifactType,
    CodeEvalApprovalStatus,
    CodeEvalEnvironmentReuseMode,
    CodeEvalEnvironmentStatus,
    CodeEvalEnvironmentVersion,
    CodeEvalJob,
    CodeEvalJobStatus,
    CodeEvalRegradePolicy,
    CodeEvalAttempt,
)
from app.schemas import (
    CodeEvalApprovalCreate,
    CodeEvalApprovalDecision,
    CodeEvalApprovalOut,
    CodeEvalEnvironmentBuildOut,
    CodeEvalEnvironmentBuildRequest,
    CodeEvalEnvironmentPublishValidationOut,
    CodeEvalRuntimeStatusOut,
    CodeEvalEnvironmentVersionCreate,
    CodeEvalEnvironmentVersionOut,
    CodeEvalJobCreate,
    CodeEvalJobDetailOut,
    CodeEvalJobOut,
)
from app.services.code_eval.contracts import (
    CodeEvalJobRequest,
    QualityRubricSourceMode,
    RegradePolicy,
    TestAuthoringMode,
)
from app.services.code_eval.firecracker_runtime import collect_firecracker_preflight

router = APIRouter(prefix="/code-eval", tags=["code-eval"])
settings = get_settings()


def _microvm_runtime_mode() -> str:
    return settings.code_eval_microvm_runtime_mode.strip().lower()


def _is_microvm_pilot_mode() -> bool:
    return (
        settings.code_eval_execution_backend.strip().lower() == "microvm"
        and _microvm_runtime_mode() in {"pilot_local", "pilot_docker"}
    )


def _latest_approved_artifact(
    db: Session,
    assignment_id: str,
    artifact_type: CodeEvalApprovalArtifactType,
) -> CodeEvalApprovalRecord | None:
    return (
        db.query(CodeEvalApprovalRecord)
        .filter(
            CodeEvalApprovalRecord.assignment_id == assignment_id,
            CodeEvalApprovalRecord.artifact_type == artifact_type,
            CodeEvalApprovalRecord.status == CodeEvalApprovalStatus.approved,
        )
        .order_by(CodeEvalApprovalRecord.version_number.desc())
        .first()
    )


def _validate_ai_testcase_coverage(content_json: dict | None) -> None:
    tests = []
    if isinstance(content_json, dict):
        tests = content_json.get("tests") or []
    if not isinstance(tests, list):
        tests = []

    covered: set[str] = set()
    for test in tests:
        if not isinstance(test, dict):
            continue
        labels = [
            test.get("class"),
            test.get("category"),
            test.get("name"),
            test.get("type"),
        ]
        normalized = [str(label).strip().lower() for label in labels if label]
        if any("happy" in label for label in normalized):
            covered.add("happy_path")
        if any("edge" in label for label in normalized):
            covered.add("edge_case")
        if any("invalid" in label for label in normalized):
            covered.add("invalid_input")

    required = {"happy_path", "edge_case", "invalid_input"}
    missing = sorted(required - covered)
    if missing:
        raise HTTPException(
            status_code=422,
            detail=(
                "ai_tests approval requires minimum testcase class coverage: "
                f"missing {', '.join(missing)}"
            ),
        )


def _microvm_pilot_policy_checks(spec_json: dict | None) -> dict[str, bool]:
    checks = {
        "microvm_policy_present": False,
        "microvm_policy_allow_pilot_runtime": False,
        "microvm_policy_approved_by_present": False,
    }

    spec = spec_json if isinstance(spec_json, dict) else {}
    policy = spec.get("microvm_policy")
    if not isinstance(policy, dict):
        return checks

    checks["microvm_policy_present"] = True
    checks["microvm_policy_allow_pilot_runtime"] = bool(policy.get("allow_pilot_runtime"))
    approved_by = policy.get("approved_by")
    checks["microvm_policy_approved_by_present"] = bool(
        isinstance(approved_by, str) and approved_by.strip()
    )
    return checks


def _validate_microvm_pilot_policy(env_version: CodeEvalEnvironmentVersion) -> None:
    if not _is_microvm_pilot_mode():
        return

    checks = _microvm_pilot_policy_checks(env_version.spec_json)
    missing: list[str] = []
    if not checks["microvm_policy_present"]:
        missing.append("microvm_policy")
    if not checks["microvm_policy_allow_pilot_runtime"]:
        missing.append("allow_pilot_runtime=true")
    if not checks["microvm_policy_approved_by_present"]:
        missing.append("approved_by")

    if missing:
        raise HTTPException(
            status_code=422,
            detail=(
                "Environment is not approved for microVM pilot execution. "
                f"Missing policy fields: {', '.join(missing)}"
            ),
        )


def _validate_microvm_pilot_docker_image_preflight(
    env_version: CodeEvalEnvironmentVersion,
    request: CodeEvalJobRequest,
) -> None:
    if not _is_microvm_pilot_mode() or _microvm_runtime_mode() != "pilot_docker":
        return

    image_from_request = (request.environment.image_reference or "").strip()
    spec = env_version.spec_json if isinstance(env_version.spec_json, dict) else {}
    image_from_env_spec = str(spec.get("image_reference") or "").strip()

    if image_from_request or image_from_env_spec:
        return

    raise HTTPException(
        status_code=422,
        detail=(
            "pilot_docker mode requires an explicit image reference. "
            "Set request.environment.image_reference or environment spec_json.image_reference "
            "to avoid runtime pull failures from non-registry freeze keys."
        ),
    )


@router.get("/runtime/status", response_model=CodeEvalRuntimeStatusOut)
def code_eval_runtime_status():
    backend = settings.code_eval_execution_backend.strip().lower()
    runtime_mode = _microvm_runtime_mode()
    pilot_required = backend == "microvm" and runtime_mode in {"pilot_local", "pilot_docker"}
    firecracker_preflight = (
        collect_firecracker_preflight()
        if backend == "microvm" and runtime_mode == "firecracker_vsock"
        else None
    )
    return CodeEvalRuntimeStatusOut(
        execution_backend=backend,
        shim_retry_enabled=settings.code_eval_enable_shim_retry,
        ai_shim_generation_enabled=settings.code_eval_enable_ai_shim_generation,
        microvm={
            "enabled": settings.code_eval_microvm_enable_adapter,
            "force_no_network": settings.code_eval_microvm_force_no_network,
            "serial_lock_file": settings.code_eval_microvm_serial_lock_file,
            "runtime_mode": runtime_mode,
            "allow_fallback": settings.code_eval_microvm_allow_fallback,
            "fallback_backend": settings.code_eval_microvm_fallback_backend,
            "runtime_bridge_url_configured": bool(
                settings.code_eval_microvm_runtime_bridge_url.strip()
            ),
            "runtime_bridge_timeout_seconds": settings.code_eval_microvm_runtime_bridge_timeout_seconds,
            "environment_build_strategy": settings.code_eval_microvm_env_build_strategy,
            "firecracker_snapshot_configured": bool(
                settings.code_eval_microvm_snapshot_vmstate_path.strip()
                and settings.code_eval_microvm_snapshot_mem_path.strip()
            ),
            "firecracker_vsock_port": settings.code_eval_microvm_vsock_port,
            "firecracker_preflight_ready": bool(
                firecracker_preflight and firecracker_preflight.get("ready")
            ),
            "firecracker_preflight_issues": (
                firecracker_preflight.get("issues") if firecracker_preflight else []
            ),
            "pilot_policy_required": pilot_required,
            "pilot_policy_required_fields": (
                ["microvm_policy.allow_pilot_runtime=true", "microvm_policy.approved_by"]
                if pilot_required
                else []
            ),
        },
    )


@router.get("/runtime/preflight")
def code_eval_runtime_preflight():
    backend = settings.code_eval_execution_backend.strip().lower()
    runtime_mode = _microvm_runtime_mode()
    payload: dict[str, object] = {
        "execution_backend": backend,
        "microvm_runtime_mode": runtime_mode,
    }
    if backend == "microvm" and runtime_mode == "firecracker_vsock":
        payload["firecracker"] = collect_firecracker_preflight()
    return payload


@router.post("/environments/versions", response_model=CodeEvalEnvironmentVersionOut, status_code=201)
def create_environment_version(body: CodeEvalEnvironmentVersionCreate, db: Session = Depends(get_db)):
    if body.assignment_id:
        assignment = db.get(Assignment, body.assignment_id)
        if not assignment:
            raise HTTPException(404, "Assignment not found")
        if assignment.course_id != body.course_id:
            raise HTTPException(
                status_code=422,
                detail="assignment_id does not belong to the provided course_id",
            )
    elif body.reuse_mode == CodeEvalEnvironmentReuseMode.assignment_only:
        raise HTTPException(
            status_code=422,
            detail="assignment_only reuse mode requires assignment_id",
        )

    env_version = CodeEvalEnvironmentVersion(**body.model_dump())
    db.add(env_version)
    db.commit()
    db.refresh(env_version)
    return env_version


@router.get("/environments/versions", response_model=list[CodeEvalEnvironmentVersionOut])
def list_environment_versions(
    course_id: str | None = None,
    assignment_id: str | None = None,
    profile_key: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
):
    q = db.query(CodeEvalEnvironmentVersion)
    if course_id:
        q = q.filter(CodeEvalEnvironmentVersion.course_id == course_id)
    if assignment_id:
        q = q.filter(CodeEvalEnvironmentVersion.assignment_id == assignment_id)
    if profile_key:
        q = q.filter(CodeEvalEnvironmentVersion.profile_key == profile_key)
    if status:
        q = q.filter(CodeEvalEnvironmentVersion.status == status)
    return q.order_by(CodeEvalEnvironmentVersion.created_at.desc()).all()


@router.post(
    "/environments/versions/{environment_version_id}/build",
    response_model=CodeEvalEnvironmentBuildOut,
)
def build_environment_version(
    environment_version_id: str,
    body: CodeEvalEnvironmentBuildRequest,
    db: Session = Depends(get_db),
):
    env_version = db.get(CodeEvalEnvironmentVersion, environment_version_id)
    if not env_version:
        raise HTTPException(404, "Environment version not found")

    if env_version.status == CodeEvalEnvironmentStatus.building and not body.force_rebuild:
        raise HTTPException(409, "Environment build already in progress")

    started_at = datetime.now(timezone.utc).isoformat()
    starter = body.triggered_by or "system"
    log_line = (
        f"[{started_at}] Build requested via API by={starter} force_rebuild={body.force_rebuild}"
    )

    env_version.status = CodeEvalEnvironmentStatus.building
    env_version.build_logs = (
        f"{env_version.build_logs}\n{log_line}" if env_version.build_logs else log_line
    )
    if body.force_rebuild:
        env_version.freeze_key = None
    db.commit()
    db.refresh(env_version)

    from app.workers.code_eval_env_tasks import run_code_eval_environment_build_task

    run_code_eval_environment_build_task.delay(
        env_version.id,
        body.force_rebuild,
        body.triggered_by,
    )

    return CodeEvalEnvironmentBuildOut(environment_version=env_version)


@router.post(
    "/environments/versions/{environment_version_id}/validate-publish",
    response_model=CodeEvalEnvironmentPublishValidationOut,
)
def validate_environment_publish(
    environment_version_id: str,
    db: Session = Depends(get_db),
):
    env_version = db.get(CodeEvalEnvironmentVersion, environment_version_id)
    if not env_version:
        raise HTTPException(404, "Environment version not found")

    assignment_exists = True
    assignment_is_code = True
    if env_version.assignment_id:
        assignment = db.get(Assignment, env_version.assignment_id)
        assignment_exists = assignment is not None
        assignment_is_code = bool(assignment and assignment.has_code_question)

    checks = {
        "status_ready": env_version.status == CodeEvalEnvironmentStatus.ready,
        "freeze_key_present": bool(env_version.freeze_key),
        "is_active": bool(env_version.is_active),
        "assignment_exists_if_bound": assignment_exists,
        "assignment_is_code_if_bound": assignment_is_code,
    }

    if _is_microvm_pilot_mode():
        checks.update(_microvm_pilot_policy_checks(env_version.spec_json))

    missing = [name for name, ok in checks.items() if not ok]

    return CodeEvalEnvironmentPublishValidationOut(
        environment_version_id=env_version.id,
        ready_for_publish=not missing,
        checks=checks,
        missing=missing,
    )


@router.post("/approvals", response_model=CodeEvalApprovalOut, status_code=201)
def create_approval_record(body: CodeEvalApprovalCreate, db: Session = Depends(get_db)):
    assignment = db.get(Assignment, body.assignment_id)
    if not assignment:
        raise HTTPException(404, "Assignment not found")

    approval = CodeEvalApprovalRecord(**body.model_dump())
    db.add(approval)
    db.commit()
    db.refresh(approval)
    return approval


@router.post("/approvals/{approval_id}/approve", response_model=CodeEvalApprovalOut)
def approve_record(approval_id: str, body: CodeEvalApprovalDecision, db: Session = Depends(get_db)):
    approval = db.get(CodeEvalApprovalRecord, approval_id)
    if not approval:
        raise HTTPException(404, "Approval record not found")

    if approval.artifact_type == CodeEvalApprovalArtifactType.ai_tests:
        _validate_ai_testcase_coverage(approval.content_json)

    approval.status = CodeEvalApprovalStatus.approved
    approval.approved_by = body.actor
    approval.approved_at = datetime.now(timezone.utc)
    approval.rejected_reason = None
    db.commit()
    db.refresh(approval)
    return approval


@router.post("/approvals/{approval_id}/reject", response_model=CodeEvalApprovalOut)
def reject_record(approval_id: str, body: CodeEvalApprovalDecision, db: Session = Depends(get_db)):
    approval = db.get(CodeEvalApprovalRecord, approval_id)
    if not approval:
        raise HTTPException(404, "Approval record not found")

    approval.status = CodeEvalApprovalStatus.rejected
    approval.approved_by = body.actor
    approval.rejected_reason = body.reason or "Rejected by instructor"
    approval.approved_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(approval)
    return approval


@router.get("/approvals", response_model=list[CodeEvalApprovalOut])
def list_approval_records(
    assignment_id: str,
    db: Session = Depends(get_db),
):
    return (
        db.query(CodeEvalApprovalRecord)
        .filter(CodeEvalApprovalRecord.assignment_id == assignment_id)
        .order_by(CodeEvalApprovalRecord.created_at.desc())
        .all()
    )


@router.post("/jobs", response_model=CodeEvalJobOut, status_code=201)
def create_job(body: CodeEvalJobCreate, db: Session = Depends(get_db)):
    if body.environment_version_id is None:
        raise HTTPException(
            status_code=422,
            detail="environment_version_id is required for phase-1 persisted execution.",
        )

    request = body.request.model_copy(deep=True)
    if "quality_evaluation" not in request.model_fields_set:
        raise HTTPException(
            status_code=422,
            detail="quality_evaluation must be explicitly provided per assignment policy.",
        )

    assignment = db.get(Assignment, request.assignment_id)
    if not assignment:
        raise HTTPException(404, "Assignment not found")
    if not assignment.has_code_question:
        raise HTTPException(422, "Assignment is not configured as a code assignment")

    submission = db.get(Submission, request.submission_id)
    if not submission:
        raise HTTPException(404, "Submission not found")
    if submission.assignment_id != assignment.id:
        raise HTTPException(422, "submission_id does not belong to assignment_id")

    env_version = db.get(CodeEvalEnvironmentVersion, body.environment_version_id)
    if not env_version:
        raise HTTPException(404, "Environment version not found")
    if env_version.course_id != assignment.course_id:
        raise HTTPException(422, "Environment version course does not match assignment course")
    if env_version.assignment_id and env_version.assignment_id != assignment.id:
        raise HTTPException(422, "Environment version assignment does not match target assignment")
    if not env_version.is_active:
        raise HTTPException(409, "Environment version is inactive")
    if env_version.status != CodeEvalEnvironmentStatus.ready:
        raise HTTPException(
            status_code=409,
            detail="Environment version is not ready. Build/freeze must complete before job creation.",
        )
    if not env_version.freeze_key:
        raise HTTPException(
            status_code=409,
            detail="Environment version has no freeze_key. Run environment build before job creation.",
        )

    # Bind immutable environment artifacts from the selected version into the
    # runtime request so worker execution always uses the published freeze.
    request.environment.freeze_key = env_version.freeze_key
    spec_json = env_version.spec_json if isinstance(env_version.spec_json, dict) else {}
    if not request.environment.image_reference:
        image_reference = str(spec_json.get("image_reference") or "").strip()
        if image_reference:
            request.environment.image_reference = image_reference
    snapshot_vmstate = str(spec_json.get("snapshot_vmstate_path") or "").strip()
    snapshot_mem = str(spec_json.get("snapshot_mem_path") or "").strip()
    if snapshot_vmstate:
        request.environment.snapshot_vmstate_path = snapshot_vmstate
    if snapshot_mem:
        request.environment.snapshot_mem_path = snapshot_mem
    snapshot_vmstate_sha = str(spec_json.get("snapshot_vmstate_sha256") or "").strip()
    snapshot_mem_sha = str(spec_json.get("snapshot_mem_sha256") or "").strip()
    if snapshot_vmstate_sha:
        request.environment.snapshot_vmstate_sha256 = snapshot_vmstate_sha
    if snapshot_mem_sha:
        request.environment.snapshot_mem_sha256 = snapshot_mem_sha

    _validate_microvm_pilot_policy(env_version)
    _validate_microvm_pilot_docker_image_preflight(env_version, request)

    if request.regrade_policy == RegradePolicy.NEW_ONLY_UNLESS_EXPLICIT and not body.explicit_regrade:
        prior_completed_job = (
            db.query(CodeEvalJob)
            .filter(
                CodeEvalJob.submission_id == request.submission_id,
                CodeEvalJob.status == CodeEvalJobStatus.COMPLETED,
            )
            .first()
        )
        if prior_completed_job:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Submission already has a completed code-eval job. "
                    "Explicit regrade is required for reprocessing under the current policy."
                ),
            )

    if request.test_authoring is not None:
        mode = request.test_authoring.mode
        if mode == TestAuthoringMode.QUESTION_AND_SOLUTION_TO_TESTS:
            tests_approval = _latest_approved_artifact(
                db,
                request.assignment_id,
                CodeEvalApprovalArtifactType.ai_tests,
            )
            if tests_approval is None:
                raise HTTPException(
                    status_code=422,
                    detail="Approved ai_tests artifact is required for selected test authoring mode.",
                )
        elif mode == TestAuthoringMode.QUESTION_TO_SOLUTION_AND_TESTS:
            solution_approval = _latest_approved_artifact(
                db,
                request.assignment_id,
                CodeEvalApprovalArtifactType.ai_solution,
            )
            tests_approval = _latest_approved_artifact(
                db,
                request.assignment_id,
                CodeEvalApprovalArtifactType.ai_tests,
            )
            missing = []
            if solution_approval is None:
                missing.append("ai_solution")
            if tests_approval is None:
                missing.append("ai_tests")
            if missing:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "Approved artifacts are required for selected test authoring mode: "
                        + ", ".join(missing)
                    ),
                )

    if (
        request.quality_evaluation.rubric_source_mode
        == QualityRubricSourceMode.AI_GENERATED_WITH_APPROVAL
    ):
        rubric_approval = _latest_approved_artifact(
            db,
            request.assignment_id,
            CodeEvalApprovalArtifactType.ai_quality_rubric,
        )
        if rubric_approval is None:
            raise HTTPException(
                status_code=422,
                detail="Approved ai_quality_rubric artifact is required for AI-generated quality rubric mode.",
            )

    regrade_policy = CodeEvalRegradePolicy(request.regrade_policy.value)
    job = CodeEvalJob(
        assignment_id=request.assignment_id,
        submission_id=request.submission_id,
        environment_version_id=env_version.id,
        language=request.language.value,
        entrypoint=request.entrypoint,
        request_json=request.model_dump(mode="json"),
        quality_config_json=request.quality_evaluation.model_dump(mode="json"),
        regrade_policy=regrade_policy,
        explicit_regrade=body.explicit_regrade,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    from app.workers.code_eval_tasks import run_code_eval_job_task

    run_code_eval_job_task.delay(job.id)
    return job


@router.get("/jobs", response_model=list[CodeEvalJobOut])
def list_jobs(
    assignment_id: str | None = None,
    submission_id: str | None = None,
    status: CodeEvalJobStatus | None = None,
    db: Session = Depends(get_db),
):
    q = db.query(CodeEvalJob)
    if assignment_id:
        q = q.filter(CodeEvalJob.assignment_id == assignment_id)
    if submission_id:
        q = q.filter(CodeEvalJob.submission_id == submission_id)
    if status:
        q = q.filter(CodeEvalJob.status == status)
    return q.order_by(CodeEvalJob.created_at.desc()).all()


@router.get("/jobs/{job_id}", response_model=CodeEvalJobDetailOut)
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.get(CodeEvalJob, job_id)
    if not job:
        raise HTTPException(404, "Code-eval job not found")

    attempts = (
        db.query(CodeEvalAttempt)
        .filter(CodeEvalAttempt.job_id == job_id)
        .order_by(CodeEvalAttempt.attempt_index.asc())
        .all()
    )

    return CodeEvalJobDetailOut(
        **CodeEvalJobOut.model_validate(job).model_dump(),
        attempts=attempts,
    )
