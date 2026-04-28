"""Pydantic request/response schemas."""

from datetime import datetime
from typing import Optional, Any
from pydantic import BaseModel, Field

from app.models import (
    QuestionType,
    SubmissionStatus,
    GradeSource,
    ClassroomStatus,
    RubricSource,
    CodeEvalApprovalArtifactType,
    CodeEvalApprovalStatus,
    CodeEvalEnvironmentReuseMode,
    CodeEvalEnvironmentStatus,
    CodeEvalJobStatus,
    CodeEvalRegradePolicy,
)
from app.services.code_eval.contracts import CodeEvalJobRequest


# ── Assignment ────────────────────────────────────────────────────────────────

class AssignmentCreate(BaseModel):
    course_id:         str
    classroom_id:      Optional[str] = None
    title:             str
    description:       Optional[str] = None
    authoring_prompt:  Optional[str] = None
    deadline:          Optional[datetime] = None
    max_marks:         float = 100.0
    question_type:     QuestionType = QuestionType.subjective
    has_code_question: bool = False


class AssignmentUpdate(BaseModel):
    title:             Optional[str] = None
    description:       Optional[str] = None
    authoring_prompt:  Optional[str] = None
    deadline:          Optional[datetime] = None
    max_marks:         Optional[float] = None
    question_type:     Optional[QuestionType] = None
    has_code_question: Optional[bool] = None


class AssignmentOut(BaseModel):
    model_config = {"from_attributes": True}
    id:                str
    course_id:         str
    classroom_id:      Optional[str]
    title:             str
    description:       Optional[str]
    authoring_prompt:  Optional[str]
    deadline:          Optional[datetime]
    max_marks:         float
    question_type:     QuestionType
    has_code_question: bool
    is_published:      bool
    published_at:      Optional[datetime]
    published_by:      Optional[str]
    published_environment_version_id: Optional[str]
    created_at:        datetime
    updated_at:        datetime


class AssignmentSummaryOut(AssignmentOut):
    """AssignmentOut enriched with computed submission/grade counts."""
    submission_count: int = 0
    graded_count:     int = 0
    released_count:   int = 0
    error_count:      int = 0


class AssignmentPublishValidationRequest(BaseModel):
    environment_version_id: Optional[str] = None


class AssignmentPublishValidationOut(BaseModel):
    assignment_id: str
    ready_for_publish: bool
    checks: dict[str, bool]
    missing: list[str] = Field(default_factory=list)
    environment_version_id: Optional[str] = None


class AssignmentPublishRequest(BaseModel):
    actor: Optional[str] = None
    environment_version_id: Optional[str] = None
    force_republish: bool = False


class AssignmentPublishOut(BaseModel):
    assignment: AssignmentOut
    validation: AssignmentPublishValidationOut


# ── Submission ────────────────────────────────────────────────────────────────

class SubmissionOut(BaseModel):
    model_config = {"from_attributes": True}
    id:            str
    assignment_id: str
    student_id:    str
    student_name:  Optional[str]
    status:        SubmissionStatus
    ocr_result:    Optional[dict]
    ocr_engine:    Optional[str]
    error_message: Optional[str]
    created_at:    datetime
    updated_at:    datetime
    # Enriched (computed from joined assignment)
    assignment_title:             Optional[str] = None
    assignment_max_marks:         Optional[float] = None
    assignment_has_code_question: Optional[bool] = None
    source_code:                  Optional[str] = None


# ── Rubric ────────────────────────────────────────────────────────────────────

class RubricCreate(BaseModel):
    # For coding assignments, scoring_policy.coding.{rubric_weight,testcase_weight} is required.
    content_json: dict
    source: RubricSource = RubricSource.manual


class RubricOut(BaseModel):
    model_config = {"from_attributes": True}
    id:            str
    assignment_id: str
    content_json:  dict
    source:        RubricSource
    approved:      bool
    approved_by:   Optional[str]
    created_at:    datetime


# ── Grade ─────────────────────────────────────────────────────────────────────

class GradeOut(BaseModel):
    model_config = {"from_attributes": True}
    id:               str
    submission_id:    str
    active_version:   bool
    total_score:      float
    breakdown_json:   dict
    source:           GradeSource
    classroom_status: ClassroomStatus
    is_truncated:     bool
    graded_at:        datetime


# ── Audit Log ─────────────────────────────────────────────────────────────────

class AuditLogOut(BaseModel):
    model_config = {"from_attributes": True}
    id:             str
    submission_id:  str
    changed_by:     str
    action:         str
    old_value_json: Optional[dict]
    new_value_json: Optional[dict]
    reason:         Optional[str]
    timestamp:      datetime


