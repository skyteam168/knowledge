from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

KindLiteral = Literal["chat", "embedding", "rerank"]
SceneLiteral = Literal["chat", "chat_fallback", "embedding", "rerank"]


def _check_url(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip().rstrip("/")
    if not value:
        return None
    if not value.startswith(("http://", "https://")):
        raise ValueError("must start with http:// or https://")
    return value


class ProviderOut(BaseModel):
    id: str
    name: str
    base_url: str
    has_api_key: bool
    api_key_hint: str | None
    enabled: bool
    source: str
    model_count: int
    in_use: bool
    last_synced_at: datetime | None
    created_at: datetime


class ProviderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    base_url: str = Field(min_length=1, max_length=512)
    api_key: str | None = Field(default=None, max_length=512)
    enabled: bool = True

    _url = field_validator("base_url")(_check_url)


class ProviderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    base_url: str | None = Field(default=None, max_length=512)
    # None keeps the stored key; use clear_api_key to remove it.
    api_key: str | None = Field(default=None, max_length=512)
    clear_api_key: bool = False
    enabled: bool | None = None

    _url = field_validator("base_url")(_check_url)


class SyncResultOut(BaseModel):
    listed: int
    added: int
    missing: list[str] = Field(description="Stored synced models no longer listed")


class ModelOut(BaseModel):
    id: str
    provider_id: str
    provider_name: str
    provider_enabled: bool
    name: str
    kind: KindLiteral
    origin: str
    base_url: str | None
    path: str | None
    effective_base_url: str
    detected_dim: int | None
    scenes: list[SceneLiteral]
    last_check_status: str | None
    last_check_at: datetime | None
    last_check_latency_ms: int | None
    last_check_message: str | None


class ModelCreate(BaseModel):
    provider_id: str
    name: str = Field(min_length=1, max_length=255)
    kind: KindLiteral
    base_url: str | None = Field(default=None, max_length=512)
    path: str | None = Field(default=None, max_length=128)

    _url = field_validator("base_url")(_check_url)


class ModelUpdate(BaseModel):
    kind: KindLiteral | None = None
    base_url: str | None = Field(default=None, max_length=512)
    path: str | None = Field(default=None, max_length=128)

    _url = field_validator("base_url")(_check_url)


class CheckOut(BaseModel):
    ok: bool
    latency_ms: int
    first_token_ms: int | None = None
    message: str
    sample: str | None = None
    dim: int | None = None
    warning: str | None = None
    checked_at: datetime


class SceneOut(BaseModel):
    scene: SceneLiteral
    kind: KindLiteral
    model: str | None
    base_url: str | None
    provider_name: str | None
    model_id: str | None
    # page = chosen in this page, config = deployment configuration, index = pinned by the
    # active index generation.
    source: Literal["page", "config", "index"]
    editable: bool
    dim: int | None = None
    note: str | None = None
    last_check_status: str | None = None
    last_check_at: datetime | None = None


class OverviewOut(BaseModel):
    scenes: list[SceneOut]
    refresh_seconds: float


class RoutesIn(BaseModel):
    chat_model_id: str | None = Field(
        default=None, description="None = back to the deployment configuration"
    )
    chat_fallback_model_id: str | None = None
    force: bool = Field(default=False, description="Save even if the check fails")
