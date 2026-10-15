from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import FeedbackRating, FeedbackReason


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(v.strip() for v in values if v.strip()))


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    kb_ids: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("kb_ids")
    @classmethod
    def _kbs(cls, value: list[str]) -> list[str]:
        return _dedupe(value)


class ConversationUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    kb_ids: list[str] | None = Field(default=None, max_length=50)

    @field_validator("kb_ids")
    @classmethod
    def _kbs(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else _dedupe(value)


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    kb_ids: list[str]
    created_at: datetime
    updated_at: datetime


class CitationOut(BaseModel):
    n: int
    document_id: str
    chunk_id: str
    chunk_ids: list[str] = Field(default_factory=list)
    hit_chunk_ids: list[str] = Field(default_factory=list)
    title: str
    filename: str | None = None
    kb_id: str | None = None
    kb_name: str | None = None
    doc_version: int | None = None
    heading_path: list[str] = Field(default_factory=list)
    page_start: int | None = None
    page_end: int | None = None
    sheet_name: str | None = None
    slide_number: int | None = None
    quote: str
    score: float | None = None
    # Cites a knowledge object: document_id = ko_id, doc_version = its published version.
    is_ko: bool = False
    ko_type: str | None = None


class FeedbackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rating: FeedbackRating
    reasons: list[FeedbackReason]
    comment: str | None
    updated_at: datetime


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    status: str
    intent: str | None = None
    rewritten_query: str | None = None
    grounding: str | None = None
    citations: list[CitationOut] = Field(default_factory=list)
    steps: list[dict[str, Any]] = Field(default_factory=list)
    trace_id: str | None = None
    error: str | None = None
    created_at: datetime
    feedback: FeedbackOut | None = None
    knowledge_requested: bool = False


class ConversationDetailOut(ConversationOut):
    messages: list[MessageOut]


class AskIn(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    # Replaces the conversation's knowledge base scope when given.
    kb_ids: list[str] | None = Field(default=None, max_length=50)

    @field_validator("content")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("question must not be blank")
        return value.strip()

    @field_validator("kb_ids")
    @classmethod
    def _kbs(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else _dedupe(value)


class FeedbackIn(BaseModel):
    rating: FeedbackRating
    reasons: list[FeedbackReason] = Field(default_factory=list, max_length=4)
    comment: str | None = Field(default=None, max_length=2000)

    @field_validator("reasons")
    @classmethod
    def _unique(cls, value: list[FeedbackReason]) -> list[FeedbackReason]:
        return list(dict.fromkeys(value))


class KnowledgeRequestIn(BaseModel):
    description: str | None = Field(default=None, max_length=2000)


class KnowledgeGapOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    gap_type: str
    status: str
    query: str
    rewritten_query: str | None
    kb_ids: list[str]
    kb_id: str | None = None
    top_score: float | None
    description: str | None
    message_id: str | None
    created_at: datetime


class SourceSegmentOut(BaseModel):
    chunk_id: str
    content: str
    # The chunk was a retrieval hit cited by the answer.
    highlight: bool


class SourceDocumentOut(BaseModel):
    id: str
    title: str
    filename: str
    kb_id: str
    kb_name: str
    version: int


class KoSourceRefOut(BaseModel):
    """A document a knowledge object cites (only those readable by the caller)."""

    document_id: str
    title: str
    chunk_id: str | None = None
    heading_path: list[str] = Field(default_factory=list)
    quote: str | None = None


class KoCitationOut(BaseModel):
    id: str
    ko_type: str
    question: str
    variants: list[str]
    answer: str
    sources: list[KoSourceRefOut]
    effective_from: datetime | None = None
    effective_to: datetime | None = None


class CitationSourceOut(BaseModel):
    n: int
    document: SourceDocumentOut
    # The document changed since the answer was produced (cited version is gone).
    outdated: bool
    heading_path: list[str]
    page_start: int | None
    page_end: int | None
    anchor_chunk_id: str
    quote: str
    segments: list[SourceSegmentOut]
    is_ko: bool = False
    ko: KoCitationOut | None = None


class QaTraceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str | None
    conversation_id: str | None
    message_id: str | None
    query: str
    rewritten_query: str | None
    intent: str | None
    grounding: str | None
    status: str
    retrieval_trace_ids: list[str]
    steps: dict[str, Any]
    timings: dict[str, Any]
    total_ms: int
    created_at: datetime
