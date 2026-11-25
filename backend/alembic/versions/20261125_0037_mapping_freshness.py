"""semantic_mappings source_of_truth + freshness_sla (Wave B Task7)

Revision ID: 0037
Revises: 0036
Create Date: 2026-11-25 20:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0037"
down_revision: str | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "semantic_mappings",
        sa.Column(
            "source_of_truth",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "semantic_mappings",
        sa.Column("freshness_sla_seconds", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("semantic_mappings", "freshness_sla_seconds")
    op.drop_column("semantic_mappings", "source_of_truth")
