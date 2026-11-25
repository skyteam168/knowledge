"""Shared snapshot shapes and connector factory for structured equipment sync."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field, model_validator

from app.core.config import Settings
from app.core.exceptions import AppError, ValidationAppError


class ConnectorError(AppError):
    status_code = 502
    code = "STRUCTURED_CONNECTOR_ERROR"
    message = "Structured source request failed"


class DeviceRow(BaseModel):
    external_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=256)
    status: str = Field(default="active", max_length=32)
    location: str | None = Field(default=None, max_length=256)
    meta: dict[str, Any] = Field(default_factory=dict)


class WorkOrderRow(BaseModel):
    external_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=512)
    status: str = Field(default="open", max_length=32)
    device_external_id: str | None = Field(default=None, max_length=64)
    opened_at: datetime | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class SparePartRow(BaseModel):
    external_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=256)
    sku: str | None = Field(default=None, max_length=64)
    qty_on_hand: float = 0.0
    meta: dict[str, Any] = Field(default_factory=dict)


class EquipmentSnapshot(BaseModel):
    devices: list[DeviceRow] = Field(default_factory=list)
    work_orders: list[WorkOrderRow] = Field(default_factory=list)
    spare_parts: list[SparePartRow] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CsvPaths(BaseModel):
    devices: str | None = None
    work_orders: str | None = None
    spare_parts: str | None = None


class RestPaths(BaseModel):
    devices: str | None = "/devices"
    work_orders: str | None = "/work-orders"
    spare_parts: str | None = "/spare-parts"


class RestConfig(BaseModel):
    base_url: str = Field(min_length=1)
    bearer_token: str | None = None
    bearer_env: str | None = None
    paths: RestPaths = Field(default_factory=RestPaths)


class MysqlConfig(BaseModel):
    """MySQL / MariaDB table pull. Password via env — never commit secrets into meta."""

    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=3306, ge=1, le=65535)
    database: str = Field(min_length=1, max_length=128)
    user: str = Field(min_length=1, max_length=128)
    password_env: str = Field(default="MES_MYSQL_PASSWORD", min_length=1, max_length=128)
    """Environment variable holding the DB password."""
    password: str | None = Field(default=None, max_length=256)
    """Optional inline password for tests only; prefer password_env in production."""
    table: str = Field(default="device_info", min_length=1, max_length=128)
    charset: str = Field(default="utf8mb4", min_length=1, max_length=32)
    connect_timeout_seconds: int = Field(default=10, ge=1, le=120)
    row_limit: int = Field(default=20_000, ge=1, le=100_000)


class IncrementalConfig(BaseModel):
    """S1: cursor / watermark incremental pull (not full re-poll every time)."""

    enabled: bool = False
    """When true, fetch only rows newer than stored watermarks."""

    field: str = Field(default="updated_at", min_length=1, max_length=64)
    """Row / CSV column used as the change watermark."""

    param: str = Field(default="updated_since", min_length=1, max_length=64)
    """REST query parameter that receives the previous watermark."""


class SyncCursor(BaseModel):
    """Per-object-kind ISO watermarks persisted on ``StructuredSource.meta.sync_cursor``."""

    watermarks: dict[str, str] = Field(default_factory=dict)
    mode: Literal["updated_at"] = "updated_at"


class FetchResult(BaseModel):
    snapshot: EquipmentSnapshot
    next_cursor: SyncCursor | None = None
    mode: Literal["full", "incremental"] = "full"


class StructuredConnectorConfig(BaseModel):
    """Parsed from ``StructuredSource.meta`` (connector keys only)."""

    connector: Literal["csv", "rest", "mysql"]
    sync_interval_minutes: int = Field(default=0, ge=0, le=10080)
    csv: CsvPaths | None = None
    rest: RestConfig | None = None
    mysql: MysqlConfig | None = None
    column_map: dict[str, dict[str, str]] = Field(default_factory=dict)
    incremental: IncrementalConfig = Field(default_factory=IncrementalConfig)

    @model_validator(mode="after")
    def _require_connector_block(self) -> StructuredConnectorConfig:
        if self.connector == "csv":
            if self.csv is None or not any(
                (self.csv.devices, self.csv.work_orders, self.csv.spare_parts)
            ):
                raise ValueError("csv connector requires at least one csv.* path")
        elif self.connector == "rest":
            if self.rest is None or not self.rest.base_url.strip():
                raise ValueError("rest connector requires rest.base_url")
        elif self.connector == "mysql":
            if self.mysql is None:
                raise ValueError("mysql connector requires mysql.{host,database,user,table}")
        return self


def parse_connector_config(meta: dict[str, Any] | None) -> StructuredConnectorConfig | None:
    """Return connector config when ``meta.connector`` is set; else None (manual source)."""
    raw = dict(meta or {})
    if not raw.get("connector"):
        return None
    try:
        return StructuredConnectorConfig.model_validate(raw)
    except Exception as exc:
        raise ValidationAppError(
            "Invalid structured connector meta",
            detail={"error": str(exc)},
        ) from exc


def parse_sync_cursor(meta: dict[str, Any] | None) -> SyncCursor | None:
    raw = (meta or {}).get("sync_cursor")
    if not isinstance(raw, dict):
        return None
    try:
        return SyncCursor.model_validate(raw)
    except Exception:
        return None


def advance_watermark(current: str | None, candidate: str | None) -> str | None:
    """Return the later ISO timestamp; invalid candidates are ignored."""
    if not candidate:
        return current
    try:
        cand_dt = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError:
        return current
    if current is None:
        return candidate
    try:
        cur_dt = datetime.fromisoformat(current.replace("Z", "+00:00"))
    except ValueError:
        return candidate
    return candidate if cand_dt >= cur_dt else current


class EquipmentConnector(ABC):
    """Pulls an equipment snapshot; never writes upstream."""

    kind: ClassVar[str]

    def __init__(self, config: StructuredConnectorConfig, settings: Settings) -> None:
        self.config = config
        self.settings = settings

    @abstractmethod
    async def fetch(
        self,
        *,
        cursor: SyncCursor | None = None,
        force_full: bool = False,
    ) -> FetchResult: ...


def build_connector(
    config: StructuredConnectorConfig,
    settings: Settings,
    *,
    transport: Any | None = None,
) -> EquipmentConnector:
    if config.connector == "csv":
        from app.services.structured.connectors.csv import CsvEquipmentConnector

        return CsvEquipmentConnector(config, settings)
    if config.connector == "rest":
        from app.services.structured.connectors.rest import RestEquipmentConnector

        return RestEquipmentConnector(config, settings, transport=transport)
    if config.connector == "mysql":
        from app.services.structured.connectors.mysql import MysqlEquipmentConnector

        return MysqlEquipmentConnector(config, settings)
    raise ValidationAppError(f"Unknown connector: {config.connector}")
