"""Add grade_id back-reference to code_eval_jobs and code_eval to grade source enum.

Revision ID: 004
Depends on: 003
Create Date: 2026-04-13
"""

from alembic import op
import sqlalchemy as sa

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add code_eval to GradeSource enum
    op.execute("ALTER TYPE gradesource ADD VALUE IF NOT EXISTS 'code_eval'")

    # Add grade_id FK column to code_eval_jobs
    op.add_column(
        "code_eval_jobs",
        sa.Column(
            "grade_id",
            sa.String(36),
            sa.ForeignKey("grades.id", name="fk_code_eval_jobs_grade_id"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_code_eval_jobs_grade_id",
        "code_eval_jobs",
        ["grade_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_code_eval_jobs_grade_id", table_name="code_eval_jobs")
    op.drop_column("code_eval_jobs", "grade_id")
    # NOTE: PostgreSQL does not support removing enum values; gradesource retains 'code_eval'
