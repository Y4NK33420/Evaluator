"""Code evaluator phase-1 schema.

Revision ID: 002
Create Date: 2026-04-06
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "code_eval_environment_versions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("course_id", sa.String(length=256), nullable=False),
        sa.Column("assignment_id", sa.String(length=36), sa.ForeignKey("assignments.id"), nullable=True),
        sa.Column("profile_key", sa.String(length=128), nullable=False),
        sa.Column(
            "reuse_mode",
            sa.Enum(
                "course_reuse_with_assignment_overrides",
                "assignment_only",
                name="codeevalenvironmentreusemode",
            ),
            nullable=False,
            server_default="course_reuse_with_assignment_overrides",
        ),
        sa.Column("spec_json", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column("freeze_key", sa.String(length=256), nullable=True),
        sa.Column(
            "status",
            sa.Enum("draft", "building", "ready", "failed", "deprecated", name="codeevalenvironmentstatus"),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("version_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("build_logs", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.text("now()")),
        sa.UniqueConstraint("course_id", "assignment_id", "profile_key", "version_number", name="uq_code_eval_env_scope_version"),
        sa.UniqueConstraint("freeze_key"),
    )
    op.create_index("ix_code_eval_environment_versions_course_id", "code_eval_environment_versions", ["course_id"])
    op.create_index("ix_code_eval_environment_versions_assignment_id", "code_eval_environment_versions", ["assignment_id"])
    op.create_index("ix_code_eval_environment_versions_profile_key", "code_eval_environment_versions", ["profile_key"])

    op.create_table(
        "code_eval_approval_records",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("assignment_id", sa.String(length=36), sa.ForeignKey("assignments.id"), nullable=False),
        sa.Column(
            "artifact_type",
            sa.Enum("ai_solution", "ai_tests", "ai_quality_rubric", name="codeevalapprovalartifacttype"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("pending", "approved", "rejected", name="codeevalapprovalstatus"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("version_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("content_json", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("generation_metadata_json", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("requested_by", sa.String(length=256), nullable=True),
        sa.Column("approved_by", sa.String(length=256), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.text("now()")),
        sa.UniqueConstraint("assignment_id", "artifact_type", "version_number", name="uq_code_eval_approval_artifact_version"),
    )
    op.create_index("ix_code_eval_approval_records_assignment_id", "code_eval_approval_records", ["assignment_id"])

    op.create_table(
        "code_eval_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("assignment_id", sa.String(length=36), sa.ForeignKey("assignments.id"), nullable=False),
        sa.Column("submission_id", sa.String(length=36), sa.ForeignKey("submissions.id"), nullable=False),
        sa.Column(
            "environment_version_id",
            sa.String(length=36),
            sa.ForeignKey("code_eval_environment_versions.id"),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "QUEUED",
                "EXECUTING_RAW",
                "AI_ANALYZING",
                "RETRYING_SHIM",
                "FINALIZING",
                "COMPLETED",
                "FAILED",
                name="codeevaljobstatus",
            ),
            nullable=False,
            server_default="QUEUED",
        ),
        sa.Column("language", sa.String(length=32), nullable=False),
        sa.Column("entrypoint", sa.String(length=512), nullable=False),
        sa.Column("request_json", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column("quality_config_json", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "regrade_policy",
            sa.Enum("new_only_unless_explicit", "force_reprocess_all", name="codeevalregradepolicy"),
            nullable=False,
            server_default="new_only_unless_explicit",
        ),
        sa.Column("explicit_regrade", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("final_result_json", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.text("now()")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.text("now()")),
    )
    op.create_index("ix_code_eval_jobs_assignment_id", "code_eval_jobs", ["assignment_id"])
    op.create_index("ix_code_eval_jobs_submission_id", "code_eval_jobs", ["submission_id"])
    op.create_index("ix_code_eval_jobs_environment_version_id", "code_eval_jobs", ["environment_version_id"])
    op.create_index("ix_code_eval_jobs_status", "code_eval_jobs", ["status"])

    op.create_table(
        "code_eval_attempts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("job_id", sa.String(length=36), sa.ForeignKey("code_eval_jobs.id"), nullable=False),
        sa.Column("attempt_index", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("stdout", sa.Text(), nullable=False, server_default=""),
        sa.Column("stderr", sa.Text(), nullable=False, server_default=""),
        sa.Column("shim_used", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("shim_source", sa.Text(), nullable=True),
        sa.Column("artifacts_json", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.text("now()")),
        sa.UniqueConstraint("job_id", "attempt_index", name="uq_code_eval_attempt_job_index"),
    )
    op.create_index("ix_code_eval_attempts_job_id", "code_eval_attempts", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_code_eval_attempts_job_id", table_name="code_eval_attempts")
    op.drop_table("code_eval_attempts")

    op.drop_index("ix_code_eval_jobs_status", table_name="code_eval_jobs")
    op.drop_index("ix_code_eval_jobs_environment_version_id", table_name="code_eval_jobs")
    op.drop_index("ix_code_eval_jobs_submission_id", table_name="code_eval_jobs")
    op.drop_index("ix_code_eval_jobs_assignment_id", table_name="code_eval_jobs")
    op.drop_table("code_eval_jobs")

    op.drop_index("ix_code_eval_approval_records_assignment_id", table_name="code_eval_approval_records")
    op.drop_table("code_eval_approval_records")

    op.drop_index("ix_code_eval_environment_versions_profile_key", table_name="code_eval_environment_versions")
    op.drop_index("ix_code_eval_environment_versions_assignment_id", table_name="code_eval_environment_versions")
    op.drop_index("ix_code_eval_environment_versions_course_id", table_name="code_eval_environment_versions")
    op.drop_table("code_eval_environment_versions")

    op.execute("DROP TYPE IF EXISTS codeevalregradepolicy")
    op.execute("DROP TYPE IF EXISTS codeevaljobstatus")
    op.execute("DROP TYPE IF EXISTS codeevalapprovalstatus")
    op.execute("DROP TYPE IF EXISTS codeevalapprovalartifacttype")
    op.execute("DROP TYPE IF EXISTS codeevalenvironmentstatus")
    op.execute("DROP TYPE IF EXISTS codeevalenvironmentreusemode")
