"""SQLAlchemy ORM models for grading and code-evaluation flows."""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Integer,
    String, Text, Enum as SAEnum, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


# ── Enums ─────────────────────────────────────────────────────────────────────

class QuestionType(str, enum.Enum):
    objective  = "objective"   # Gemini OCR text + GLM bbox/confidence metadata
    subjective = "subjective"  # Gemini OCR text
    mixed      = "mixed"       # follows subjective flow


class SubmissionStatus(str, enum.Enum):
    pending    = "pending"
    processing = "processing"
    ocr_done   = "ocr_done"
    grading    = "grading"
    graded     = "graded"
    failed     = "failed"


class GradeSource(str, enum.Enum):
    ai_generated = "AI_Generated"
    ai_corrected = "AI_Corrected"
    ai_healed    = "AI_HEALED"
    ta_manual    = "TA_Manual"


class ClassroomStatus(str, enum.Enum):
    not_synced = "not_synced"
    draft      = "draft"
    released   = "released"


class RubricSource(str, enum.Enum):
    manual       = "manual"
    ai_generated = "ai_generated"


class CodeEvalEnvironmentReuseMode(str, enum.Enum):
    course_reuse_with_assignment_overrides = "course_reuse_with_assignment_overrides"
    assignment_only = "assignment_only"


class CodeEvalEnvironmentStatus(str, enum.Enum):
    draft = "draft"
    building = "building"
    ready = "ready"
    failed = "failed"
    deprecated = "deprecated"


class CodeEvalApprovalArtifactType(str, enum.Enum):
    ai_solution = "ai_solution"
    ai_tests = "ai_tests"
    ai_quality_rubric = "ai_quality_rubric"


class CodeEvalApprovalStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class CodeEvalJobStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    EXECUTING_RAW = "EXECUTING_RAW"
    AI_ANALYZING = "AI_ANALYZING"
    RETRYING_SHIM = "RETRYING_SHIM"
    FINALIZING = "FINALIZING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class CodeEvalRegradePolicy(str, enum.Enum):
    new_only_unless_explicit = "new_only_unless_explicit"
    force_reprocess_all = "force_reprocess_all"


# ── Tables ────────────────────────────────────────────────────────────────────

class Assignment(Base):
    __tablename__ = "assignments"

    id:            Mapped[str]  = mapped_column(String(36), primary_key=True, default=_uuid)
    course_id:     Mapped[str]  = mapped_column(String(256), nullable=False, index=True)
    classroom_id:  Mapped[str | None] = mapped_column(String(256), nullable=True)
    title:         Mapped[str]  = mapped_column(String(512), nullable=False)
    description:   Mapped[str | None] = mapped_column(Text, nullable=True)
    deadline:      Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    max_marks:     Mapped[float] = mapped_column(Float, nullable=False, default=100.0)
    question_type: Mapped[QuestionType] = mapped_column(
        SAEnum(QuestionType), nullable=False, default=QuestionType.subjective
    )
    has_code_question: Mapped[bool] = mapped_column(Boolean, default=False)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    published_environment_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("code_eval_environment_versions.id"),
        nullable=True,
    )
    created_at:    Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at:    Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    # relationships
    submissions: Mapped[list["Submission"]] = relationship(back_populates="assignment")
    rubrics:     Mapped[list["Rubric"]]     = relationship(back_populates="assignment")
    code_eval_environment_versions: Mapped[list["CodeEvalEnvironmentVersion"]] = relationship(
        back_populates="assignment",
        foreign_keys="CodeEvalEnvironmentVersion.assignment_id",
    )
    published_environment_version: Mapped["CodeEvalEnvironmentVersion | None"] = relationship(
        foreign_keys=[published_environment_version_id],
    )
    code_eval_approval_records: Mapped[list["CodeEvalApprovalRecord"]] = relationship(
        back_populates="assignment"
    )
    code_eval_jobs: Mapped[list["CodeEvalJob"]] = relationship(back_populates="assignment")


