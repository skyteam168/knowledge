"""MySQL table connector for equipment mirror rows (S1.2).

Password is never stored in ``StructuredSource.meta`` — use ``password_env``.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

import pymysql
from pymysql.cursors import DictCursor

from app.core.config import Settings
from app.core.exceptions import ValidationAppError
from app.services.structured.connectors.base import (
    ConnectorError,
    DeviceRow,
    EquipmentConnector,
    EquipmentSnapshot,
    FetchResult,
    StructuredConnectorConfig,
    SyncCursor,
    advance_watermark,
)

MysqlConnectFn = Callable[..., Any]

DEFAULT_DEVICE_FIELDS = {
    "external_id": (
        "external_id",
        "device_number",
        "device_code",
        "device_id",
        "device_no",
        "equip_code",
        "code",
        "id",
    ),
    "name": ("name", "device_name", "equip_name", "title", "label"),
    "status": ("status", "device_status", "state"),
    "location": (
        "location",
        "device_location",
        "workshop",
        "area",
        "site",
        "position",
        "plant",
        "factory",
    ),
    "updated_at": (
        "updated_at",
        "update_time",
        "modify_time",
        "gmt_modified",
        "last_update_time",
        "changed_at",
        "create_time",
    ),
}


def _pick(row: dict[str, Any], *keys: str) -> str:
    lower = {str(k).lower(): k for k in row}
    for key in keys:
        real = lower.get(key.lower())
        if real is None:
            continue
        val = row.get(real)
        if val is None:
            continue
        text = str(val).strip()
        if text:
            return text
    return ""


def _mapped_keys(
    column_map: dict[str, str], field: str, defaults: Sequence[str]
) -> tuple[str, ...]:
    mapped = column_map.get(field)
    if mapped:
        return (mapped, *defaults)
    return tuple(defaults)


def _normalize_ts(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value
        return dt.isoformat()
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    # MySQL DATETIME often "YYYY-MM-DD HH:MM:SS"
    if " " in text and "T" not in text:
        text = text.replace(" ", "T", 1)
    try:
        datetime.fromisoformat(text)
    except ValueError:
        return None
    return text


def _quote_ident(name: str) -> str:
    if not name or any(c in name for c in ("`", ";", "\x00")):
        raise ValidationAppError("Invalid SQL identifier", detail={"name": name})
    return f"`{name}`"


class MysqlEquipmentConnector(EquipmentConnector):
    kind = "mysql"

    def __init__(
        self,
        config: StructuredConnectorConfig,
        settings: Settings,
        *,
        connect_fn: MysqlConnectFn | None = None,
    ) -> None:
        super().__init__(config, settings)
        self._connect_fn = connect_fn or pymysql.connect

    def _mysql(self):
        cfg = self.config.mysql
        assert cfg is not None
        password = cfg.password
        if not password and cfg.password_env:
            password = os.environ.get(cfg.password_env) or ""
        if not password:
            raise ValidationAppError(
                "MySQL password missing",
                detail={"password_env": cfg.password_env},
            )
        try:
            return self._connect_fn(
                host=cfg.host,
                port=cfg.port,
                user=cfg.user,
                password=password,
                database=cfg.database,
                charset=cfg.charset,
                connect_timeout=cfg.connect_timeout_seconds,
                cursorclass=DictCursor,
            )
        except Exception as exc:
            raise ConnectorError(
                "MySQL connection failed",
                detail={"host": cfg.host, "port": cfg.port, "error": str(exc)},
            ) from exc

    def _device_map(self) -> dict[str, str]:
        return dict(self.config.column_map.get("devices") or {})

    def _fetch_devices(
        self, conn: Any, *, since: str | None
    ) -> tuple[list[DeviceRow], str | None, list[str]]:
        cfg = self.config.mysql
        assert cfg is not None
        cmap = self._device_map()
        updated_keys = _mapped_keys(
            cmap, "updated_at", DEFAULT_DEVICE_FIELDS["updated_at"]
        )
        updated_col = cmap.get("updated_at")
        table = _quote_ident(cfg.table)
        sql = f"SELECT * FROM {table}"
        params: list[Any] = []
        warnings: list[str] = []
        if since:
            if updated_col:
                sql += f" WHERE {_quote_ident(updated_col)} > %s"
                params.append(since.replace("T", " ").split("+")[0].split("Z")[0])
            else:
                warnings.append(
                    "incremental requested but column_map.devices.updated_at unset; "
                    "fetched full table and filtered in memory"
                )
        sql += f" LIMIT {max(1, min(cfg.row_limit, 100_000))}"
        with conn.cursor() as cur:
            cur.execute(sql, params)
            raw_rows = list(cur.fetchall())
        devices: list[DeviceRow] = []
        high: str | None = since
        for r in raw_rows:
            row = {str(k): v for k, v in dict(r).items()}
            external_id = _pick(
                row, *_mapped_keys(cmap, "external_id", DEFAULT_DEVICE_FIELDS["external_id"])
            )
            name = _pick(row, *_mapped_keys(cmap, "name", DEFAULT_DEVICE_FIELDS["name"]))
            if not external_id or not name:
                continue
            status = (
                _pick(row, *_mapped_keys(cmap, "status", DEFAULT_DEVICE_FIELDS["status"]))
                or "active"
            )
            location = (
                _pick(
                    row, *_mapped_keys(cmap, "location", DEFAULT_DEVICE_FIELDS["location"])
                )
                or None
            )
            watermark = None
            for key in updated_keys:
                watermark = _normalize_ts(row.get(key) if key in row else None)
                if watermark is None:
                    # case-insensitive
                    watermark = _normalize_ts(
                        next(
                            (
                                row[rk]
                                for rk in row
                                if rk.lower() == key.lower()
                            ),
                            None,
                        )
                    )
                if watermark:
                    break
            high = advance_watermark(high, watermark)
            # Only skip columns actually used as identity/name — keep asset codes
            # (e.g. device_number) in meta even when external_id maps to `id`.
            skip = {k.lower() for k in (cmap.get("external_id"), cmap.get("name")) if k}
            if not skip:
                skip = {"id", "name", "device_name"}
            preferred_extra = (
                "device_number",
                "device_code",
                "serial",
                "brand",
                "device_model",
                "department",
                "classify",
                "type",
            )
            extras: dict[str, Any] = {}
            for key in preferred_extra:
                val = _pick(row, key)
                if not val or key.lower() in skip:
                    continue
                extras[f"col_{key}"] = val[:200]
            for k, v in row.items():
                if k.lower() in skip or v is None or f"col_{k}" in extras:
                    continue
                if len(extras) >= 12:
                    break
                text = v.isoformat() if isinstance(v, datetime) else str(v)
                if len(text) > 200:
                    text = text[:200]
                extras[f"col_{k}"] = text
            meta = {"connector": "mysql", "table": cfg.table, **extras}
            if since and not cmap.get("updated_at"):
                # In-memory incremental when SQL WHERE could not be applied.
                if not watermark or not _after_cursor(watermark, since):
                    continue
            devices.append(
                DeviceRow(
                    external_id=external_id[:64],
                    name=name[:256],
                    status=status[:32],
                    location=(location[:256] if location else None),
                    meta=meta,
                )
            )
        return devices, high, warnings

    async def fetch(
        self,
        *,
        cursor: SyncCursor | None = None,
        force_full: bool = False,
    ) -> FetchResult:
        cfg = self.config.mysql
        assert cfg is not None
        use_cursor = (
            self.config.incremental.enabled
            and not force_full
            and cursor is not None
            and bool(cursor.watermarks)
        )
        mode = "incremental" if use_cursor else "full"
        since = cursor.watermarks.get("devices") if use_cursor and cursor else None
        try:
            conn = self._mysql()
        except ConnectorError:
            raise
        try:
            devices, high, warnings = self._fetch_devices(conn, since=since)
        except ConnectorError:
            raise
        except Exception as exc:
            raise ConnectorError(
                "MySQL query failed",
                detail={"table": cfg.table, "error": str(exc)},
            ) from exc
        finally:
            try:
                conn.close()
            except Exception:
                pass

        next_cursor = None
        if self.config.incremental.enabled:
            watermarks = dict(cursor.watermarks) if cursor else {}
            if high:
                watermarks["devices"] = high
            next_cursor = SyncCursor(watermarks=watermarks)

        return FetchResult(
            snapshot=EquipmentSnapshot(
                devices=devices,
                work_orders=[],
                spare_parts=[],
                warnings=warnings,
            ),
            next_cursor=next_cursor,
            mode=mode,  # type: ignore[arg-type]
        )


def _after_cursor(value: str | None, since: str | None) -> bool:
    if not since:
        return True
    if not value:
        return False
    try:
        row_dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
    except ValueError:
        return False
    return row_dt > since_dt


def probe_mysql_table(
    *,
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
    table: str,
    charset: str = "utf8mb4",
    connect_fn: MysqlConnectFn | None = None,
    sample_limit: int = 3,
) -> dict[str, Any]:
    """Read-only schema + sample rows for Steward mapping (CLI)."""
    connect = connect_fn or pymysql.connect
    conn = connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        charset=charset,
        connect_timeout=10,
        cursorclass=DictCursor,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_KEY, COLUMN_TYPE "
                "FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s "
                "ORDER BY ORDINAL_POSITION",
                (database, table),
            )
            columns = list(cur.fetchall())
            if not columns:
                raise ValidationAppError(
                    "Table not found",
                    detail={"database": database, "table": table},
                )
            cur.execute(
                f"SELECT COUNT(*) AS n FROM {_quote_ident(table)}"
            )
            count_row = cur.fetchone() or {}
            cur.execute(
                f"SELECT * FROM {_quote_ident(table)} LIMIT %s",
                (max(1, min(sample_limit, 20)),),
            )
            samples = list(cur.fetchall())
        return {
            "database": database,
            "table": table,
            "columns": [
                {
                    "name": c["COLUMN_NAME"],
                    "type": c["COLUMN_TYPE"],
                    "nullable": c["IS_NULLABLE"],
                    "key": c["COLUMN_KEY"],
                }
                for c in columns
            ],
            "row_count": int(count_row.get("n") or 0),
            "samples": [
                {str(k): (v.isoformat() if isinstance(v, datetime) else v) for k, v in dict(r).items()}
                for r in samples
            ],
        }
    finally:
        conn.close()
