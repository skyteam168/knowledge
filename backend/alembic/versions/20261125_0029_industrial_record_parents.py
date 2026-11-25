"""structured_records parent columns + link object_type width (O1.3)

Revision ID: 0029
Revises: 0028
Create Date: 2026-11-25 09:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "structured_records",
        sa.Column("parent_object_type", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "structured_records",
        sa.Column("parent_external_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_structured_records_parent",
        "structured_records",
        ["org_id", "parent_object_type", "parent_external_id"],
    )
    # Align with structured_records.object_type (64) for industrial kinds.
    op.alter_column(
        "structured_entity_links",
        "object_type",
        existing_type=sa.String(length=32),
        type_=sa.String(length=64),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "structured_entity_links",
        "object_type",
        existing_type=sa.String(length=64),
        type_=sa.String(length=32),
        existing_nullable=False,
    )
    op.drop_index("ix_structured_records_parent", table_name="structured_records")
    op.drop_column("structured_records", "parent_external_id")
    op.drop_column("structured_records", "parent_object_type")
