"""structured domains + generic records

Revision ID: 0027
Revises: 0026
Create Date: 2026-11-14 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "structured_domains",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("org_id", sa.String(length=32), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="generic"),
        sa.Column("description", sa.String(length=512), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
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
        sa.UniqueConstraint("org_id", "code", name="uq_structured_domains_org_code"),
    )
    op.create_index("ix_structured_domains_org", "structured_domains", ["org_id"])

    op.create_table(
        "structured_records",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("org_id", sa.String(length=32), nullable=False),
        sa.Column("domain_id", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=32), nullable=False),
        sa.Column("object_type", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("attrs", JSON, nullable=False),
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
        sa.ForeignKeyConstraint(["domain_id"], ["structured_domains.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["structured_sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "org_id",
            "source_id",
            "object_type",
            "external_id",
            name="uq_structured_records_source_type_ext",
        ),
    )
    op.create_index(
        "ix_structured_records_domain", "structured_records", ["org_id", "domain_id"]
    )
    op.create_index(
        "ix_structured_records_ext",
        "structured_records",
        ["org_id", "object_type", "external_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_structured_records_ext", table_name="structured_records")
    op.drop_index("ix_structured_records_domain", table_name="structured_records")
    op.drop_table("structured_records")
    op.drop_index("ix_structured_domains_org", table_name="structured_domains")
    op.drop_table("structured_domains")
