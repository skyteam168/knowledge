"""Collaboration: favorites, recently viewed and document comments."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    IdMixin,
    JsonType,
    TenantMixin,
    TimestampMixin,
    created_at_column,
    utcnow,
)


class Favorite(IdMixin, TenantMixin, Base):
    __tablename__ = "favorites"
    __table_args__ = (
        UniqueConstraint("user_id", "resource_type", "resource_id"),
        Index("ix_favorites_user", "org_id", "user_id", "created_at"),
    )

    user_id: Mapped[str] = mapped_column(String(32), nullable=False)
    # "document" or "kb"
    resource_type: Mapped[str] = mapped_column(String(16), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = created_at_column()


class RecentView(IdMixin, TenantMixin, Base):
    __tablename__ = "recent_views"
    __table_args__ = (
        UniqueConstraint("user_id", "resource_type", "resource_id"),
        Index("ix_recent_views_user", "org_id", "user_id", "viewed_at"),
    )

    user_id: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(16), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(32), nullable=False)
    viewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class DocumentComment(IdMixin, TenantMixin, TimestampMixin, Base):
    """A comment on a document; replies point at a top-level comment (one level deep)."""

    __tablename__ = "document_comments"
    __table_args__ = (Index("ix_document_comments_doc", "document_id", "created_at"),)

    document_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    kb_id: Mapped[str] = mapped_column(String(32), nullable=False)
    parent_id: Mapped[str | None] = mapped_column(String(32))
    author_id: Mapped[str] = mapped_column(String(32), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    mentions: Mapped[list[str]] = mapped_column(JsonType, default=list, nullable=False)
    # Version the comment was written against.
    document_version: Mapped[int] = mapped_column(Integer, nullable=False)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[str | None] = mapped_column(String(32))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
