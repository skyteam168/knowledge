import ipaddress
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import ApiScope

PrincipalKind = Literal["dept", "group", "role"]


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(v.strip() for v in values if v and v.strip()))


def _check_ips(values: list[str]) -> list[str]:
    cleaned = _dedupe(values)
    for value in cleaned:
        try:
            ipaddress.ip_network(value, strict=False)
        except ValueError as exc:
            raise ValueError(f"invalid IP address or CIDR: {value}") from exc
    return cleaned


# ---- admin ----------------------------------------------------------------------------


class ApiPrincipalRef(BaseModel):
    type: PrincipalKind
    id: str = Field(min_length=1, max_length=32)


class ApiPrincipalOut(ApiPrincipalRef):
    name: str | None = None


class NamedRef(BaseModel):
    id: str
    name: str


class ApiClientCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    owner_department_id: str | None = Field(default=None, max_length=32)
    contact: str | None = Field(default=None, max_length=255)
    kb_ids: list[str] = Field(min_length=1, max_length=100)
    principals: list[ApiPrincipalRef] = Field(min_length=1, max_length=20)
    scopes: list[ApiScope] = Field(min_length=1)
    rate_limit_per_minute: int = Field(default=0, ge=0, le=6000)
    daily_quota: int = Field(default=0, ge=0, le=10_000_000)
    ip_allowlist: list[str] = Field(default_factory=list, max_length=50)
    expires_at: datetime | None = None

    @field_validator("kb_ids")
    @classmethod
    def _kbs(cls, value: list[str]) -> list[str]:
        return _dedupe(value)

    @field_validator("ip_allowlist")
    @classmethod
    def _ips(cls, value: list[str]) -> list[str]:
        return _check_ips(value)

    @field_validator("scopes")
    @classmethod
    def _scopes(cls, value: list[ApiScope]) -> list[ApiScope]:
        return list(dict.fromkeys(value))


class ApiClientUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    owner_department_id: str | None = Field(default=None, max_length=32)
    contact: str | None = Field(default=None, max_length=255)
    status: Literal["active", "disabled"] | None = None
    kb_ids: list[str] | None = Field(default=None, min_length=1, max_length=100)
    principals: list[ApiPrincipalRef] | None = Field(default=None, min_length=1, max_length=20)
    scopes: list[ApiScope] | None = Field(default=None, min_length=1)
    rate_limit_per_minute: int | None = Field(default=None, ge=0, le=6000)
    daily_quota: int | None = Field(default=None, ge=0, le=10_000_000)
    ip_allowlist: list[str] | None = Field(default=None, max_length=50)
    expires_at: datetime | None = None
    clear_expires_at: bool = False

    @field_validator("kb_ids")
    @classmethod
    def _kbs(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else _dedupe(value)

    @field_validator("ip_allowlist")
    @classmethod
    def _ips(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else _check_ips(value)

    @field_validator("scopes")
    @classmethod
    def _scopes(cls, value: list[ApiScope] | None) -> list[ApiScope] | None:
        return None if value is None else list(dict.fromkeys(value))


class ApiClientOut(BaseModel):
    id: str
    name: str
    description: str | None
    owner_department_id: str | None
    owner_department_name: str | None = None
    contact: str | None
    status: str
    service_user_id: str
    kbs: list[NamedRef]
    principals: list[ApiPrincipalOut]
    scopes: list[str]
    rate_limit_per_minute: int
    effective_rate_per_minute: int
    daily_quota: int
    ip_allowlist: list[str]
    expires_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime
    updated_at: datetime
    active_keys: int = 0
    calls_today: int = 0


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    expires_at: datetime | None = None


class ApiKeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    prefix: str
    status: str
    expires_at: datetime | None
    last_used_at: datetime | None
    last_used_ip: str | None
    created_at: datetime
    revoked_at: datetime | None


class ApiKeyCreatedOut(ApiKeyOut):
    # Shown once; only its HMAC is stored.
    secret: str


class ApiCallLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    key_id: str | None
    endpoint: str
    status_code: int
    error_code: str | None
    latency_ms: int
    ip: str | None
    query: str | None
    kb_ids: list[str]
    result_count: int
    document_ids: list[str]
    trace_id: str | None
    created_at: datetime


class ApiUsageDay(BaseModel):
    day: str
    calls: int
    errors: int
    avg_latency_ms: float


class ApiUsageOut(BaseModel):
    days: list[ApiUsageDay]
    total_calls: int
    total_errors: int
    by_endpoint: dict[str, int]
    by_status: dict[str, int]


class OpenApiOptionsOut(BaseModel):
    kbs: list[NamedRef]
    departments: list[NamedRef]
    groups: list[NamedRef]
    roles: list[NamedRef]
    scopes: list[str]
    default_rate_per_minute: int
    max_top_k: int


# ---- public (called by agents) --------------------------------------------------------


class OpenRetrieveIn(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    kb_ids: list[str] = Field(default_factory=list, max_length=100)
    top_k: int = Field(default=5, ge=1, le=100)

    @field_validator("query")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must not be blank")
        return value.strip()

    @field_validator("kb_ids")
    @classmethod
    def _kbs(cls, value: list[str]) -> list[str]:
        return _dedupe(value)


class OpenChunkOut(BaseModel):
    rank: int
    chunk_id: str
    document_id: str
    title: str
    kb_id: str
    kb_name: str
    heading_path: list[str]
    content: str
    score: float | None
    page_start: int | None = None
    page_end: int | None = None
    slide_number: int | None = None
    is_ko: bool = False
    # Presigned page/slide image when the document was rasterized at ingest.
    image_url: str | None = None
    image_mime_type: str | None = None
    # Controlled document: content may be truncated for this caller.
    copy_protect: bool = False
    content_truncated: bool = False


class OpenRetrieveOut(BaseModel):
    query: str
    kb_ids: list[str]
    items: list[OpenChunkOut]
    total: int
    trace_id: str | None
    took_ms: float


class OpenChatIn(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    kb_ids: list[str] = Field(default_factory=list, max_length=100)
    conversation_id: str | None = Field(default=None, max_length=32)
    stream: bool = False

    @field_validator("question")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("question must not be blank")
        return value.strip()

    @field_validator("kb_ids")
    @classmethod
    def _kbs(cls, value: list[str]) -> list[str]:
        return _dedupe(value)


class OpenChatOut(BaseModel):
    conversation_id: str
    message_id: str
    answer: str
    grounding: str | None
    citations: list[dict[str, Any]]
    steps: list[dict[str, Any]]
    trace_id: str | None


class OpenKbOut(BaseModel):
    id: str
    name: str
    description: str | None


class OpenWhoAmIOut(BaseModel):
    client_id: str
    name: str
    scopes: list[str]
    kbs: list[OpenKbOut]
    rate_limit_per_minute: int
    daily_quota: int
    on_behalf_of: str | None = None
    acting_user_id: str | None = None
    acting_username: str | None = None


class OpenEntityReadIn(BaseModel):
    """Lookup by entity_id, name/alias, or structured object_type+external_id (one mode)."""

    entity_id: str | None = Field(default=None, max_length=32)
    name: str | None = Field(default=None, max_length=256)
    object_type: str | None = Field(default=None, max_length=64)
    external_id: str | None = Field(default=None, max_length=64)
    source_id: str | None = Field(default=None, max_length=32)

    @model_validator(mode="after")
    def _one_mode(self) -> "OpenEntityReadIn":
        by_id = bool(self.entity_id and self.entity_id.strip())
        by_name = bool(self.name and self.name.strip())
        by_ext = bool(
            self.object_type
            and self.object_type.strip()
            and self.external_id
            and self.external_id.strip()
        )
        if sum((by_id, by_name, by_ext)) != 1:
            raise ValueError(
                "provide exactly one of: entity_id | name | (object_type + external_id)"
            )
        if self.entity_id:
            self.entity_id = self.entity_id.strip()
        if self.name:
            self.name = self.name.strip()
        if self.object_type:
            self.object_type = self.object_type.strip().lower()
        if self.external_id:
            self.external_id = self.external_id.strip()
        if self.source_id:
            self.source_id = self.source_id.strip() or None
        return self


class OpenEntityTermOut(BaseModel):
    id: str
    canonical_name: str
    entity_type: str
    status: str
    aliases: list[str] = Field(default_factory=list)


class OpenRelatedTermOut(BaseModel):
    id: str
    canonical_name: str
    entity_type: str
    kind: str
    direction: str  # out | in


class OpenEntityMirrorOut(BaseModel):
    object_type: str
    object_id: str
    external_id: str
    source_id: str
    label: str
    status: str


class OpenEntityKoOut(BaseModel):
    id: str
    title: str
    ko_type: str
    kb_id: str


class OpenEntityReadOut(BaseModel):
    terminology: OpenEntityTermOut | None = None
    mirror: OpenEntityMirrorOut | None = None
    knowledge_objects: list[OpenEntityKoOut] = Field(default_factory=list)
    related_terms: list[OpenRelatedTermOut] = Field(default_factory=list)


class OpenGraphTraverseIn(BaseModel):
    ko_id: str = Field(min_length=1, max_length=32)
    max_hops: int = Field(default=2, ge=1, le=3)
    relation_types: list[str] = Field(default_factory=list, max_length=20)
    kb_ids: list[str] = Field(default_factory=list, max_length=100)
    direction: Literal["out", "in", "both"] = "both"

    @field_validator("ko_id")
    @classmethod
    def _ko(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("ko_id must not be blank")
        return value.strip()

    @field_validator("kb_ids")
    @classmethod
    def _kbs(cls, value: list[str]) -> list[str]:
        return _dedupe(value)

    @field_validator("relation_types")
    @classmethod
    def _rels(cls, value: list[str]) -> list[str]:
        return _dedupe([v.lower() for v in value])


class OpenGraphNeighborOut(BaseModel):
    ko_id: str
    title: str
    hops: int
    seed_id: str
    ko_type: str
    kb_id: str
    path: str = ""


class OpenGraphSeedOut(BaseModel):
    id: str
    title: str
    ko_type: str
    kb_id: str


class OpenGraphTraverseOut(BaseModel):
    seed: OpenGraphSeedOut
    neighbors: list[OpenGraphNeighborOut] = Field(default_factory=list)
    max_hops: int
    direction: Literal["out", "in", "both"] = "both"


class OpenOntologyDescribeOut(BaseModel):
    namespace: str
    classes: list[str]
    ko_relation_properties: list[str]
    industrial_relation_properties: list[str]
    attribute_schemas: list[dict[str, Any]] = Field(default_factory=list)
    hard_object_relations: list[str]
    soft_object_relations: list[str]
    # OS1: published org extension + scope control
    scope: str = "summary"
    version: str | None = None
    version_id: str | None = None
    version_name: str | None = None
    published_at: str | None = None
    org_entities: list[dict[str, Any]] = Field(default_factory=list)
    evidences: list[dict[str, Any]] = Field(default_factory=list)


class OpenGetObjectIn(BaseModel):
    object_type: str = Field(min_length=1, max_length=64)
    object_id: str | None = Field(default=None, max_length=32)
    external_id: str | None = Field(default=None, max_length=64)
    source_id: str | None = Field(default=None, max_length=32)
    include_neighbors: bool = True
    neighbor_hops: int = Field(default=1, ge=0, le=3)

    @model_validator(mode="after")
    def _id_or_ext(self) -> "OpenGetObjectIn":
        self.object_type = self.object_type.strip().lower()
        oid = (self.object_id or "").strip() or None
        ext = (self.external_id or "").strip() or None
        if bool(oid) == bool(ext):
            raise ValueError("provide exactly one of object_id | external_id")
        self.object_id = oid
        self.external_id = ext
        if self.source_id:
            self.source_id = self.source_id.strip() or None
        return self


class OpenObjectNeighborOut(BaseModel):
    kind: str
    object_id: str
    object_type: str | None = None
    hops: int
    path: str = ""
    via_relation_types: str = ""


class OpenObjectLinkOut(BaseModel):
    """Terminology / KO link attached to a structured object."""

    id: str
    terminology_entity_id: str | None = None
    terminology_name: str | None = None
    ko_id: str | None = None
    ko_title: str | None = None


class OpenObjectIdentifierOut(BaseModel):
    """External identifier under a source system for a canonical entity."""

    system: str
    id_kind: str
    external_id: str
    is_primary: bool = False


class OpenGetObjectOut(BaseModel):
    kind: str = "structured"
    object_type: str
    object_id: str
    external_id: str
    title: str
    status: str
    standard_status: str | None = None
    status_label: str | None = None
    attrs: dict[str, Any] = Field(default_factory=dict)
    derived: dict[str, Any] = Field(default_factory=dict)
    neighbors: list[OpenObjectNeighborOut] = Field(default_factory=list)
    links: list[OpenObjectLinkOut] = Field(default_factory=list)
    canonical_id: str | None = None
    identifiers: list[OpenObjectIdentifierOut] = Field(default_factory=list)
    evidences: list[dict[str, Any]] = Field(default_factory=list)


class OpenQueryObjectsIn(BaseModel):
    object_type: str = Field(min_length=1, max_length=64)
    status: str | None = Field(default=None, max_length=32)
    q: str | None = Field(default=None, max_length=200)
    line_external_id: str | None = Field(default=None, max_length=64)
    equipment_external_id: str | None = Field(default=None, max_length=64)
    event_type: str | None = Field(default=None, max_length=32)
    occurred_from: datetime | None = None
    occurred_to: datetime | None = None
    due_before: datetime | None = Field(
        default=None, description="Filter production_order by attrs.due_date < due_before"
    )
    risk_status: str | None = Field(
        default=None,
        max_length=32,
        description="Filter by attrs.risk_status (e.g. delayed|at_risk)",
    )
    page: int = Field(default=1, ge=1)
    size: int = Field(default=20, ge=1, le=100)

    @field_validator("object_type")
    @classmethod
    def _ot(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("event_type")
    @classmethod
    def _et(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip().lower()
        return text or None

    @field_validator("risk_status")
    @classmethod
    def _risk(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip().lower()
        return text or None


class OpenQueryObjectItem(BaseModel):
    object_type: str
    object_id: str
    external_id: str
    title: str
    status: str
    attrs: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime | None = None
    ended_at: datetime | None = None
    event_type: str | None = None


class OpenQueryObjectsOut(BaseModel):
    items: list[OpenQueryObjectItem]
    total: int
    page: int
    size: int


class OpenAggregateObjectsIn(BaseModel):
    """Count (or future metrics) over structured objects with ACL applied."""

    object_type: str = Field(min_length=1, max_length=64)
    metric: Literal["count"] = "count"
    status: str | None = Field(default=None, max_length=32)
    event_type: str | None = Field(default=None, max_length=32)
    equipment_external_id: str | None = Field(default=None, max_length=64)
    line_external_id: str | None = Field(default=None, max_length=64)
    occurred_from: datetime | None = None
    occurred_to: datetime | None = None

    @field_validator("object_type")
    @classmethod
    def _ot(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("event_type")
    @classmethod
    def _et(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip().lower()
        return text or None


class OpenAggregateObjectsOut(BaseModel):
    object_type: str
    metric: str
    value: int
    filters: dict[str, Any] = Field(default_factory=dict)


class OpenTraverseIn(BaseModel):
    """Unified directed traverse: KO graph or industrial object_relations."""

    mode: Literal["ko", "object"] = "ko"
    ko_id: str | None = Field(default=None, max_length=32)
    kind: str | None = Field(default=None, max_length=16)
    object_id: str | None = Field(default=None, max_length=32)
    object_type: str | None = Field(default=None, max_length=64)
    direction: Literal["out", "in", "both"] = "out"
    relation_types: list[str] = Field(default_factory=list, max_length=20)
    max_hops: int = Field(default=2, ge=1, le=3)
    kb_ids: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def _mode_fields(self) -> "OpenTraverseIn":
        self.relation_types = _dedupe([v.lower() for v in self.relation_types])
        self.kb_ids = _dedupe(self.kb_ids)
        if self.mode == "ko":
            if not (self.ko_id and self.ko_id.strip()):
                raise ValueError("ko_id is required when mode=ko")
            self.ko_id = self.ko_id.strip()
        else:
            if not (self.kind and self.object_id):
                raise ValueError("kind and object_id are required when mode=object")
            self.kind = self.kind.strip().lower()
            self.object_id = self.object_id.strip()
            self.object_type = (self.object_type or "").strip().lower() or None
        return self


class OpenTraverseNeighborOut(BaseModel):
    kind: str
    object_id: str
    object_type: str | None = None
    title: str | None = None
    hops: int
    path: str = ""
    via_relation_types: str = ""
    ko_type: str | None = None
    kb_id: str | None = None


class OpenTraverseOut(BaseModel):
    mode: Literal["ko", "object"]
    direction: Literal["out", "in", "both"]
    max_hops: int
    seed: dict[str, Any]
    neighbors: list[OpenTraverseNeighborOut] = Field(default_factory=list)


class OpenActionTypeOut(BaseModel):
    name: str
    description: str | None = None
    input_schema: dict[str, Any] = Field(default_factory=dict)
    preconditions: dict[str, Any] = Field(default_factory=dict)
    risk: str
    systems: list[str] = Field(default_factory=list)


class OpenActionListOut(BaseModel):
    items: list[OpenActionTypeOut] = Field(default_factory=list)


class OpenActionApproveIn(BaseModel):
    action_type: str = Field(min_length=1, max_length=128)
    input: dict[str, Any] = Field(default_factory=dict)
    acknowledge_risk: bool = False


class OpenActionApproveOut(BaseModel):
    approval_id: str
    expires_at: datetime
    action_type: str


class OpenActionInvokeIn(BaseModel):
    action_type: str = Field(min_length=1, max_length=128)
    input: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=1, max_length=64)
    approval_id: str | None = Field(default=None, max_length=32)
    dry_run: bool = False


class OpenActionInvokeOut(BaseModel):
    status: str
    action_type: str
    execution_id: str | None = None
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    approval_id: str | None = None
    rule_verdict: str | None = None
