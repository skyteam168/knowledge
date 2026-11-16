"""terminology entities and aliases for query expansion

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-14 09:45:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "terminology_entities",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("org_id", sa.String(length=32), nullable=False),
        sa.Column("canonical_name", sa.String(length=256), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False, server_default="other"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_terminology_entities")),
    )
    op.create_index("ix_terminology_entities_org_id", "terminology_entities", ["org_id"])
    op.create_index(
        "ix_terminology_entities_org_type", "terminology_entities", ["org_id", "entity_type"]
    )
    op.create_index(
        "ix_terminology_entities_org_status", "terminology_entities", ["org_id", "status"]
    )

    op.create_table(
        "terminology_aliases",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("org_id", sa.String(length=32), nullable=False),
        sa.Column("entity_id", sa.String(length=32), nullable=False),
        sa.Column("alias", sa.String(length=256), nullable=False),
        sa.Column("alias_normalized", sa.String(length=256), nullable=False),
        sa.Column("lang", sa.String(length=8), nullable=False, server_default="any"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["terminology_entities.id"],
            name=op.f("fk_terminology_aliases_entity_id_terminology_entities"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_terminology_aliases")),
        sa.UniqueConstraint(
            "org_id", "alias_normalized", name="uq_terminology_aliases_org_norm"
        ),
    )
    op.create_index("ix_terminology_aliases_org_id", "terminology_aliases", ["org_id"])
    op.create_index("ix_terminology_aliases_entity", "terminology_aliases", ["entity_id"])


def downgrade() -> None:
    op.drop_index("ix_terminology_aliases_entity", table_name="terminology_aliases")
    op.drop_index("ix_terminology_aliases_org_id", table_name="terminology_aliases")
    op.drop_table("terminology_aliases")
    op.drop_index("ix_terminology_entities_org_status", table_name="terminology_entities")
    op.drop_index("ix_terminology_entities_org_type", table_name="terminology_entities")
    op.drop_index("ix_terminology_entities_org_id", table_name="terminology_entities")
    op.drop_table("terminology_entities")
