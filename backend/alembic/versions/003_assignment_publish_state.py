"""Add assignment publish state and bound code-eval environment.

Revision ID: 003
Create Date: 2026-04-07
"""

from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "assignments",
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column("assignments", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("assignments", sa.Column("published_by", sa.String(length=256), nullable=True))
    op.add_column(
        "assignments",
        sa.Column("published_environment_version_id", sa.String(length=36), nullable=True),
    )
    op.create_index(
        "ix_assignments_published_environment_version_id",
        "assignments",
        ["published_environment_version_id"],
    )
    op.create_foreign_key(
        "fk_assignments_published_environment_version_id",
        "assignments",
        "code_eval_environment_versions",
        ["published_environment_version_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_assignments_published_environment_version_id",
        "assignments",
        type_="foreignkey",
    )
    op.drop_index("ix_assignments_published_environment_version_id", table_name="assignments")
    op.drop_column("assignments", "published_environment_version_id")
    op.drop_column("assignments", "published_by")
    op.drop_column("assignments", "published_at")
    op.drop_column("assignments", "is_published")
