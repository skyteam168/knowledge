"""semantic_attributes unit / enum_map / labels (Wave A Task3)

Revision ID: 0034
Revises: 0033
Create Date: 2026-11-25 17:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JsonType = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.add_column(
        "semantic_attributes",
        sa.Column("unit", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "semantic_attributes",
        sa.Column("enum_map", JsonType, nullable=False, server_default=sa.text("'{}'")),
    )
    op.add_column(
        "semantic_attributes",
        sa.Column("labels", JsonType, nullable=False, server_default=sa.text("'{}'")),
    )


def downgrade() -> None:
    op.drop_column("semantic_attributes", "labels")
    op.drop_column("semantic_attributes", "enum_map")
    op.drop_column("semantic_attributes", "unit")
