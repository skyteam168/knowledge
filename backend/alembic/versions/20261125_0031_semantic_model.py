"""semantic model versions + entities/attributes/mappings (OS1)

Revision ID: 0031
Revises: 0030
Create Date: 2026-11-25 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "semantic_model_versions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("org_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("notes", sa.String(length=512), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by", sa.String(length=32), nullable=True),
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
    )
    op.create_index(
        "ix_semantic_model_versions_org_status",
        "semantic_model_versions",
        ["org_id", "status"],
    )
    op.create_index(
        "ix_semantic_model_versions_org_active",
        "semantic_model_versions",
        ["org_id", "is_active"],
    )

    op.create_table(
        "semantic_entities",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("org_id", sa.String(length=32), nullable=False),
        sa.Column("version_id", sa.String(length=32), nullable=False),
        sa.Column("local_name", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=1024), nullable=True),
        sa.Column("object_type", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
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
            ["version_id"], ["semantic_model_versions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "org_id", "version_id", "local_name", name="uq_semantic_entities_version_local"
        ),
    )
    op.create_index(
        "ix_semantic_entities_version", "semantic_entities", ["org_id", "version_id"]
    )

    op.create_table(
        "semantic_attributes",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("org_id", sa.String(length=32), nullable=False),
        sa.Column("version_id", sa.String(length=32), nullable=False),
        sa.Column("entity_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=1024), nullable=True),
        sa.Column("attr_kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
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
            ["version_id"], ["semantic_model_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"], ["semantic_entities.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "org_id", "entity_id", "name", name="uq_semantic_attributes_entity_name"
        ),
    )
    op.create_index(
        "ix_semantic_attributes_entity", "semantic_attributes", ["org_id", "entity_id"]
    )
    op.create_index(
        "ix_semantic_attributes_version",
        "semantic_attributes",
        ["org_id", "version_id"],
    )

    op.create_table(
        "semantic_mappings",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("org_id", sa.String(length=32), nullable=False),
        sa.Column("version_id", sa.String(length=32), nullable=False),
        sa.Column("attribute_id", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=32), nullable=True),
        sa.Column("table_name", sa.String(length=128), nullable=False),
        sa.Column("column_name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
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
            ["version_id"], ["semantic_model_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["attribute_id"], ["semantic_attributes.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "org_id",
            "attribute_id",
            "table_name",
            "column_name",
            name="uq_semantic_mappings_attr_col",
        ),
    )
    op.create_index(
        "ix_semantic_mappings_attr", "semantic_mappings", ["org_id", "attribute_id"]
    )
    op.create_index(
        "ix_semantic_mappings_version", "semantic_mappings", ["org_id", "version_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_semantic_mappings_version", table_name="semantic_mappings")
    op.drop_index("ix_semantic_mappings_attr", table_name="semantic_mappings")
    op.drop_table("semantic_mappings")
    op.drop_index("ix_semantic_attributes_version", table_name="semantic_attributes")
    op.drop_index("ix_semantic_attributes_entity", table_name="semantic_attributes")
    op.drop_table("semantic_attributes")
    op.drop_index("ix_semantic_entities_version", table_name="semantic_entities")
    op.drop_table("semantic_entities")
    op.drop_index(
        "ix_semantic_model_versions_org_active", table_name="semantic_model_versions"
    )
    op.drop_index(
        "ix_semantic_model_versions_org_status", table_name="semantic_model_versions"
    )
    op.drop_table("semantic_model_versions")
