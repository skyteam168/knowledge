"""structured_records event timeline denorm columns (S2)

Revision ID: 0032
Revises: 0031
Create Date: 2026-11-25 14:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "structured_records",
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "structured_records",
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "structured_records",
        sa.Column("event_type", sa.String(length=32), nullable=True),
    )
    op.create_index(
        "ix_structured_records_occurred",
        "structured_records",
        ["org_id", "object_type", "occurred_at"],
    )
    op.create_index(
        "ix_structured_records_event_parent",
        "structured_records",
        [
            "org_id",
            "object_type",
            "parent_object_type",
            "parent_external_id",
            "occurred_at",
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_structured_records_event_parent", table_name="structured_records")
    op.drop_index("ix_structured_records_occurred", table_name="structured_records")
    op.drop_column("structured_records", "event_type")
    op.drop_column("structured_records", "ended_at")
    op.drop_column("structured_records", "occurred_at")
