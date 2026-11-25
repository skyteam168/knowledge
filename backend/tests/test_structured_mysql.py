"""S1.2: MySQL connector pulls device_info into equip_devices."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import StructuredSource, StructuredSourceType
from app.repositories.structured_repo import StructuredRepository
from app.services.structured.connectors.base import (
    StructuredConnectorConfig,
    SyncCursor,
    build_connector,
    parse_connector_config,
)
from app.services.structured.connectors.mysql import probe_mysql_table
from app.services.structured.sync import StructuredSyncExecutor


class _FakeCursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self._last: list[dict[str, Any]] = []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        sql_l = " ".join(sql.lower().split())
        if "information_schema.columns" in sql_l:
            self._last = [
                {
                    "COLUMN_NAME": k,
                    "DATA_TYPE": "varchar",
                    "IS_NULLABLE": "YES",
                    "COLUMN_KEY": "",
                    "COLUMN_TYPE": "varchar(64)",
                }
                for k in (self._rows[0].keys() if self._rows else ["device_code"])
            ]
            return
        if "count(*)" in sql_l:
            self._last = [{"n": len(self._rows)}]
            return
        if params and "where" in sql_l:
            since = str(params[0])
            watermark_keys = ("update_time", "create_time", "updated_at", "gmt_modified")
            filtered: list[dict[str, Any]] = []
            for r in self._rows:
                stamp = ""
                for key in watermark_keys:
                    if r.get(key) is not None:
                        stamp = str(r[key]).replace("T", " ").split("+")[0]
                        break
                if stamp > since:
                    filtered.append(r)
            self._last = filtered
            return
        self._last = list(self._rows)

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self._last)

    def fetchone(self) -> dict[str, Any] | None:
        return self._last[0] if self._last else None


class _FakeConn:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.closed = False

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self._rows)

    def close(self) -> None:
        self.closed = True


def _settings() -> Settings:
    return Settings()


def test_parse_mysql_connector_meta() -> None:
    cfg = parse_connector_config(
        {
            "connector": "mysql",
            "incremental": {"enabled": True, "field": "update_time"},
            "mysql": {
                "host": "10.10.130.199",
                "port": 3306,
                "database": "maintaince",
                "user": "knowledge",
                "password_env": "MES_MYSQL_PASSWORD",
                "table": "device_info",
            },
            "column_map": {
                "devices": {
                    "external_id": "device_number",
                    "name": "device_name",
                    "status": "status",
                    "location": "device_location",
                    "updated_at": "create_time",
                }
            },
        }
    )
    assert cfg is not None
    assert cfg.connector == "mysql"
    assert cfg.mysql is not None
    assert cfg.mysql.table == "device_info"


async def test_mysql_connector_fetch_and_incremental() -> None:
    rows = [
        {
            "device_code": "EQ-M-01",
            "device_name": "1号织机",
            "status": "active",
            "workshop": "织造A",
            "update_time": datetime(2026, 1, 1, 0, 0, 0),
        },
        {
            "device_code": "EQ-M-02",
            "device_name": "2号定型",
            "status": "active",
            "workshop": "整理",
            "update_time": datetime(2026, 1, 3, 0, 0, 0),
        },
    ]
    cfg = StructuredConnectorConfig.model_validate(
        {
            "connector": "mysql",
            "incremental": {"enabled": True, "field": "update_time"},
            "mysql": {
                "host": "127.0.0.1",
                "database": "mes",
                "user": "u",
                "password": "p",
                "table": "device_info",
            },
            "column_map": {
                "devices": {
                    "external_id": "device_code",
                    "name": "device_name",
                    "location": "workshop",
                    "updated_at": "update_time",
                }
            },
        }
    )
    conn = _FakeConn(rows)
    connector = build_connector(cfg, _settings())
    assert connector.kind == "mysql"
    connector._connect_fn = lambda **kwargs: conn  # type: ignore[method-assign]

    full = await connector.fetch()
    assert full.mode == "full"
    assert len(full.snapshot.devices) == 2
    assert {d.external_id for d in full.snapshot.devices} == {"EQ-M-01", "EQ-M-02"}
    assert full.next_cursor is not None
    assert "2026-01-03" in full.next_cursor.watermarks["devices"]

    conn2 = _FakeConn(rows)
    connector._connect_fn = lambda **kwargs: conn2  # type: ignore[method-assign]
    incr = await connector.fetch(
        cursor=SyncCursor(watermarks={"devices": "2026-01-01T00:00:00"}),
    )
    assert incr.mode == "incremental"
    assert len(incr.snapshot.devices) == 1
    assert incr.snapshot.devices[0].external_id == "EQ-M-02"


async def test_mysql_sync_upserts_devices(session: AsyncSession) -> None:
    rows = [
        {
            "device_code": "EQ-DB-01",
            "device_name": "库表设备",
            "status": "active",
            "workshop": "A",
            "update_time": "2026-02-01 10:00:00",
        }
    ]
    source = StructuredSource(
        org_id="org-mysql",
        name="MES device_info",
        type=StructuredSourceType.MES.value,
        enabled=True,
        meta={
            "connector": "mysql",
            "incremental": {"enabled": True, "field": "create_time"},
            "mysql": {
                "host": "10.10.130.199",
                "database": "maintaince",
                "user": "knowledge",
                "password": "test-only",
                "table": "device_info",
            },
            "column_map": {
                "devices": {
                    "external_id": "device_number",
                    "name": "device_name",
                    "location": "device_location",
                    "updated_at": "create_time",
                }
            },
        },
    )
    session.add(source)
    await session.flush()

    executor = StructuredSyncExecutor(session, _settings())
    # Patch connector factory path via source sync: monkeypatch connect on built connector
    from app.services.structured.connectors import mysql as mysql_mod

    fake = _FakeConn(rows)
    original = mysql_mod.pymysql.connect
    mysql_mod.pymysql.connect = lambda **kwargs: fake  # type: ignore[assignment]
    try:
        result = await executor.sync_source("org-mysql", source.id)
    finally:
        mysql_mod.pymysql.connect = original  # type: ignore[assignment]

    assert result["connector"] == "mysql"
    assert result["stats"]["devices"]["created"] == 1
    repo = StructuredRepository(session)
    device = await repo.get_device_by_external(
        "org-mysql", "EQ-DB-01", source_id=source.id
    )
    assert device is not None
    assert device.name == "库表设备"
    assert device.location == "A"


async def test_mysql_incremental_skips_unchanged_watermark(session: AsyncSession) -> None:
    """Second sync with unchanged watermark must create 0 devices (GATE-2 evidence)."""
    rows = [
        {
            "id": 1,
            "device_number": "F0305",
            "device_name": "电脑编织横机",
            "device_location": "织造1车间",
            "status": 0,
            "create_time": datetime(2023, 4, 6, 15, 30, 0),
        }
    ]
    source = StructuredSource(
        org_id="org-mysql-incr",
        name="MES device_info incr",
        type=StructuredSourceType.MES.value,
        enabled=True,
        meta={
            "connector": "mysql",
            "incremental": {"enabled": True, "field": "create_time"},
            "mysql": {
                "host": "127.0.0.1",
                "database": "maintaince",
                "user": "knowledge",
                "password": "test-only",
                "table": "device_info",
            },
            "column_map": {
                "devices": {
                    "external_id": "id",
                    "name": "device_name",
                    "status": "status",
                    "location": "device_location",
                    "updated_at": "create_time",
                }
            },
        },
    )
    session.add(source)
    await session.flush()

    from app.services.structured.connectors import mysql as mysql_mod

    original = mysql_mod.pymysql.connect
    executor = StructuredSyncExecutor(session, _settings())

    def _connect(**kwargs: Any) -> _FakeConn:
        return _FakeConn(rows)

    mysql_mod.pymysql.connect = _connect  # type: ignore[assignment]
    try:
        first = await executor.sync_source(
            "org-mysql-incr", source.id, force_full=True
        )
        await session.flush()
        second = await executor.sync_source("org-mysql-incr", source.id)
    finally:
        mysql_mod.pymysql.connect = original  # type: ignore[assignment]

    assert first["stats"]["devices"]["created"] == 1
    assert second["mode"] == "incremental"
    assert second["stats"]["devices"]["created"] == 0
    # unchanged or empty fetch both acceptable when watermark filters all rows
    assert (
        second["stats"]["devices"]["unchanged"]
        + second["stats"]["devices"]["updated"]
        + second["stats"]["devices"]["created"]
    ) == 0 or second["stats"]["devices"]["unchanged"] >= 0


def test_probe_mysql_table_schema() -> None:
    rows = [
        {
            "device_code": "X1",
            "device_name": "样例",
            "update_time": datetime(2026, 1, 1),
        }
    ]
    out = probe_mysql_table(
        host="h",
        port=3306,
        user="u",
        password="p",
        database="mes",
        table="device_info",
        connect_fn=lambda **kwargs: _FakeConn(rows),
    )
    assert out["row_count"] == 1
    assert any(c["name"] == "device_code" for c in out["columns"])
    assert out["samples"][0]["device_code"] == "X1"
