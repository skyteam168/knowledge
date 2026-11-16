"""ko_relations light ontology edges

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-14 10:20:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ko_relations",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("org_id", sa.String(length=32), nullable=False),
        sa.Column("from_ko_id", sa.String(length=32), nullable=False),
        sa.Column("to_ko_id", sa.String(length=32), nullable=False),
        sa.Column(
            "relation_type",
            sa.String(length=32),
            nullable=False,
            server_default="related_to",
        ),
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
        sa.ForeignKeyConstraint(
            ["from_ko_id"],
            ["knowledge_objects.id"],
            name=op.f("fk_ko_relations_from_ko_id_knowledge_objects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["to_ko_id"],
            ["knowledge_objects.id"],
            name=op.f("fk_ko_relations_to_ko_id_knowledge_objects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ko_relations")),
        sa.UniqueConstraint(
            "org_id",
            "from_ko_id",
            "to_ko_id",
            "relation_type",
            name="uq_ko_relations_edge",
        ),
    )
    op.create_index("ix_ko_relations_org_id", "ko_relations", ["org_id"], unique=False)
    op.create_index(
        "ix_ko_relations_from", "ko_relations", ["org_id", "from_ko_id"], unique=False
    )
    op.create_index("ix_ko_relations_to", "ko_relations", ["org_id", "to_ko_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_ko_relations_to", table_name="ko_relations")
    op.drop_index("ix_ko_relations_from", table_name="ko_relations")
    op.drop_index("ix_ko_relations_org_id", table_name="ko_relations")
    op.drop_table("ko_relations")
