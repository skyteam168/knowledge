"""object_relations directed typed edges (O2.1)

Revision ID: 0030
Revises: 0029
Create Date: 2026-11-25 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "object_relations",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("org_id", sa.String(length=32), nullable=False),
        sa.Column("relation_type", sa.String(length=32), nullable=False),
        sa.Column("from_kind", sa.String(length=16), nullable=False),
        sa.Column("from_id", sa.String(length=32), nullable=False),
        sa.Column("from_object_type", sa.String(length=64), nullable=True),
        sa.Column("to_kind", sa.String(length=16), nullable=False),
        sa.Column("to_id", sa.String(length=32), nullable=False),
        sa.Column("to_object_type", sa.String(length=64), nullable=True),
        sa.Column("created_by", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "org_id",
            "relation_type",
            "from_kind",
            "from_id",
            "from_object_type",
            "to_kind",
            "to_id",
            "to_object_type",
            name="uq_object_relations_edge",
        ),
    )
    op.create_index(
        "ix_object_relations_from",
        "object_relations",
        ["org_id", "from_kind", "from_id"],
    )
    op.create_index(
        "ix_object_relations_to",
        "object_relations",
        ["org_id", "to_kind", "to_id"],
    )
    op.create_index(
        "ix_object_relations_type",
        "object_relations",
        ["org_id", "relation_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_object_relations_type", table_name="object_relations")
    op.drop_index("ix_object_relations_to", table_name="object_relations")
    op.drop_index("ix_object_relations_from", table_name="object_relations")
    op.drop_table("object_relations")
