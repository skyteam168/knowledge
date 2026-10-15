from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, JsonType, TenantMixin, TimestampMixin, created_at_column


class RetrievalProfile(IdMixin, TenantMixin, TimestampMixin, Base):
    """A named retrieval strategy (top_k, weights, rerank...). One active profile per org."""

    __tablename__ = "retrieval_profiles"
    __table_args__ = (
        UniqueConstraint("org_id", "name"),
        Index(
            "uq_retrieval_profiles_active",
            "org_id",
            unique=True,
            postgresql_where=text("is_active"),
            sqlite_where=text("is_active"),
        ),
    )

    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    # RetrievalConfig (app.retrieval.config) as JSON.
    config: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(32))
    updated_by: Mapped[str | None] = mapped_column(String(32))


class RetrievalTrace(IdMixin, TenantMixin, Base):
    """One retrieval run: input, per-stage candidates and scores, timings (size-capped)."""

    __tablename__ = "retrieval_traces"
    __table_args__ = (Index("ix_retrieval_traces_org_created", "org_id", "created_at"),)

    user_id: Mapped[str | None] = mapped_column(String(32))
    query: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_query: Mapped[str] = mapped_column(Text, nullable=False)
    filters: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, nullable=False)
    profile_id: Mapped[str | None] = mapped_column(String(32))
    profile_name: Mapped[str] = mapped_column(String(64), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, nullable=False)
    principals_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    generation: Mapped[int | None] = mapped_column(Integer)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    degraded: Mapped[list[str]] = mapped_column(JsonType, default=list, nullable=False)
    result_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    timings: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, nullable=False)
    stages: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, nullable=False)
    truncated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    total_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = created_at_column()
