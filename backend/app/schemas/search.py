from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.retrieval.config import RetrievalConfig

# ---- search ---------------------------------------------------------------------------


class SearchDocumentOut(BaseModel):
    id: str
    title: str
    filename: str
    kb_id: str
    kb_name: str
    version: int
    doc_type: str
    tags: list[str]
    updated_at: datetime


class StageScores(BaseModel):
    dense: float | None = None
    bm25: float | None = None
    rrf: float
    rerank: float | None = None


class StageRanks(BaseModel):
    dense: int | None = None
    bm25: int | None = None
    rrf: int
    rerank: int | None = None


class SearchHitOut(BaseModel):
    rank: int
    chunk_id: str
    content: str
    # HTML-escaped fragments with <em> marks around matched terms.
    snippet: str
    highlights: list[str]
    title_html: str
    heading_path: list[str]
    chunk_type: str
    page_start: int | None
    page_end: int | None
    sheet_name: str | None
    slide_number: int | None
    # A curated knowledge object (document = the KO, version = published version).
    is_ko: bool = False
    document: SearchDocumentOut
    scores: StageScores
    ranks: StageRanks


class AppliedKbOut(BaseModel):
    id: str
    name: str


class AppliedFiltersOut(BaseModel):
    kbs: list[AppliedKbOut]
    unresolved_kbs: list[str]
    tags: list[str]
    doc_types: list[str]
    date_from: datetime | None
    date_to: datetime | None


class SearchProfileRef(BaseModel):
    id: str | None
    name: str


class SearchDebugOut(BaseModel):
    config: dict[str, Any]
    stages: dict[str, Any]
    timings: dict[str, float]


class SearchResponse(BaseModel):
    query: str
    normalized_query: str
    exact_terms: list[str]
    ignored_operators: list[str]
    filters: AppliedFiltersOut
    items: list[SearchHitOut]
    total: int
    took_ms: float
    trace_id: str | None
    profile: SearchProfileRef
    degraded: list[str]
    cache_hit: bool
    debug: SearchDebugOut | None = None


class SearchOptionsOut(BaseModel):
    doc_types: list[str]
    tags: list[str]
    can_debug: bool


# ---- profiles ---------------------------------------------------------------------------


class RetrievalProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=2000)
    config: RetrievalConfig = Field(default_factory=RetrievalConfig)


class RetrievalProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=2000)
    config: RetrievalConfig | None = None


class RetrievalProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str | None
    name: str
    description: str | None
    config: RetrievalConfig
    is_active: bool
    builtin: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ---- traces ---------------------------------------------------------------------------


class RetrievalTraceSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str | None
    query: str
    profile_name: str
    generation: int | None
    cache_hit: bool
    degraded: list[str]
    result_count: int
    total_ms: int
    truncated: bool
    created_at: datetime


class RetrievalTraceOut(RetrievalTraceSummaryOut):
    normalized_query: str
    filters: dict[str, Any]
    profile_id: str | None
    config: dict[str, Any]
    principals_hash: str
    timings: dict[str, Any]
    stages: dict[str, Any]
