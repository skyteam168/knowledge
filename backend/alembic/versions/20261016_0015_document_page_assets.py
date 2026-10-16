"""document page/slide raster assets for citation previews

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-16 10:40:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_page_assets",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("document_id", sa.String(32), nullable=False),
        sa.Column("document_version", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("page_index", sa.Integer(), nullable=False),
        sa.Column("minio_key", sa.String(1024), nullable=False),
        sa.Column("mime_type", sa.String(64), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "document_id",
            "document_version",
            "kind",
            "page_index",
            name="uq_doc_page_assets_doc_ver_kind_idx",
        ),
    )
    op.create_index("ix_document_page_assets_org_id", "document_page_assets", ["org_id"])
    op.create_index(
        "ix_document_page_assets_doc_ver",
        "document_page_assets",
        ["document_id", "document_version"],
    )


def downgrade() -> None:
    op.drop_table("document_page_assets")