class Submission(Base):
    __tablename__ = "submissions"

    id:            Mapped[str]  = mapped_column(String(36), primary_key=True, default=_uuid)
    assignment_id: Mapped[str]  = mapped_column(ForeignKey("assignments.id"), nullable=False, index=True)
    student_id:    Mapped[str]  = mapped_column(String(256), nullable=False, index=True)
    student_name:  Mapped[str | None] = mapped_column(String(512), nullable=True)
    file_path:     Mapped[str | None] = mapped_column(String(1024), nullable=True)
    image_hash:    Mapped[str | None] = mapped_column(String(64),  nullable=True)  # SHA-256
    status:        Mapped[SubmissionStatus] = mapped_column(
        SAEnum(SubmissionStatus), nullable=False, default=SubmissionStatus.pending, index=True
    )
    # OCR output stored as JSON:  {blocks: [{...}], flagged_count, ...}
    ocr_result:    Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ocr_engine:    Mapped[str | None]  = mapped_column(String(32), nullable=True)  # "gemini" | "gemini+glm_meta"
    error_message: Mapped[str | None]  = mapped_column(Text, nullable=True)
    created_at:    Mapped[datetime]    = mapped_column(DateTime(timezone=True), default=_now)
    updated_at:    Mapped[datetime]    = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    # relationships
    assignment: Mapped["Assignment"]  = relationship(back_populates="submissions")
    grades:     Mapped[list["Grade"]] = relationship(back_populates="submission")
    audit_logs: Mapped[list["AuditLog"]] = relationship(back_populates="submission")
    code_eval_jobs: Mapped[list["CodeEvalJob"]] = relationship(back_populates="submission")

    __table_args__ = (
        UniqueConstraint("assignment_id", "student_id", name="uq_submission_student"),
    )


class Rubric(Base):
    __tablename__ = "rubrics"

    id:            Mapped[str]  = mapped_column(String(36), primary_key=True, default=_uuid)
    assignment_id: Mapped[str]  = mapped_column(ForeignKey("assignments.id"), nullable=False, index=True)
    content_json:  Mapped[dict] = mapped_column(JSON, nullable=False)  # step-wise marking scheme
    source:        Mapped[RubricSource] = mapped_column(SAEnum(RubricSource), nullable=False)
    approved:      Mapped[bool] = mapped_column(Boolean, default=False)
    approved_by:   Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at:    Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    assignment: Mapped["Assignment"] = relationship(back_populates="rubrics")


class Grade(Base):
    __tablename__ = "grades"

    id:              Mapped[str]   = mapped_column(String(36), primary_key=True, default=_uuid)
    submission_id:   Mapped[str]   = mapped_column(ForeignKey("submissions.id"), nullable=False, index=True)
    active_version:  Mapped[bool]  = mapped_column(Boolean, default=True, index=True)
    total_score:     Mapped[float] = mapped_column(Float, nullable=False)
    breakdown_json:  Mapped[dict]  = mapped_column(JSON, nullable=False)  # {q1: {marks, feedback}, ...}
    source:          Mapped[GradeSource] = mapped_column(SAEnum(GradeSource), nullable=False)
    classroom_status: Mapped[ClassroomStatus] = mapped_column(
        SAEnum(ClassroomStatus), nullable=False, default=ClassroomStatus.not_synced
    )
    is_truncated:    Mapped[bool]  = mapped_column(Boolean, default=False)
    graded_at:       Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    submission: Mapped["Submission"] = relationship(back_populates="grades")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id:             Mapped[str]   = mapped_column(String(36), primary_key=True, default=_uuid)
    submission_id:  Mapped[str]   = mapped_column(ForeignKey("submissions.id"), nullable=False, index=True)
    changed_by:     Mapped[str]   = mapped_column(String(256), nullable=False)  # TA user id or "system"
    action:         Mapped[str]   = mapped_column(String(128), nullable=False)  # "ocr_correction", "manual_override", ...
    old_value_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    new_value_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reason:         Mapped[str | None]  = mapped_column(Text, nullable=True)
    timestamp:      Mapped[datetime]    = mapped_column(DateTime(timezone=True), default=_now, index=True)

    submission: Mapped["Submission"] = relationship(back_populates="audit_logs")


