"""SQL Server connector: schema probe + equipment table pull.

Password is never stored in ``StructuredSource.meta`` — use ``password_env``.
Uses ``pymssql`` (already a project dependency).
"""

from __future__ import annotations

import os
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pymssql

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
from app.services.structured.connectors.mysql import (
    DEFAULT_DEVICE_FIELDS,
    _after_cursor,
    _mapped_keys,
    _normalize_ts,
    _pick,
)

DEFAULT_SCHEMA = "dbo"


def resolve_mssql_password(
    *,
    password: str | None = None,
    password_env: str = "MES_MSSQL_PASSWORD",
) -> str:
    if password:
        return password
    env_name = (password_env or "").strip() or "MES_MSSQL_PASSWORD"
    value = os.environ.get(env_name) or ""
    if not value:
        raise ValidationAppError(
            "SQL Server password missing",
            detail={"password_env": env_name},
        )
    return value


def _quote_ident(name: str) -> str:
    if not name or any(c in name for c in ("]", ";", "\x00")):
        raise ValidationAppError("Invalid SQL identifier", detail={"name": name})
    return f"[{name}]"


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    return value


def _connect(
    *,
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
    connect_timeout: float = 10.0,
    login_timeout: float | None = None,
) -> Any:
    try:
        return pymssql.connect(
            server=host,
            port=port,
            user=user,
            password=password,
            database=database,
            login_timeout=int(login_timeout or connect_timeout),
            timeout=int(connect_timeout),
            as_dict=True,
        )
    except Exception as exc:
        raise ConnectorError(
            "SQL Server connection failed",
            detail={"host": host, "port": port, "error": str(exc)},
        ) from exc


def list_mssql_tables(
    *,
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
    schema: str = DEFAULT_SCHEMA,
    connect_timeout: float = 10.0,
) -> list[dict[str, Any]]:
    """List base tables / views in a schema (read-only)."""
    schema_name = (schema or DEFAULT_SCHEMA).strip() or DEFAULT_SCHEMA
    conn = _connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        connect_timeout=connect_timeout,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT TABLE_NAME AS name,
                       TABLE_TYPE AS table_type
                FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_SCHEMA = %s
                ORDER BY TABLE_NAME
                """,
                (schema_name,),
            )
            rows = list(cur.fetchall() or [])
            approx: dict[str, int] = {}
            try:
                cur.execute(
                    """
                    SELECT t.name AS name, SUM(p.rows) AS approx_rows
                    FROM sys.tables t
                    JOIN sys.partitions p
                      ON p.object_id = t.object_id AND p.index_id IN (0, 1)
                    WHERE SCHEMA_NAME(t.schema_id) = %s
                    GROUP BY t.name
                    """,
                    (schema_name,),
                )
                for r in cur.fetchall() or []:
                    if r.get("name"):
                        approx[str(r["name"])] = int(r.get("approx_rows") or 0)
            except Exception:
                approx = {}
        return [
            {
                "name": str(r.get("name") or ""),
                "table_type": str(r.get("table_type") or ""),
                "approx_rows": approx.get(str(r.get("name") or ""), 0),
                "comment": None,
                "schema": schema_name,
            }
            for r in rows
            if r.get("name")
        ]
    finally:
        conn.close()


def probe_mssql_table(
    *,
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
    table: str,
    schema: str = DEFAULT_SCHEMA,
    sample_limit: int = 3,
    connect_timeout: float = 10.0,
) -> dict[str, Any]:
    """Read-only schema + sample rows for ontology import."""
    schema_name = (schema or DEFAULT_SCHEMA).strip() or DEFAULT_SCHEMA
    table_name = table.strip()
    conn = _connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        connect_timeout=connect_timeout,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT c.COLUMN_NAME AS column_name,
                       c.DATA_TYPE AS data_type,
                       c.IS_NULLABLE AS is_nullable,
                       c.CHARACTER_MAXIMUM_LENGTH AS character_maximum_length,
                       CASE WHEN pk.COLUMN_NAME IS NOT NULL THEN 'PRI' ELSE '' END AS column_key
                FROM INFORMATION_SCHEMA.COLUMNS c
                LEFT JOIN (
                    SELECT ku.COLUMN_NAME
                    FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
                    JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE ku
                      ON tc.CONSTRAINT_NAME = ku.CONSTRAINT_NAME
                     AND tc.TABLE_SCHEMA = ku.TABLE_SCHEMA
                    WHERE tc.TABLE_SCHEMA = %s
                      AND tc.TABLE_NAME = %s
                      AND tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
                ) pk ON pk.COLUMN_NAME = c.COLUMN_NAME
                WHERE c.TABLE_SCHEMA = %s AND c.TABLE_NAME = %s
                ORDER BY c.ORDINAL_POSITION
                """,
                (schema_name, table_name, schema_name, table_name),
            )
            columns = list(cur.fetchall() or [])
            if not columns:
                raise ValidationAppError(
                    "Table not found",
                    detail={
                        "database": database,
                        "schema": schema_name,
                        "table": table_name,
                    },
                )
            fq = f"{_quote_ident(schema_name)}.{_quote_ident(table_name)}"
            cur.execute(f"SELECT COUNT(*) AS n FROM {fq}")
            count_row = cur.fetchone() or {}
            limit = max(1, min(sample_limit, 20))
            cur.execute(f"SELECT TOP ({limit}) * FROM {fq}")
            samples = list(cur.fetchall() or [])
        col_out = []
        for c in columns:
            name = str(c.get("column_name") or "")
            data_type = str(c.get("data_type") or "nvarchar")
            maxlen = c.get("character_maximum_length")
            type_label = f"{data_type}({maxlen})" if maxlen else data_type
            col_out.append(
                {
                    "name": name,
                    "type": type_label,
                    "nullable": str(c.get("is_nullable") or ""),
                    "key": str(c.get("column_key") or ""),
                }
            )
        return {
            "database": database,
            "schema": schema_name,
            "table": table_name,
            "columns": col_out,
            "row_count": int(count_row.get("n") or 0),
            "samples": [
                {str(k): _jsonable(v) for k, v in dict(r).items()} for r in samples
            ],
        }
    finally:
        conn.close()


