from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import GapStatus, GapType, KoStatus, KoType, ReviewStatus

GapSort = Literal["frequency", "recent"]
ReviewDecision = Literal["approve", "reject"]


def _clean_list(values: list[str], limit: int) -> list[str]:
    return list(dict.fromkeys(v.strip() for v in values if v and v.strip()))[:limit]


class UserRef(BaseModel):
    id: str
    name: str


# ---- gaps ------------------------------------------------------------------------------


class GapOut(BaseModel):
    id: str
    gap_type: GapType
    status: GapStatus
    query: str
    rewritten_query: str | None
    description: str | None
    kb_id: str | None
    kb_name: str | None = None
    cluster_id: str | None
    # Occurrences of this gap (folded identical questions included).
    occurrences: int
    # Occurrences of the whole cluster (similar questions).
    cluster_occurrences: int | None = None
    cluster_size: int | None = None
    top_score: float | None
    assignee: UserRef | None = None
    user_id: str | None
    conversation_id: str | None
    message_id: str | None
    trace_id: str | None
    duplicate_of_id: str | None
    resolution: dict[str, Any]
    resolved_at: datetime | None
    created_at: datetime
    last_seen_at: datetime


class GapClusterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kb_id: str | None
    representative_query: str
    gap_count: int
    occurrences: int
    open_count: int
    sources: dict[str, int]
    last_seen_at: datetime


class GapStatsOut(BaseModel):
    by_status: dict[str, int]
    # Active (open / in_review) occurrences per source signal.
    by_source: dict[str, int]
    clusters_open: int


class ConversationMessageOut(BaseModel):
    id: str
    role: str
    content: str
    grounding: str | None = None
    citations: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    # The answer used material the reviewer may not read: content withheld.
    redacted: bool = False
    is_gap_message: bool = False


class GapKoRef(BaseModel):
    id: str
    title: str
    status: KoStatus
    published_version: int | None


class GapDetailOut(GapOut):
    conversation: list[ConversationMessageOut]
    # QA trace of the answer (material contents of unreadable documents are removed).
    qa_trace: dict[str, Any] | None = None
    cluster: GapClusterOut | None = None
    similar: list[GapOut] = Field(default_factory=list)
    knowledge_objects: list[GapKoRef] = Field(default_factory=list)


class GapPatch(BaseModel):
    assignee_id: str | None = Field(default=None, max_length=32)
    kb_id: str | None = Field(default=None, max_length=32)


class GapLinkDocumentsIn(BaseModel):
    """The answer exists in these documents: a retrieval problem (kept for tuning)."""

    document_ids: list[str] = Field(min_length=1, max_length=20)
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("document_ids")
    @classmethod
    def _ids(cls, value: list[str]) -> list[str]:
        return _clean_list(value, 20)


class GapRejectIn(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class GapDuplicateIn(BaseModel):
    duplicate_of_id: str = Field(min_length=1, max_length=32)
    note: str | None = Field(default=None, max_length=2000)


class GapDraftIn(BaseModel):
    """Ask the knowledge compiler for a KO draft answering the gap."""

    kb_id: str | None = Field(default=None, max_length=32)
    ko_type: KoType = KoType.FAQ
    # Documents the answer should come from (empty: search the knowledge base).
    document_ids: list[str] = Field(default_factory=list, max_length=20)
    # Material written by the reviewer (treated as a source of the draft).
    notes: str | None = Field(default=None, max_length=8000)

    @field_validator("document_ids")
    @classmethod
    def _ids(cls, value: list[str]) -> list[str]:
        return _clean_list(value, 20)


class ClusterRunOut(BaseModel):
    processed: int
    clustered: int
    new_clusters: int
    folded: int


# ---- knowledge objects ---------------------------------------------------------------------


class KoSourceIn(BaseModel):
    document_id: str = Field(min_length=1, max_length=32)
    chunk_id: str | None = Field(default=None, max_length=32)
    quote: str | None = Field(default=None, max_length=2000)


class KoSourceOut(BaseModel):
    document_id: str
    chunk_id: str | None = None
    title: str
    heading_path: list[str] = Field(default_factory=list)
    quote: str | None = None
    doc_version: int | None = None
    # False: deleted, or the caller cannot read it (title withheld).
    available: bool = True


class _KoFields(BaseModel):
    title: str | None = Field(default=None, max_length=512)
    question: str = Field(min_length=1, max_length=2000)
    variants: list[str] = Field(default_factory=list, max_length=30)
    answer: str = Field(default="", max_length=20000)
    sources: list[KoSourceIn] = Field(default_factory=list, max_length=50)
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    owner_id: str | None = Field(default=None, max_length=32)

    @field_validator("question")
    @classmethod
    def _question(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("question must not be blank")
        return value.strip()

    @field_validator("variants")
    @classmethod
    def _variants(cls, value: list[str]) -> list[str]:
        return [v[:2000] for v in _clean_list(value, 30)]

    @model_validator(mode="after")
    def _window(self) -> "_KoFields":
        if self.effective_from and self.effective_to and self.effective_to <= self.effective_from:
            raise ValueError("effective_to must be after effective_from")
        return self


class KoCreate(_KoFields):
    kb_id: str = Field(min_length=1, max_length=32)
    ko_type: KoType = KoType.FAQ
    gap_ids: list[str] = Field(default_factory=list, max_length=50)


class KoUpdate(_KoFields):
    ko_type: KoType = KoType.FAQ


class KoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kb_id: str
    kb_name: str | None = None
    ko_type: KoType
    title: str
    question: str
    variants: list[str]
    status: KoStatus
    version: int
    published_version: int | None
    origin: str
    owner: UserRef | None = None
    effective_from: datetime | None
    effective_to: datetime | None
    conflict_count: int = 0
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ReviewTaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    ko_id: str
    ko_title: str | None = None
    kb_id: str | None = None
    ko_version: int
    status: ReviewStatus
    submitted_by: UserRef | None = None
    note: str | None
    reviewer: UserRef | None = None
    comment: str | None
    decided_at: datetime | None
    conflicts: list[dict[str, Any]]
    created_at: datetime


class KoDetailOut(KoOut):
    answer: str
    sources: list[KoSourceOut]
    acl_inherit: bool
    gap_ids: list[str]
    ai_draft: dict[str, Any]
    conflicts: list[dict[str, Any]]
    conflicts_checked_at: datetime | None
    pending_review: ReviewTaskOut | None = None
    reviews: list[ReviewTaskOut] = Field(default_factory=list)
    can_edit: bool = False
    can_review: bool = False


class KoVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    ko_id: str
    version: int
    ko_type: KoType
    title: str
    question: str
    variants: list[str]
    answer: str
    sources: list[dict[str, Any]]
    effective_from: datetime | None
    effective_to: datetime | None
    status: str
    note: str | None
    created_by: UserRef | None = None
    created_at: datetime
    published_at: datetime | None
    published_by: UserRef | None = None


class KoSubmitIn(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class KoReviewIn(BaseModel):
    decision: ReviewDecision
    comment: str | None = Field(default=None, max_length=2000)


class KoDeprecateIn(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)


class FaqGenerateIn(BaseModel):
    max_items: int = Field(default=5, ge=1, le=20)
    ko_type: KoType = KoType.FAQ


# ---- notifications -------------------------------------------------------------------------


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: str
    title: str
    body: str | None
    resource_type: str | None
    resource_id: str | None
    link: str | None
    read_at: datetime | None
    created_at: datetime


class NotificationReadIn(BaseModel):
    # None: mark everything read.
    ids: list[str] | None = Field(default=None, max_length=200)


class UnreadCountOut(BaseModel):
    unread: int
