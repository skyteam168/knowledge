"""structured equipment mirror + entity links

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-14 11:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "structured_sources",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("org_id", sa.String(length=32), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False, server_default="manual"),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("meta", JSON, nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_structured_sources")),
        sa.UniqueConstraint("org_id", "name", name="uq_structured_sources_org_name"),
    )
    op.create_index("ix_structured_sources_org_id", "structured_sources", ["org_id"])

    op.create_table(
        "equip_devices",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("org_id", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("location", sa.String(length=256), nullable=True),
        sa.Column("meta", JSON, nullable=False),
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
            ["source_id"],
            ["structured_sources.id"],
            name=op.f("fk_equip_devices_source_id_structured_sources"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_equip_devices")),
        sa.UniqueConstraint(
            "org_id", "source_id", "external_id", name="uq_equip_devices_source_ext"
        ),
    )
    op.create_index("ix_equip_devices_org_id", "equip_devices", ["org_id"])
    op.create_index("ix_equip_devices_org_source", "equip_devices", ["org_id", "source_id"])

    op.create_table(
        "equip_work_orders",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("org_id", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.Column("device_external_id", sa.String(length=64), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="open"),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("meta", JSON, nullable=False),
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
            ["source_id"],
            ["structured_sources.id"],
            name=op.f("fk_equip_work_orders_source_id_structured_sources"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_equip_work_orders")),
        sa.UniqueConstraint(
            "org_id", "source_id", "external_id", name="uq_equip_work_orders_source_ext"
        ),
    )
    op.create_index("ix_equip_work_orders_org_id", "equip_work_orders", ["org_id"])
    op.create_index(
        "ix_equip_work_orders_org_source", "equip_work_orders", ["org_id", "source_id"]
    )
    op.create_index(
        "ix_equip_work_orders_device_ext",
        "equip_work_orders",
        ["org_id", "device_external_id"],
    )

    op.create_table(
        "equip_spare_parts",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("org_id", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("sku", sa.String(length=64), nullable=True),
        sa.Column("qty_on_hand", sa.Float(), nullable=False, server_default="0"),
        sa.Column("meta", JSON, nullable=False),
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
            ["source_id"],
            ["structured_sources.id"],
            name=op.f("fk_equip_spare_parts_source_id_structured_sources"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_equip_spare_parts")),
        sa.UniqueConstraint(
            "org_id", "source_id", "external_id", name="uq_equip_spare_parts_source_ext"
        ),
    )
    op.create_index("ix_equip_spare_parts_org_id", "equip_spare_parts", ["org_id"])
    op.create_index(
        "ix_equip_spare_parts_org_source", "equip_spare_parts", ["org_id", "source_id"]
    )

    op.create_table(
        "structured_entity_links",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("org_id", sa.String(length=32), nullable=False),
        sa.Column("object_type", sa.String(length=32), nullable=False),
        sa.Column("object_id", sa.String(length=32), nullable=False),
        sa.Column("terminology_entity_id", sa.String(length=32), nullable=True),
        sa.Column("ko_id", sa.String(length=32), nullable=True),
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
            ["terminology_entity_id"],
            ["terminology_entities.id"],
            name=op.f("fk_structured_entity_links_terminology_entity_id_terminology_entities"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ko_id"],
            ["knowledge_objects.id"],
            name=op.f("fk_structured_entity_links_ko_id_knowledge_objects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_structured_entity_links")),
        sa.UniqueConstraint(
            "org_id",
            "object_type",
            "object_id",
            "terminology_entity_id",
            "ko_id",
            name="uq_structured_entity_links_edge",
        ),
    )
    op.create_index("ix_structured_entity_links_org_id", "structured_entity_links", ["org_id"])
    op.create_index(
        "ix_structured_entity_links_object",
        "structured_entity_links",
        ["org_id", "object_type", "object_id"],
    )
    op.create_index(
        "ix_structured_entity_links_term",
        "structured_entity_links",
        ["org_id", "terminology_entity_id"],
    )
    op.create_index(
        "ix_structured_entity_links_ko",
        "structured_entity_links",
        ["org_id", "ko_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_structured_entity_links_ko", table_name="structured_entity_links")
    op.drop_index("ix_structured_entity_links_term", table_name="structured_entity_links")
    op.drop_index("ix_structured_entity_links_object", table_name="structured_entity_links")
    op.drop_index("ix_structured_entity_links_org_id", table_name="structured_entity_links")
    op.drop_table("structured_entity_links")
    op.drop_index("ix_equip_spare_parts_org_source", table_name="equip_spare_parts")
    op.drop_index("ix_equip_spare_parts_org_id", table_name="equip_spare_parts")
    op.drop_table("equip_spare_parts")
    op.drop_index("ix_equip_work_orders_device_ext", table_name="equip_work_orders")
    op.drop_index("ix_equip_work_orders_org_source", table_name="equip_work_orders")
    op.drop_index("ix_equip_work_orders_org_id", table_name="equip_work_orders")
    op.drop_table("equip_work_orders")
    op.drop_index("ix_equip_devices_org_source", table_name="equip_devices")
    op.drop_index("ix_equip_devices_org_id", table_name="equip_devices")
    op.drop_table("equip_devices")
    op.drop_index("ix_structured_sources_org_id", table_name="structured_sources")
    op.drop_table("structured_sources")
