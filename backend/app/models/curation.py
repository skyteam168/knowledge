"""Knowledge loop: gap clusters, knowledge objects (KO) with versions, reviews, notifications."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, JsonType, TenantMixin, TimestampMixin, created_at_column


class GapCluster(IdMixin, TenantMixin, TimestampMixin, Base):
    """Similar gap questions (incremental clustering on question embeddings)."""

    __tablename__ = "gap_clusters"
    __table_args__ = (Index("ix_gap_clusters_org_seen", "org_id", "last_seen_at"),)

    kb_id: Mapped[str | None] = mapped_column(String(32))
    representative_query: Mapped[str] = mapped_column(Text, nullable=False)
    # Normalized running mean of member embeddings (in the space of embedding_model).
    centroid: Mapped[list[float]] = mapped_column(JsonType, default=list, nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(255), nullable=False)
    embedding_dim: Mapped[int] = mapped_column(Integer, nullable=False)
    # Gaps that are not folded duplicates.
    gap_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Every signal, duplicates included.
    occurrences: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    open_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # gap_type -> occurrences
    sources: Mapped[dict[str, int]] = mapped_column(JsonType, default=dict, nullable=False)
    last_seen_at: Mapped[datetime] = created_at_column()


class KoType(StrEnum):
    FAQ = "faq"
    QA = "qa"
    CARD = "card"
    POLICY_SUMMARY = "policy_summary"


class KoStatus(StrEnum):
    """State of the working copy. A published version may stay live while a new draft exists."""

    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    PUBLISHED = "published"
    DEPRECATED = "deprecated"


class KoOrigin(StrEnum):
    MANUAL = "manual"
    GAP = "gap"
    DOCUMENT = "document"


class KoVersionStatus(StrEnum):
    PENDING_REVIEW = "pending_review"
    PUBLISHED = "published"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    # A later version was published.
    SUPERSEDED = "superseded"
    DEPRECATED = "deprecated"


class KnowledgeObject(IdMixin, TenantMixin, TimestampMixin, Base):
    """A curated knowledge object. Its fields are the working copy; live content is the
    `ko_versions` row of `published_version` (what the indexes and answers use)."""

    __tablename__ = "knowledge_objects"
    __table_args__ = (Index("ix_knowledge_objects_kb_status", "org_id", "kb_id", "status"),)

    kb_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("knowledge_bases.id", ondelete="RESTRICT"), nullable=False
    )
    ko_type: Mapped[str] = mapped_column(String(32), default=KoType.FAQ.value, nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    # Standard question and its alternative phrasings (all of them are indexed).
    question: Mapped[str] = mapped_column(Text, nullable=False)
    variants: Mapped[list[str]] = mapped_column(JsonType, default=list, nullable=False)
    answer: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # [{document_id, chunk_id, title, heading_path, quote, doc_version}]
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JsonType, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=KoStatus.DRAFT.value, nullable=False)
    # Latest submitted version number (0 = never submitted).
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    published_version: Mapped[int | None] = mapped_column(Integer)
    # True: readers are those of the knowledge base; False: own resource_acl entries apply.
    acl_inherit: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    owner_id: Mapped[str | None] = mapped_column(String(32))
    origin: Mapped[str] = mapped_column(String(16), default=KoOrigin.MANUAL.value, nullable=False)
    gap_ids: Mapped[list[str]] = mapped_column(JsonType, default=list, nullable=False)
    # The compiler's original output (shown next to the edited draft).
    ai_draft: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, nullable=False)
    # Latest conflict detection: [{kind, id, title, score, verdict, reason, excerpt}]
    conflicts: Mapped[list[dict[str, Any]]] = mapped_column(JsonType, default=list, nullable=False)
    conflicts_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by: Mapped[str | None] = mapped_column(String(32))
    expiry_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(String(32))
    updated_by: Mapped[str | None] = mapped_column(String(32))


class KoVersion(IdMixin, TenantMixin, Base):
    """Immutable snapshot of a submitted KO version."""

    __tablename__ = "ko_versions"
    __table_args__ = (UniqueConstraint("ko_id", "version"),)

    ko_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("knowledge_objects.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    ko_type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    variants: Mapped[list[str]] = mapped_column(JsonType, default=list, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JsonType, default=list, nullable=False)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = created_at_column()
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by: Mapped[str | None] = mapped_column(String(32))


class KoEntry(TenantMixin, Base):
    """Index units of the published version: the standard question and each variant.

    Ids are deterministic per (ko, version, seq) and double as index chunk ids.
    """

    __tablename__ = "ko_entries"
    __table_args__ = (UniqueConstraint("ko_id", "ko_version", "seq"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    ko_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("knowledge_objects.id", ondelete="CASCADE"), nullable=False
    )
    ko_version: Mapped[int] = mapped_column(Integer, nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = created_at_column()


class KoSourceRef(IdMixin, TenantMixin, Base):
    """Documents cited by the published version (KO lookup by document at answer time)."""

    __tablename__ = "ko_source_refs"
    __table_args__ = (Index("ix_ko_source_refs_document", "org_id", "document_id"),)

    ko_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("knowledge_objects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[str] = mapped_column(String(32), nullable=False)
    chunk_id: Mapped[str | None] = mapped_column(String(32))


class ReviewStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class ReviewTask(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "review_tasks"
    __table_args__ = (Index("ix_review_tasks_org_status", "org_id", "status", "created_at"),)

    ko_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("knowledge_objects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ko_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=ReviewStatus.PENDING.value, nullable=False
    )
    submitted_by: Mapped[str | None] = mapped_column(String(32))
    note: Mapped[str | None] = mapped_column(Text)
    reviewer_id: Mapped[str | None] = mapped_column(String(32))
    comment: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Conflict detection results at submission time.
    conflicts: Mapped[list[dict[str, Any]]] = mapped_column(JsonType, default=list, nullable=False)


class Notification(IdMixin, TenantMixin, Base):
    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user", "org_id", "user_id", "created_at"),
        UniqueConstraint("user_id", "dedupe_key"),
    )

    user_id: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    resource_type: Mapped[str | None] = mapped_column(String(32))
    resource_id: Mapped[str | None] = mapped_column(String(64))
    link: Mapped[str | None] = mapped_column(String(512))
    # Same key for the same user = same notification (reminders are not repeated).
    dedupe_key: Mapped[str | None] = mapped_column(String(255))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_column()