# ── OCR correction (TA edit) ──────────────────────────────────────────────────

class OCRCorrectionRequest(BaseModel):
    block_index: int
    new_content: str
    reason:      Optional[str] = None
    changed_by:  str = "ta"


class RegradeRequest(BaseModel):
    reason:     str = "Instructor requested regrade"
    changed_by: str = "ta"


class ManualGradeOverrideRequest(BaseModel):
    total_score:    float
    breakdown_json: dict
    reason:         str
    changed_by:     str = "ta"


# ── Batch operations ──────────────────────────────────────────────────────────

class BatchGradeRelease(BaseModel):
    submission_ids: list[str]


class JobEnqueuedResponse(BaseModel):
    job_id:        str
    submission_id: str
    status:        str = "enqueued"


# ── Code Evaluator ───────────────────────────────────────────────────────────

class CodeEvalEnvironmentVersionCreate(BaseModel):
    course_id: str
    assignment_id: Optional[str] = None
    profile_key: str
    reuse_mode: CodeEvalEnvironmentReuseMode = (
        CodeEvalEnvironmentReuseMode.course_reuse_with_assignment_overrides
    )
    spec_json: dict
    freeze_key: Optional[str] = None
    status: CodeEvalEnvironmentStatus = CodeEvalEnvironmentStatus.draft
    version_number: int = Field(default=1, ge=1)
    is_active: bool = True
    build_logs: Optional[str] = None
    created_by: Optional[str] = None


class CodeEvalEnvironmentVersionOut(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    course_id: str
    assignment_id: Optional[str]
    profile_key: str
    reuse_mode: CodeEvalEnvironmentReuseMode
    spec_json: dict
    freeze_key: Optional[str]
    status: CodeEvalEnvironmentStatus
    version_number: int
    is_active: bool
    build_logs: Optional[str]
    created_by: Optional[str]
    created_at: datetime
    updated_at: datetime


class CodeEvalEnvironmentBuildRequest(BaseModel):
    triggered_by: Optional[str] = None
    force_rebuild: bool = False


class CodeEvalEnvironmentBuildOut(BaseModel):
    status: str = "build_enqueued"
    environment_version: CodeEvalEnvironmentVersionOut


class CodeEvalEnvironmentPublishValidationOut(BaseModel):
    environment_version_id: str
    ready_for_publish: bool
    checks: dict[str, bool]
    missing: list[str] = Field(default_factory=list)


class CodeEvalRuntimeStatusOut(BaseModel):
    execution_backend: str
    shim_retry_enabled: bool
    ai_shim_generation_enabled: bool = False
    microvm: dict[str, Any]


class CodeEvalApprovalCreate(BaseModel):
    assignment_id: str
    artifact_type: CodeEvalApprovalArtifactType
    version_number: int = Field(default=1, ge=1)
    content_json: Optional[dict] = None
    generation_metadata_json: Optional[dict] = None
    requested_by: Optional[str] = None


class CodeEvalApprovalDecision(BaseModel):
    actor: str
    reason: Optional[str] = None


class CodeEvalApprovalOut(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    assignment_id: str
    artifact_type: CodeEvalApprovalArtifactType
    status: CodeEvalApprovalStatus
    version_number: int
    content_json: Optional[dict]
    generation_metadata_json: Optional[dict]
    requested_by: Optional[str]
    approved_by: Optional[str]
    approved_at: Optional[datetime]
    rejected_reason: Optional[str]
    created_at: datetime
    updated_at: datetime


class CodeEvalJobCreate(BaseModel):
    environment_version_id: Optional[str] = None
    explicit_regrade: bool = False
    request: CodeEvalJobRequest


class CodeEvalAttemptOut(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    job_id: str
    attempt_index: int
    stage: str
    passed: bool
    exit_code: Optional[int]
    score: float
    stdout: str
    stderr: str
    shim_used: bool
    shim_source: Optional[str]
    artifacts_json: Optional[dict]
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    created_at: datetime


class CodeEvalJobOut(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    assignment_id: str
    submission_id: str
    environment_version_id: Optional[str]
    status: CodeEvalJobStatus
    language: str
    entrypoint: str
    regrade_policy: CodeEvalRegradePolicy
    explicit_regrade: bool
    attempt_count: int
    final_result_json: Optional[dict]
    error_message: Optional[str]
    queued_at: datetime
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class CodeEvalJobDetailOut(CodeEvalJobOut):
    attempts: list[CodeEvalAttemptOut] = Field(default_factory=list)
