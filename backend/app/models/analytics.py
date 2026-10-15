"""Daily analytics summaries, rebuilt from qa_traces / feedback / gaps by the scheduler.

The dashboards only read these tables; they never scan the raw trace tables.
"""

from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, JsonType, TenantMixin, created_at_column

# kb_id of the org-wide rows (every question, whatever its knowledge base).
ALL_KBS = "*"


class AnalyticsDaily(IdMixin, TenantMixin, Base):
    """Usage, quality and latency of one day, org-wide (kb_id = '*') and per knowledge base.

    A question counts for every knowledge base it touched (conversation scope or citations).
    """

    __tablename__ = "analytics_daily"
    __table_args__ = (UniqueConstraint("org_id", "day", "kb_id"),)

    day: Mapped[date] = mapped_column(Date, nullable=False)
    kb_id: Mapped[str] = mapped_column(String(32), nullable=False)
    active_users: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    questions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    grounded: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    uncertain: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    low_grounding: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    no_evidence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    chitchat: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    out_of_scope: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    errors: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Citations of generated answers (grounded + uncertain + low_grounding).
    citations: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    feedback_up: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    feedback_down: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    gaps_new: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    gaps_resolved: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # stage -> {p50, p95, avg, count, hist}; hist counts per LATENCY_BUCKETS_MS bucket.
    latency: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, nullable=False)
    refreshed_at: Mapped[datetime] = created_at_column()


class AnalyticsTopQuestion(IdMixin, TenantMixin, Base):
    """Most asked (normalized) questions of a day."""

    __tablename__ = "analytics_top_questions"
    __table_args__ = (Index("ix_analytics_top_questions_day", "org_id", "day", "kb_id"),)

    day: Mapped[date] = mapped_column(Date, nullable=False)
    kb_id: Mapped[str] = mapped_column(String(32), nullable=False)
    query_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False)
    # Of which refused (no_evidence) or answered without valid citation (low_grounding).
    unanswered: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class AnalyticsDocCitation(IdMixin, TenantMixin, Base):
    """How often a document / knowledge object was cited in answers on a day."""

    __tablename__ = "analytics_doc_citations"
    __table_args__ = (
        Index("ix_analytics_doc_citations_day", "org_id", "day"),
        Index("ix_analytics_doc_citations_document", "org_id", "document_id", "day"),
    )

    day: Mapped[date] = mapped_column(Date, nullable=False)
    kb_id: Mapped[str] = mapped_column(String(32), nullable=False)
    document_id: Mapped[str] = mapped_column(String(32), nullable=False)
    is_ko: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    citations: Mapped[int] = mapped_column(Integer, nullable=False)
