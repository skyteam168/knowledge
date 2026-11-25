"""entity_state_history valid-time snapshots (Wave B Task8)

Revision ID: 0038
Revises: 0037
Create Date: 2026-11-25 21:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0038"
down_revision: str | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "entity_state_history",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("org_id", sa.String(length=32), nullable=False),
        sa.Column("canonical_id", sa.String(length=32), nullable=False),
        sa.Column("standard_status", sa.String(length=32), nullable=False),
        sa.Column("status_label", sa.String(length=64), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["canonical_id"], ["canonical_entities.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_entity_state_history_canonical",
        "entity_state_history",
        ["org_id", "canonical_id"],
    )
    op.create_index(
        "ix_entity_state_history_valid",
        "entity_state_history",
        ["org_id", "valid_from", "valid_to"],
    )


def downgrade() -> None:
    op.drop_index("ix_entity_state_history_valid", table_name="entity_state_history")
    op.drop_index("ix_entity_state_history_canonical", table_name="entity_state_history")
    op.drop_table("entity_state_history")
