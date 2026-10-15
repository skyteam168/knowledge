"""Token metering of model calls: one row per call, rolled up per day by the analytics job."""

from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TenantMixin, created_at_column

# user_id of usage rows without a user (indexing, scheduled jobs).
NO_USER = ""


class LlmUsage(IdMixin, TenantMixin, Base):
    __tablename__ = "llm_usage"
    __table_args__ = (
        Index("ix_llm_usage_org_created", "org_id", "created_at"),
        Index("ix_llm_usage_org_user_created", "org_id", "user_id", "created_at"),
    )

    user_id: Mapped[str | None] = mapped_column(String(32))
    feature: Mapped[str] = mapped_column(String(32), nullable=False)
    stage: Mapped[str | None] = mapped_column(String(32))
    # chat / embedding / rerank
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # The provider returned no usage: tokens are estimated from the text length.
    estimated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    input_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    first_token_ms: Mapped[int | None] = mapped_column(Integer)
    # ok / error / cancelled
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    fallback: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    conversation_id: Mapped[str | None] = mapped_column(String(32))
    message_id: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = created_at_column()


class AnalyticsLlmUsage(IdMixin, TenantMixin, Base):
    """Model usage of one day per user, feature, kind and model."""

    __tablename__ = "analytics_llm_usage"
    __table_args__ = (
        UniqueConstraint("org_id", "day", "user_id", "feature", "kind", "model"),
        Index("ix_analytics_llm_usage_user", "org_id", "user_id", "day"),
    )

    day: Mapped[date] = mapped_column(Date, nullable=False)
    user_id: Mapped[str] = mapped_column(String(32), nullable=False)
    feature: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    errors: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    estimated_calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    fallback_calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    latency_ms: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    refreshed_at: Mapped[datetime] = created_at_column()
