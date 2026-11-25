"""canonical_entities + entity_identifiers (Wave A Task2)

Revision ID: 0033
Revises: 0032
Create Date: 2026-11-25 16:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "canonical_entities",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("org_id", sa.String(length=32), nullable=False),
        sa.Column("object_type", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=256), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("structured_object_type", sa.String(length=64), nullable=True),
        sa.Column("structured_object_id", sa.String(length=32), nullable=True),
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
    )
    op.create_index(
        "ix_canonical_entities_org_type",
        "canonical_entities",
        ["org_id", "object_type"],
    )
    op.create_index(
        "ix_canonical_entities_org_status",
        "canonical_entities",
        ["org_id", "status"],
    )

    op.create_table(
        "entity_identifiers",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("org_id", sa.String(length=32), nullable=False),
        sa.Column("canonical_id", sa.String(length=32), nullable=False),
        sa.Column("system", sa.String(length=32), nullable=False),
        sa.Column("id_kind", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=128), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
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
            ["canonical_id"],
            ["canonical_entities.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "org_id",
            "system",
            "id_kind",
            "external_id",
            name="uq_entity_identifiers_org_system_kind_ext",
        ),
    )
    op.create_index(
        "ix_entity_identifiers_canonical",
        "entity_identifiers",
        ["org_id", "canonical_id"],
    )
    op.create_index(
        "ix_entity_identifiers_lookup",
        "entity_identifiers",
        ["org_id", "system", "external_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_entity_identifiers_lookup", table_name="entity_identifiers")
    op.drop_index("ix_entity_identifiers_canonical", table_name="entity_identifiers")
    op.drop_table("entity_identifiers")
    op.drop_index("ix_canonical_entities_org_status", table_name="canonical_entities")
    op.drop_index("ix_canonical_entities_org_type", table_name="canonical_entities")
    op.drop_table("canonical_entities")
