"""Add assignment authoring prompt text.

Revision ID: 005_assignment_authoring_prompt
Revises: 004
Create Date: 2026-04-28
"""

from alembic import op
import sqlalchemy as sa


revision = "005_assignment_authoring_prompt"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("assignments", sa.Column("authoring_prompt", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("assignments", "authoring_prompt")
