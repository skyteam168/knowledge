"""object_relations cardinality / attrs / valid time (Wave A Task5)

Revision ID: 0035
Revises: 0034
Create Date: 2026-11-25 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JsonType = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.add_column(
        "object_relations",
        sa.Column(
            "cardinality",
            sa.String(length=16),
            nullable=False,
            server_default="one_to_many",
        ),
    )
    op.add_column(
        "object_relations",
        sa.Column("attrs", JsonType, nullable=False, server_default=sa.text("'{}'")),
    )
    op.add_column(
        "object_relations",
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "object_relations",
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("object_relations", "valid_to")
    op.drop_column("object_relations", "valid_from")
    op.drop_column("object_relations", "attrs")
    op.drop_column("object_relations", "cardinality")
