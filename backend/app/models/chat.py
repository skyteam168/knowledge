from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, JsonType, TenantMixin, TimestampMixin, created_at_column


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class MessageStatus(StrEnum):
    STREAMING = "streaming"
    DONE = "done"
    ERROR = "error"


class Grounding(StrEnum):
    """How an assistant answer relates to the knowledge base."""

    GROUNDED = "grounded"
    # Evidence in the middle score band: answered, uncertain parts called out.
    UNCERTAIN = "uncertain"
    # An answer was generated but carries no valid citation.
    LOW_GROUNDING = "low_grounding"
    # Refused without calling the LLM: no reliable evidence.
    NO_EVIDENCE = "no_evidence"
    CHITCHAT = "chitchat"
    OUT_OF_SCOPE = "out_of_scope"


class FeedbackRating(StrEnum):
    UP = "up"
    DOWN = "down"


class FeedbackReason(StrEnum):
    INACCURATE = "inaccurate"
    INCOMPLETE = "incomplete"
    OUTDATED = "outdated"
    NOT_FOUND = "not_found"


class GapType(StrEnum):
    """Where a gap came from (its source signal)."""

    NO_EVIDENCE = "no_evidence"
    LOW_GROUNDING = "low_grounding"
    NEGATIVE_FEEDBACK = "negative_feedback"
    USER_REQUEST = "user_request"


class GapStatus(StrEnum):
    OPEN = "open"
    IN_REVIEW = "in_review"
    RESOLVED = "resolved"
    REJECTED = "rejected"
    # Folded into another gap (duplicate_of_id); counted in its occurrences.
    DUPLICATE = "duplicate"


ACTIVE_GAP_STATUSES = (GapStatus.OPEN.value, GapStatus.IN_REVIEW.value)


class Conversation(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_user_updated", "org_id", "user_id", "updated_at"),)

    user_id: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    # Knowledge base scope of the conversation; empty = every readable knowledge base.
    kb_ids: Mapped[list[str]] = mapped_column(JsonType, default=list, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Message(IdMixin, TenantMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_conversation_created", "conversation_id", "created_at"),)

    conversation_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=MessageStatus.DONE.value, nullable=False
    )
    intent: Mapped[str | None] = mapped_column(String(32))
    rewritten_query: Mapped[str | None] = mapped_column(Text)
    grounding: Mapped[str | None] = mapped_column(String(32))
    # [{n, document_id, chunk_id, title, heading_path, page_start, page_end, quote, ...}]
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JsonType, default=list, nullable=False)
    # Progress shown to the user: [{step, status, ms, detail}] (rewrite / retrieve / ...).
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JsonType, default=list, nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(32))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_column()


class MessageFeedback(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "message_feedback"
    __table_args__ = (UniqueConstraint("message_id", "user_id"),)

    message_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(String(32), nullable=False)
    rating: Mapped[str] = mapped_column(String(8), nullable=False)
    reasons: Mapped[list[str]] = mapped_column(JsonType, default=list, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)


class KnowledgeGap(IdMixin, TenantMixin, TimestampMixin, Base):
    """A question the knowledge base could not (reliably) answer."""

    __tablename__ = "knowledge_gaps"
    __table_args__ = (
        Index("ix_knowledge_gaps_org_status", "org_id", "status", "created_at"),
        Index("ix_knowledge_gaps_cluster_hash", "cluster_id", "query_hash"),
    )

    gap_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=GapStatus.OPEN.value, nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    rewritten_query: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[str | None] = mapped_column(String(32))
    # No foreign keys: gaps outlive the conversations they came from.
    conversation_id: Mapped[str | None] = mapped_column(String(32))
    message_id: Mapped[str | None] = mapped_column(String(32), index=True)
    trace_id: Mapped[str | None] = mapped_column(String(32))
    kb_ids: Mapped[list[str]] = mapped_column(JsonType, default=list, nullable=False)
    # The knowledge base the gap belongs to (single-KB scope, or set by a reviewer).
    kb_id: Mapped[str | None] = mapped_column(String(32), index=True)
    top_score: Mapped[float | None] = mapped_column(Float)
    description: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, nullable=False)
    # Set by the clustering job; NULL = not clustered yet.
    cluster_id: Mapped[str | None] = mapped_column(String(32))
    # Hash of the normalized question: identical questions in a cluster are folded.
    query_hash: Mapped[str | None] = mapped_column(String(64))
    occurrences: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    last_seen_at: Mapped[datetime] = created_at_column()
    assignee_id: Mapped[str | None] = mapped_column(String(32), index=True)
    duplicate_of_id: Mapped[str | None] = mapped_column(String(32), index=True)
    # {action: ko | retrieval_issue | rejected | duplicate, ko_id, document_ids, note, ...}
    resolution: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, nullable=False)
    resolved_by: Mapped[str | None] = mapped_column(String(32))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class QaTrace(IdMixin, TenantMixin, Base):
    """One question answering run: every step (rewrite ... citations) with timings."""

    __tablename__ = "qa_traces"
    __table_args__ = (Index("ix_qa_traces_org_created", "org_id", "created_at"),)

    user_id: Mapped[str | None] = mapped_column(String(32))
    conversation_id: Mapped[str | None] = mapped_column(String(32))
    message_id: Mapped[str | None] = mapped_column(String(32))
    query: Mapped[str] = mapped_column(Text, nullable=False)
    rewritten_query: Mapped[str | None] = mapped_column(Text)
    intent: Mapped[str | None] = mapped_column(String(32))
    grounding: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    retrieval_trace_ids: Mapped[list[str]] = mapped_column(JsonType, default=list, nullable=False)
    steps: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, nullable=False)
    timings: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, nullable=False)
    total_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = created_at_column()
