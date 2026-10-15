"""Offline RAG evaluation: datasets of questions with references, runs per retrieval profile."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, JsonType, TenantMixin, TimestampMixin, created_at_column


class EvalCaseSource(StrEnum):
    MANUAL = "manual"
    # An upvoted answer (source_id = message id).
    FEEDBACK = "feedback"
    # A resolved knowledge gap (source_id = gap id).
    GAP = "gap"


class EvalRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class EvalDataset(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "eval_datasets"
    __table_args__ = (UniqueConstraint("org_id", "name"),)

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(32))


class EvalCase(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "eval_cases"
    __table_args__ = (
        # One-click imports are idempotent per source item.
        UniqueConstraint("dataset_id", "source", "source_id"),
        Index("ix_eval_cases_dataset", "dataset_id", "created_at"),
    )

    dataset_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("eval_datasets.id", ondelete="CASCADE"), nullable=False
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    reference_answer: Mapped[str | None] = mapped_column(Text)
    # Relevance judgements: chunk ids when known, else document (or KO) ids.
    expected_document_ids: Mapped[list[str]] = mapped_column(JsonType, default=list, nullable=False)
    expected_chunk_ids: Mapped[list[str]] = mapped_column(JsonType, default=list, nullable=False)
    # Knowledge base scope of the question; empty = everything the run's user can read.
    kb_ids: Mapped[list[str]] = mapped_column(JsonType, default=list, nullable=False)
    tags: Mapped[list[str]] = mapped_column(JsonType, default=list, nullable=False)
    source: Mapped[str] = mapped_column(
        String(16), default=EvalCaseSource.MANUAL.value, nullable=False
    )
    source_id: Mapped[str | None] = mapped_column(String(32))
    created_by: Mapped[str | None] = mapped_column(String(32))


class EvalRun(IdMixin, TenantMixin, TimestampMixin, Base):
    """One evaluation of a dataset with one retrieval profile (config snapshot kept)."""

    __tablename__ = "eval_runs"
    __table_args__ = (Index("ix_eval_runs_org_created", "org_id", "created_at"),)

    dataset_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("eval_datasets.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str | None] = mapped_column(String(128))
    # NULL = built-in profile.
    profile_id: Mapped[str | None] = mapped_column(String(32))
    profile_name: Mapped[str] = mapped_column(String(64), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, nullable=False)
    # Embedding model, index generation, chunking parameters, judge model ... at run time.
    environment: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, nullable=False)
    judge_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=EvalRunStatus.PENDING.value, nullable=False
    )
    case_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    done_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Mean of every metric over the cases where it is defined.
    metrics: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Retrieval runs with this user's permissions (ACL applies to evaluation too).
    created_by: Mapped[str | None] = mapped_column(String(32))


class EvalResult(IdMixin, TenantMixin, Base):
    __tablename__ = "eval_results"
    __table_args__ = (UniqueConstraint("run_id", "case_id"),)

    run_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("eval_runs.id", ondelete="CASCADE"), nullable=False
    )
    case_id: Mapped[str] = mapped_column(String(32), nullable=False)
    # [{rank, chunk_id, document_id, score, relevant}]
    retrieved: Mapped[list[dict[str, Any]]] = mapped_column(JsonType, default=list, nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, nullable=False)
    answer: Mapped[str | None] = mapped_column(Text)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JsonType, default=list, nullable=False)
    grounding: Mapped[str | None] = mapped_column(String(32))
    # Judge verdicts and reasons.
    judge: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_column()
