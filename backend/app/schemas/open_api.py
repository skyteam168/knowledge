import ipaddress
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
    is_ko: bool = False


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
