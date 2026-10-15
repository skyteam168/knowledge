from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SourceType = Literal["wecom", "dingtalk", "weaver", "excel"]


class DirectorySourceCreate(BaseModel):
    type: SourceType
    name: str = Field(min_length=1, max_length=128)
    is_primary: bool = False
    enabled: bool = True
    # 0 = manual only; minimum automatic interval is 10 minutes.
    sync_interval_minutes: int = Field(default=0, ge=0, le=7 * 24 * 60)
    config: dict[str, Any] = Field(default_factory=dict)


class DirectorySourceUpdate(BaseModel):
    """Secret fields left empty in `config` keep their stored value."""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    is_primary: bool | None = None
    enabled: bool | None = None
    sync_interval_minutes: int | None = Field(default=None, ge=0, le=7 * 24 * 60)
    config: dict[str, Any] | None = None


class DirectorySourceOut(BaseModel):
    id: str
    type: SourceType
    name: str
    is_primary: bool
    enabled: bool
    sync_interval_minutes: int
    # Secrets are never returned: their keys are listed in `secrets_set` instead.
    config: dict[str, Any]
    secrets_set: list[str]
    login_supported: bool
    login_configured: bool
    last_sync_at: datetime | None
    last_status: str | None
    last_run_id: str | None
    next_sync_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DirectoryTestRequest(BaseModel):
    type: SourceType
    config: dict[str, Any] = Field(default_factory=dict)
    # Editing an existing source: empty secrets fall back to the stored ones.
    source_id: str | None = None


class DirectoryTestResult(BaseModel):
    ok: bool
    departments: int = 0
    users: int = 0
    active_users: int = 0
    warnings: list[str] = []
    error: str | None = None
    duration_ms: int = 0


class SyncRequest(BaseModel):
    mode: Literal["preview", "apply"] = "preview"
    force: bool = False


class SyncRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_id: str
    mode: str
    status: str
    forced: bool
    stats: dict[str, Any]
    error: str | None
    triggered_by: str | None
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int


class SyncRunDetail(SyncRunOut):
    changes: dict[str, Any]
