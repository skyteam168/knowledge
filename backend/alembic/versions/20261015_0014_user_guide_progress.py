"""per-user onboarding tour progress

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-15 20:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_guide_progress",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("user_id", sa.String(32), nullable=False),
        sa.Column("guide_key", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "user_id", "guide_key", name="uq_user_guide_progress_user_id_guide_key"
        ),
    )
    op.create_index("ix_user_guide_progress_org_id", "user_guide_progress", ["org_id"])
    op.create_index("ix_user_guide_progress_user_id", "user_guide_progress", ["user_id"])


def downgrade() -> None:
    op.drop_table("user_guide_progress")
