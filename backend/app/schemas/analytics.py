from datetime import date, datetime

from pydantic import BaseModel, Field


class NamedRef(BaseModel):
    id: str
    name: str


class AnalyticsFiltersOut(BaseModel):
    # Only platform administrators may look at other organizations.
    orgs: list[NamedRef]
    kbs: list[NamedRef]
    org_id: str
    timezone: str


class UsageSummaryOut(BaseModel):
    questions: int
    active_users_avg: float
    active_users_peak: int
    knowledge_questions: int = Field(description="grounded + uncertain + low_grounding + refused")
    answered: int = Field(description="Generated answers: grounded + uncertain + low_grounding")


class QualitySummaryOut(BaseModel):
    feedback_up: int
    feedback_down: int
    like_rate: float | None = Field(description="up / (up + down)")
    refusal_rate: float | None = Field(description="no_evidence / knowledge_questions")
    low_grounding_rate: float | None = Field(description="low_grounding / answered")
    avg_citations: float | None = Field(description="citations / answered")
    error_rate: float | None = Field(description="errors / questions")
    gaps_new: int
    gaps_resolved: int


class DailyPointOut(BaseModel):
    day: date
    active_users: int
    questions: int
    grounded: int
    uncertain: int
    low_grounding: int
    no_evidence: int
    chitchat: int
    out_of_scope: int
    errors: int
    citations: int
    feedback_up: int
    feedback_down: int
    gaps_new: int
    gaps_resolved: int
    like_rate: float | None
    refusal_rate: float | None
    low_grounding_rate: float | None
    avg_citations: float | None


class LatencyStatOut(BaseModel):
    stage: str
    count: int
    p50: float | None
    p95: float | None
    avg: float | None


class LatencyDailyOut(BaseModel):
    day: date
    stages: list[LatencyStatOut]


class KbHeatOut(BaseModel):
    kb_id: str
    kb_name: str
    questions: int
    active_users_peak: int
    citations: int
    feedback_down: int
    gaps_new: int


class TopQuestionOut(BaseModel):
    query: str
    count: int
    unanswered: int


class AnalyticsOverviewOut(BaseModel):
    org_id: str
    kb_id: str | None
    date_from: date
    date_to: date
    usage: UsageSummaryOut
    quality: QualitySummaryOut
    daily: list[DailyPointOut]
    latency: list[LatencyStatOut]
    latency_daily: list[LatencyDailyOut]
    kb_heat: list[KbHeatOut]
    top_questions: list[TopQuestionOut]
    refreshed_at: datetime | None


class StatusCountOut(BaseModel):
    status: str
    count: int


class ContentDocumentOut(BaseModel):
    id: str
    title: str
    filename: str
    kb_id: str
    kb_name: str
    status: str
    created_at: datetime
    updated_at: datetime
    effective_to: datetime | None = None
    last_cited: date | None = None
    error_message: str | None = None


class ContentKoOut(BaseModel):
    id: str
    title: str
    kb_id: str
    kb_name: str
    effective_to: datetime | None


class IndexHealthOut(BaseModel):
    outbox_pending: int
    outbox_processing: int
    outbox_dead: int
    oldest_pending_seconds: float | None
    failed_documents: list[ContentDocumentOut]


class AnalyticsContentOut(BaseModel):
    org_id: str
    kb_id: str | None
    knowledge_bases: int
    documents: int
    chunks: int
    published_kos: int
    document_status: list[StatusCountOut]
    index: IndexHealthOut
    zombie_days: int
    zombie_total: int
    zombie_documents: list[ContentDocumentOut]
    expiring_days: int
    expired_documents: int
    expiring_documents: list[ContentDocumentOut]
    expiring_kos: list[ContentKoOut]


class LlmUsageTotals(BaseModel):
    calls: int = 0
    errors: int = 0
    estimated_calls: int = Field(default=0, description="Calls without provider usage")
    fallback_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    avg_latency_ms: float | None = None


class LlmUsageSummaryOut(LlmUsageTotals):
    users: int = Field(description="Distinct callers (people and agents)")


class LlmUsageDailyOut(BaseModel):
    day: date
    calls: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class LlmUsageModelOut(LlmUsageTotals):
    kind: str
    model: str


class LlmUsageFeatureOut(LlmUsageTotals):
    feature: str


class LlmUsageUserOut(LlmUsageTotals):
    user_id: str
    username: str | None
    display_name: str | None
    department: str | None
    is_service: bool
    assistant_tokens: int = Field(description="Tokens of the AI assistant feature")


class LlmUsageOut(BaseModel):
    org_id: str
    user_id: str | None
    date_from: date
    date_to: date
    summary: LlmUsageSummaryOut
    daily: list[LlmUsageDailyOut]
    by_model: list[LlmUsageModelOut]
    by_feature: list[LlmUsageFeatureOut]
    users: list[LlmUsageUserOut]
    users_total: int
    refreshed_at: datetime | None


class AnalyticsRefreshIn(BaseModel):
    days: int = Field(default=2, ge=1, le=90)


class AnalyticsRefreshOut(BaseModel):
    days: list[str]
    rows: int