class CodeEvalEnvironmentVersion(Base):
    __tablename__ = "code_eval_environment_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    course_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    assignment_id: Mapped[str | None] = mapped_column(
        ForeignKey("assignments.id"), nullable=True, index=True
    )
    profile_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    reuse_mode: Mapped[CodeEvalEnvironmentReuseMode] = mapped_column(
        SAEnum(CodeEvalEnvironmentReuseMode, name="codeevalenvironmentreusemode"),
        nullable=False,
        default=CodeEvalEnvironmentReuseMode.course_reuse_with_assignment_overrides,
    )
    spec_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    freeze_key: Mapped[str | None] = mapped_column(String(256), nullable=True, unique=True)
    status: Mapped[CodeEvalEnvironmentStatus] = mapped_column(
        SAEnum(CodeEvalEnvironmentStatus, name="codeevalenvironmentstatus"),
        nullable=False,
        default=CodeEvalEnvironmentStatus.draft,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    build_logs: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    assignment: Mapped["Assignment | None"] = relationship(
        back_populates="code_eval_environment_versions",
        foreign_keys=[assignment_id],
    )
    jobs: Mapped[list["CodeEvalJob"]] = relationship(back_populates="environment_version")

    __table_args__ = (
        UniqueConstraint(
            "course_id",
            "assignment_id",
            "profile_key",
            "version_number",
            name="uq_code_eval_env_scope_version",
        ),
    )


class CodeEvalApprovalRecord(Base):
    __tablename__ = "code_eval_approval_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    assignment_id: Mapped[str] = mapped_column(ForeignKey("assignments.id"), nullable=False, index=True)
    artifact_type: Mapped[CodeEvalApprovalArtifactType] = mapped_column(
        SAEnum(CodeEvalApprovalArtifactType, name="codeevalapprovalartifacttype"),
        nullable=False,
    )
    status: Mapped[CodeEvalApprovalStatus] = mapped_column(
        SAEnum(CodeEvalApprovalStatus, name="codeevalapprovalstatus"),
        nullable=False,
        default=CodeEvalApprovalStatus.pending,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    content_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    generation_metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    requested_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    assignment: Mapped["Assignment"] = relationship(back_populates="code_eval_approval_records")

    __table_args__ = (
        UniqueConstraint(
            "assignment_id",
            "artifact_type",
            "version_number",
            name="uq_code_eval_approval_artifact_version",
        ),
    )


class CodeEvalJob(Base):
    __tablename__ = "code_eval_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    assignment_id: Mapped[str] = mapped_column(ForeignKey("assignments.id"), nullable=False, index=True)
    submission_id: Mapped[str] = mapped_column(ForeignKey("submissions.id"), nullable=False, index=True)
    environment_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("code_eval_environment_versions.id"), nullable=True, index=True
    )
    status: Mapped[CodeEvalJobStatus] = mapped_column(
        SAEnum(CodeEvalJobStatus, name="codeevaljobstatus"),
        nullable=False,
        default=CodeEvalJobStatus.QUEUED,
        index=True,
    )
    language: Mapped[str] = mapped_column(String(32), nullable=False)
    entrypoint: Mapped[str] = mapped_column(String(512), nullable=False)
    request_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    quality_config_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    regrade_policy: Mapped[CodeEvalRegradePolicy] = mapped_column(
        SAEnum(CodeEvalRegradePolicy, name="codeevalregradepolicy"),
        nullable=False,
        default=CodeEvalRegradePolicy.new_only_unless_explicit,
    )
    explicit_regrade: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    final_result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    assignment: Mapped["Assignment"] = relationship(back_populates="code_eval_jobs")
    submission: Mapped["Submission"] = relationship(back_populates="code_eval_jobs")
    environment_version: Mapped["CodeEvalEnvironmentVersion | None"] = relationship(back_populates="jobs")
    attempts: Mapped[list["CodeEvalAttempt"]] = relationship(back_populates="job")


class CodeEvalAttempt(Base):
    __tablename__ = "code_eval_attempts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(ForeignKey("code_eval_jobs.id"), nullable=False, index=True)
    attempt_index: Mapped[int] = mapped_column(Integer, nullable=False)
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    stdout: Mapped[str] = mapped_column(Text, nullable=False, default="")
    stderr: Mapped[str] = mapped_column(Text, nullable=False, default="")
    shim_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    shim_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    artifacts_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    job: Mapped["CodeEvalJob"] = relationship(back_populates="attempts")

    __table_args__ = (
        UniqueConstraint("job_id", "attempt_index", name="uq_code_eval_attempt_job_index"),
    )
