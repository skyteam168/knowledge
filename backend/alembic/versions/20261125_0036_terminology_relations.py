"""terminology_relations contains/inherits/related (Wave A Task6)

Revision ID: 0036
Revises: 0035
Create Date: 2026-11-25 19:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "terminology_relations",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("org_id", sa.String(length=32), nullable=False),
        sa.Column("from_id", sa.String(length=32), nullable=False),
        sa.Column("to_id", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
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
        sa.ForeignKeyConstraint(["from_id"], ["terminology_entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["to_id"], ["terminology_entities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "org_id", "from_id", "to_id", "kind", name="uq_terminology_relations_edge"
        ),
    )
    op.create_index(
        "ix_terminology_relations_from",
        "terminology_relations",
        ["org_id", "from_id"],
    )
    op.create_index(
        "ix_terminology_relations_to",
        "terminology_relations",
        ["org_id", "to_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_terminology_relations_to", table_name="terminology_relations")
    op.drop_index("ix_terminology_relations_from", table_name="terminology_relations")
    op.drop_table("terminology_relations")
