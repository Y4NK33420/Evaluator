"""Initial schema — all five core tables.

Revision ID: 001
Create Date: 2026-04-01
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── assignments ───────────────────────────────────────────────────────────
    op.create_table(
        "assignments",
        sa.Column("id",                 sa.String(36),   primary_key=True),
        sa.Column("course_id",          sa.String(256),  nullable=False),
        sa.Column("classroom_id",       sa.String(256),  nullable=True),
        sa.Column("title",              sa.String(512),  nullable=False),
        sa.Column("description",        sa.Text(),       nullable=True),
        sa.Column("deadline",           sa.DateTime(timezone=True), nullable=True),
        sa.Column("max_marks",          sa.Float(),      nullable=False, server_default="100"),
        sa.Column("question_type",
                  sa.Enum("objective", "subjective", "mixed", name="questiontype"),
                  nullable=False, server_default="subjective"),
        sa.Column("has_code_question",  sa.Boolean(),    nullable=False, server_default="false"),
        sa.Column("created_at",         sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at",         sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_assignments_course_id", "assignments", ["course_id"])

    # ── submissions ───────────────────────────────────────────────────────────
    op.create_table(
        "submissions",
        sa.Column("id",            sa.String(36),  primary_key=True),
        sa.Column("assignment_id", sa.String(36),  sa.ForeignKey("assignments.id"), nullable=False),
        sa.Column("student_id",    sa.String(256), nullable=False),
        sa.Column("student_name",  sa.String(512), nullable=True),
        sa.Column("file_path",     sa.String(1024),nullable=True),
        sa.Column("image_hash",    sa.String(64),  nullable=True),
        sa.Column("status",
                  sa.Enum("pending","processing","ocr_done","grading","graded","failed",
                           name="submissionstatus"),
                  nullable=False, server_default="pending"),
        sa.Column("ocr_result",    postgresql.JSON(), nullable=True),
        sa.Column("ocr_engine",    sa.String(32),  nullable=True),
        sa.Column("error_message", sa.Text(),      nullable=True),
        sa.Column("created_at",    sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at",    sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("assignment_id", "student_id", name="uq_submission_student"),
    )
    op.create_index("ix_submissions_assignment_id", "submissions", ["assignment_id"])
    op.create_index("ix_submissions_student_id",   "submissions", ["student_id"])
    op.create_index("ix_submissions_status",       "submissions", ["status"])

    # ── rubrics ───────────────────────────────────────────────────────────────
    op.create_table(
        "rubrics",
        sa.Column("id",            sa.String(36),  primary_key=True),
        sa.Column("assignment_id", sa.String(36),  sa.ForeignKey("assignments.id"), nullable=False),
        sa.Column("content_json",  postgresql.JSON(), nullable=False),
        sa.Column("source",
                  sa.Enum("manual", "ai_generated", name="rubricsource"),
                  nullable=False),
        sa.Column("approved",      sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("approved_by",   sa.String(256), nullable=True),
        sa.Column("created_at",    sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_rubrics_assignment_id", "rubrics", ["assignment_id"])

    # ── grades ────────────────────────────────────────────────────────────────
    op.create_table(
        "grades",
        sa.Column("id",               sa.String(36),  primary_key=True),
        sa.Column("submission_id",    sa.String(36),  sa.ForeignKey("submissions.id"), nullable=False),
        sa.Column("active_version",   sa.Boolean(),   nullable=False, server_default="true"),
        sa.Column("total_score",      sa.Float(),     nullable=False),
        sa.Column("breakdown_json",   postgresql.JSON(), nullable=False),
        sa.Column("source",
                  sa.Enum("AI_Generated","AI_Corrected","AI_HEALED","TA_Manual",
                           name="gradesource"),
                  nullable=False),
        sa.Column("classroom_status",
                  sa.Enum("not_synced","draft","released", name="classroomstatus"),
                  nullable=False, server_default="not_synced"),
        sa.Column("is_truncated",     sa.Boolean(),   nullable=False, server_default="false"),
        sa.Column("graded_at",        sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_grades_submission_id",  "grades", ["submission_id"])
    op.create_index("ix_grades_active_version", "grades", ["active_version"])

    # ── audit_logs ────────────────────────────────────────────────────────────
    op.create_table(
        "audit_logs",
        sa.Column("id",             sa.String(36),  primary_key=True),
        sa.Column("submission_id",  sa.String(36),  sa.ForeignKey("submissions.id"), nullable=False),
        sa.Column("changed_by",     sa.String(256), nullable=False),
        sa.Column("action",         sa.String(128), nullable=False),
        sa.Column("old_value_json", postgresql.JSON(), nullable=True),
        sa.Column("new_value_json", postgresql.JSON(), nullable=True),
        sa.Column("reason",         sa.Text(),      nullable=True),
        sa.Column("timestamp",      sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_audit_logs_submission_id", "audit_logs", ["submission_id"])
    op.create_index("ix_audit_logs_timestamp",     "audit_logs", ["timestamp"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("grades")
    op.drop_table("rubrics")
    op.drop_table("submissions")
    op.drop_table("assignments")
    op.execute("DROP TYPE IF EXISTS questiontype")
    op.execute("DROP TYPE IF EXISTS submissionstatus")
    op.execute("DROP TYPE IF EXISTS rubricsource")
    op.execute("DROP TYPE IF EXISTS gradesource")
    op.execute("DROP TYPE IF EXISTS classroomstatus")
