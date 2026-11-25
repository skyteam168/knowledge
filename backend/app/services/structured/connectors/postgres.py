"""PostgreSQL connector: schema probe + equipment table pull.

Password is never stored in ``StructuredSource.meta`` — use ``password_env``.
"""

from __future__ import annotations

import os
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import asyncpg

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

DEFAULT_SCHEMA = "public"


def resolve_postgres_password(
    *,
    password: str | None = None,
    password_env: str = "MES_PG_PASSWORD",
) -> str:
    if password:
        return password
    env_name = (password_env or "").strip() or "MES_PG_PASSWORD"
    value = os.environ.get(env_name) or ""
    if not value:
        raise ValidationAppError(
            "PostgreSQL password missing",
            detail={"password_env": env_name},
        )
    return value


def _quote_ident(name: str) -> str:
    if not name or any(c in name for c in ('"', ";", "\x00")):
        raise ValidationAppError("Invalid SQL identifier", detail={"name": name})
    return f'"{name}"'


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
    if isinstance(value, (bytes, memoryview)):
        return bytes(value).hex()
    return value


async def list_postgres_tables(
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
    try:
        conn = await asyncpg.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            timeout=connect_timeout,
        )
    except Exception as exc:
        raise ConnectorError(
            "PostgreSQL connection failed",
            detail={"host": host, "port": port, "error": str(exc)},
        ) from exc
    try:
        rows = await conn.fetch(
            """
            SELECT c.relname AS name,
                   CASE c.relkind
                     WHEN 'r' THEN 'BASE TABLE'
                     WHEN 'p' THEN 'BASE TABLE'
                     WHEN 'v' THEN 'VIEW'
                     WHEN 'm' THEN 'VIEW'
                     ELSE c.relkind::text
                   END AS table_type,
                   COALESCE(s.n_live_tup, 0)::bigint AS approx_rows,
                   obj_description(c.oid, 'pg_class') AS comment
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            LEFT JOIN pg_stat_user_tables s
              ON s.relid = c.oid
            WHERE n.nspname = $1
              AND c.relkind IN ('r', 'p', 'v', 'm')
              AND NOT c.relispartition
            ORDER BY c.relname
            """,
            schema_name,
        )
        return [
            {
                "name": str(r["name"]),
                "table_type": str(r["table_type"] or ""),
                "approx_rows": int(r["approx_rows"] or 0),
                "comment": (str(r["comment"]) if r["comment"] else None),
                "schema": schema_name,
            }
            for r in rows
        ]
    finally:
        await conn.close()


async def probe_postgres_table(
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
    try:
        conn = await asyncpg.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            timeout=connect_timeout,
        )
    except Exception as exc:
        raise ConnectorError(
            "PostgreSQL connection failed",
            detail={"host": host, "port": port, "error": str(exc)},
        ) from exc
    try:
        columns = await conn.fetch(
            """
            SELECT column_name,
                   data_type,
                   udt_name,
                   is_nullable,
                   character_maximum_length
            FROM information_schema.columns
            WHERE table_schema = $1 AND table_name = $2
            ORDER BY ordinal_position
            """,
            schema_name,
            table_name,
        )
        if not columns:
            raise ValidationAppError(
                "Table not found",
                detail={"database": database, "schema": schema_name, "table": table_name},
            )
        pk_rows = await conn.fetch(
            """
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            WHERE tc.table_schema = $1
              AND tc.table_name = $2
              AND tc.constraint_type = 'PRIMARY KEY'
            """,
            schema_name,
            table_name,
        )
        pk = {str(r["column_name"]) for r in pk_rows}
        fq = f"{_quote_ident(schema_name)}.{_quote_ident(table_name)}"
        count_row = await conn.fetchrow(f"SELECT COUNT(*) AS n FROM {fq}")
        limit = max(1, min(sample_limit, 20))
        samples = await conn.fetch(f"SELECT * FROM {fq} LIMIT {limit}")
        col_out = []
        for c in columns:
            name = str(c["column_name"])
            data_type = str(c["data_type"] or c["udt_name"] or "text")
            maxlen = c["character_maximum_length"]
            type_label = f"{data_type}({maxlen})" if maxlen else data_type
            col_out.append(
                {
                    "name": name,
                    "type": type_label,
                    "nullable": str(c["is_nullable"] or ""),
                    "key": "PRI" if name in pk else "",
                }
            )
        row_count = int(count_row["n"]) if count_row is not None else 0
        return {
            "database": database,
            "schema": schema_name,
            "table": table_name,
            "columns": col_out,
            "row_count": row_count,
            "samples": [
                {str(k): _jsonable(v) for k, v in dict(r).items()} for r in samples
            ],
        }
    finally:
        await conn.close()


class PostgresEquipmentConnector(EquipmentConnector):
    kind = "postgres"

    def __init__(self, config: StructuredConnectorConfig, settings: Settings) -> None:
        super().__init__(config, settings)

    def _pg(self):
        cfg = self.config.postgres
        assert cfg is not None
        return cfg

    async def _connect(self) -> asyncpg.Connection:
        cfg = self._pg()
        password = resolve_postgres_password(
            password=cfg.password, password_env=cfg.password_env
        )
        try:
            return await asyncpg.connect(
                host=cfg.host,
                port=cfg.port,
                user=cfg.user,
                password=password,
                database=cfg.database,
                timeout=float(cfg.connect_timeout_seconds),
            )
        except Exception as exc:
            raise ConnectorError(
                "PostgreSQL connection failed",
                detail={"host": cfg.host, "port": cfg.port, "error": str(exc)},
            ) from exc

    def _device_map(self) -> dict[str, str]:
        return dict(self.config.column_map.get("devices") or {})

    async def _fetch_devices(
        self, conn: asyncpg.Connection, *, since: str | None
    ) -> tuple[list[DeviceRow], str | None, list[str]]:
        cfg = self._pg()
        cmap = self._device_map()
        updated_keys = _mapped_keys(
            cmap, "updated_at", DEFAULT_DEVICE_FIELDS["updated_at"]
        )
        updated_col = cmap.get("updated_at")
        schema = (cfg.schema or DEFAULT_SCHEMA).strip() or DEFAULT_SCHEMA
        fq = f"{_quote_ident(schema)}.{_quote_ident(cfg.table)}"
        sql = f"SELECT * FROM {fq}"
        params: list[Any] = []
        warnings: list[str] = []
        if since:
            if updated_col:
                sql += f" WHERE {_quote_ident(updated_col)} > $1"
                params.append(since)
            else:
                warnings.append(
                    "incremental requested but column_map.devices.updated_at unset; "
                    "fetched full table and filtered in memory"
                )
        sql += f" LIMIT {max(1, min(cfg.row_limit, 100_000))}"
        raw_rows = await conn.fetch(sql, *params)
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
                "connector": "postgres",
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
        cfg = self._pg()
        use_cursor = (
            self.config.incremental.enabled
            and not force_full
            and cursor is not None
            and bool(cursor.watermarks)
        )
        mode = "incremental" if use_cursor else "full"
        since = cursor.watermarks.get("devices") if use_cursor and cursor else None
        conn = await self._connect()
        try:
            devices, high, warnings = await self._fetch_devices(conn, since=since)
        except ConnectorError:
            raise
        except Exception as exc:
            raise ConnectorError(
                "PostgreSQL query failed",
                detail={"table": cfg.table, "error": str(exc)},
            ) from exc
        finally:
            await conn.close()

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
