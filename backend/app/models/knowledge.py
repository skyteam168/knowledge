from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, JsonType, TenantMixin, TimestampMixin, created_at_column


class KbVisibility(StrEnum):
    # Every member of the org can read; resource_acl entries grant more (edit/manage).
    ORG = "org"
    # Only principals listed in resource_acl.
    RESTRICTED = "restricted"


class DocumentStatus(StrEnum):
    UPLOADED = "uploaded"
    PARSING = "parsing"
    PARSED = "parsed"
    INDEXING = "indexing"
    INDEXED = "indexed"
    FAILED = "failed"


class ChunkType(StrEnum):
    TEXT = "text"
    TABLE = "table"
    TITLE = "title"


class KnowledgeBase(IdMixin, TenantMixin, TimestampMixin, Base):
    """A knowledge base. Its resource_acl entries are the default ACL inherited by documents."""

    __tablename__ = "knowledge_bases"
    __table_args__ = (UniqueConstraint("org_id", "name"),)

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    visibility: Mapped[str] = mapped_column(
        String(16), default=KbVisibility.RESTRICTED.value, nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(String(32))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Document(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_kb_sha256", "org_id", "kb_id", "sha256"),
        Index("ix_documents_kb_filename", "org_id", "kb_id", "filename"),
        Index("ix_documents_kb_status", "org_id", "kb_id", "status"),
    )

    kb_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("knowledge_bases.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    minio_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=DocumentStatus.UPLOADED.value, nullable=False
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(JsonType, default=list, nullable=False)
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JsonType, default=dict, nullable=False)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # True: permissions come from the knowledge base; False: own resource_acl entries apply.
    acl_inherit: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    chunk_count: Mapped[int | None] = mapped_column(Integer)
    parsed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    chunked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(String(32))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[str | None] = mapped_column(String(32))


class DocumentVersion(IdMixin, TenantMixin, Base):
    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("document_id", "version"),)

    document_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    minio_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = created_at_column()


class Chunk(TenantMixin, Base):
    """Chunk ids are deterministic per (document, version, seq): re-chunking overwrites."""

    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "document_version", "seq"),
        Index("ix_chunks_parent", "parent_id"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    kb_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    document_version: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_id: Mapped[str | None] = mapped_column(String(32))
    # 1 = parent (section level), 2 = child (retrieval unit).
    level: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    heading_path: Mapped[list[str]] = mapped_column(JsonType, default=list, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    sheet_name: Mapped[str | None] = mapped_column(String(255))
    slide_number: Mapped[int | None] = mapped_column(Integer)
    chunk_type: Mapped[str] = mapped_column(String(16), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = created_at_column()


class OutboxStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    # Dead letter: retries exhausted or permanently failing; needs manual retry.
    DEAD = "dead"


class OutboxEvent(IdMixin, TenantMixin, Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        Index("ix_outbox_events_status_created", "status", "created_at"),
        Index("ix_outbox_events_aggregate", "aggregate_type", "aggregate_id", "status"),
    )

    aggregate_type: Mapped[str] = mapped_column(String(32), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=OutboxStatus.PENDING.value, nullable=False
    )
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_column()
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Earliest time a pending event may be claimed again (exponential backoff).
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Lease of a processing event; expired leases are reclaimed by the dispatcher.
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
