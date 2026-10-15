"""knowledge bases, documents, versions, chunks and outbox events

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-08 15:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _ts(name: str) -> sa.Column[object]:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "knowledge_bases",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("visibility", sa.String(16), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_bases"),
        sa.UniqueConstraint("org_id", "name", name="uq_knowledge_bases_org_id_name"),
    )
    op.create_index("ix_knowledge_bases_org_id", "knowledge_bases", ["org_id"])

    op.create_table(
        "documents",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("kb_id", sa.String(32), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("mime_type", sa.String(255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("minio_key", sa.String(1024), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("tags", JSON, nullable=False),
        sa.Column("metadata", JSON, nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acl_inherit", sa.Boolean(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=True),
        sa.Column("parsed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("chunked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.String(32), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.PrimaryKeyConstraint("id", name="pk_documents"),
        sa.ForeignKeyConstraint(
            ["kb_id"],
            ["knowledge_bases.id"],
            name="fk_documents_kb_id_knowledge_bases",
            ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_documents_org_id", "documents", ["org_id"])
    op.create_index("ix_documents_kb_sha256", "documents", ["org_id", "kb_id", "sha256"])
    op.create_index("ix_documents_kb_filename", "documents", ["org_id", "kb_id", "filename"])
    op.create_index("ix_documents_kb_status", "documents", ["org_id", "kb_id", "status"])

    op.create_table(
        "document_versions",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("document_id", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("mime_type", sa.String(255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("minio_key", sa.String(1024), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        _ts("created_at"),
        sa.PrimaryKeyConstraint("id", name="pk_document_versions"),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_document_versions_document_id_documents",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "document_id", "version", name="uq_document_versions_document_id_version"
        ),
    )
    op.create_index("ix_document_versions_org_id", "document_versions", ["org_id"])

    op.create_table(
        "chunks",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("kb_id", sa.String(32), nullable=False),
        sa.Column("document_id", sa.String(32), nullable=False),
        sa.Column("document_version", sa.Integer(), nullable=False),
        sa.Column("parent_id", sa.String(32), nullable=True),
        sa.Column("level", sa.SmallInteger(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("heading_path", JSON, nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("sheet_name", sa.String(255), nullable=True),
        sa.Column("slide_number", sa.Integer(), nullable=True),
        sa.Column("chunk_type", sa.String(16), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        _ts("created_at"),
        sa.PrimaryKeyConstraint("id", name="pk_chunks"),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_chunks_document_id_documents",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "document_id",
            "document_version",
            "seq",
            name="uq_chunks_document_id_document_version_seq",
        ),
    )
    op.create_index("ix_chunks_org_id", "chunks", ["org_id"])
    op.create_index("ix_chunks_kb_id", "chunks", ["kb_id"])
    op.create_index("ix_chunks_parent", "chunks", ["parent_id"])

    op.create_table(
        "outbox_events",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("org_id", sa.String(32), nullable=False),
        sa.Column("aggregate_type", sa.String(32), nullable=False),
        sa.Column("aggregate_id", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("payload", JSON, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        _ts("created_at"),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_outbox_events"),
    )
    op.create_index("ix_outbox_events_org_id", "outbox_events", ["org_id"])
    op.create_index("ix_outbox_events_status_created", "outbox_events", ["status", "created_at"])


def downgrade() -> None:
    op.drop_table("outbox_events")
    op.drop_table("chunks")
    op.drop_table("document_versions")
    op.drop_table("documents")
    op.drop_table("knowledge_bases")