class MssqlEquipmentConnector(EquipmentConnector):
    kind = "mssql"

    def __init__(self, config: StructuredConnectorConfig, settings: Settings) -> None:
        super().__init__(config, settings)

    def _cfg(self):
        cfg = self.config.mssql
        assert cfg is not None
        return cfg

    def _connect(self) -> Any:
        cfg = self._cfg()
        password = resolve_mssql_password(
            password=cfg.password, password_env=cfg.password_env
        )
        return _connect(
            host=cfg.host,
            port=cfg.port,
            user=cfg.user,
            password=password,
            database=cfg.database,
            connect_timeout=float(cfg.connect_timeout_seconds),
        )

    def _device_map(self) -> dict[str, str]:
        return dict(self.config.column_map.get("devices") or {})

    def _fetch_devices(
        self, conn: Any, *, since: str | None
    ) -> tuple[list[DeviceRow], str | None, list[str]]:
        cfg = self._cfg()
        cmap = self._device_map()
        updated_keys = _mapped_keys(
            cmap, "updated_at", DEFAULT_DEVICE_FIELDS["updated_at"]
        )
        updated_col = cmap.get("updated_at")
        schema = (cfg.schema or DEFAULT_SCHEMA).strip() or DEFAULT_SCHEMA
        fq = f"{_quote_ident(schema)}.{_quote_ident(cfg.table)}"
        sql = f"SELECT TOP ({max(1, min(cfg.row_limit, 100_000))}) * FROM {fq}"
        params: tuple[Any, ...] = ()
        warnings: list[str] = []
        if since:
            if updated_col:
                sql = (
                    f"SELECT TOP ({max(1, min(cfg.row_limit, 100_000))}) * FROM {fq} "
                    f"WHERE {_quote_ident(updated_col)} > %s"
                )
                params = (since,)
            else:
                warnings.append(
                    "incremental requested but column_map.devices.updated_at unset; "
                    "fetched full table and filtered in memory"
                )
        with conn.cursor() as cur:
            cur.execute(sql, params)
            raw_rows = list(cur.fetchall() or [])
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
            location = _pick(
                row, *_mapped_keys(cmap, "location", DEFAULT_DEVICE_FIELDS["location"])
            )
            watermark = None
            for key in updated_keys:
                raw = row.get(key)
                if raw is None:
                    lower = {str(k).lower(): k for k in row}
                    real = lower.get(key.lower())
                    raw = row.get(real) if real else None
                watermark = _normalize_ts(raw)
                if watermark:
                    break
            high = advance_watermark(high, watermark)
            extras: dict[str, Any] = {}
            for k, v in row.items():
                if len(extras) >= 12:
                    break
                text = str(_jsonable(v))
                if len(text) > 200:
                    text = text[:200]
                extras[f"col_{k}"] = text
            meta = {
                "connector": "mssql",
                "schema": schema,
                "table": cfg.table,
                **extras,
            }
            if since and not cmap.get("updated_at"):
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
        import asyncio

        cfg = self._cfg()
        use_cursor = (
            self.config.incremental.enabled
            and not force_full
            and cursor is not None
            and bool(cursor.watermarks)
        )
        mode = "incremental" if use_cursor else "full"
        since = cursor.watermarks.get("devices") if use_cursor and cursor else None

        def _run() -> tuple[list[DeviceRow], str | None, list[str]]:
            conn = self._connect()
            try:
                return self._fetch_devices(conn, since=since)
            finally:
                conn.close()

        try:
            devices, high, warnings = await asyncio.to_thread(_run)
        except ConnectorError:
            raise
        except Exception as exc:
            raise ConnectorError(
                "SQL Server query failed",
                detail={"table": cfg.table, "error": str(exc)},
            ) from exc

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
