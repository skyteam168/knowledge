"""PostgreSQL connector schema probe + config parsing."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.services.structured.connectors.base import parse_connector_config
from app.services.structured.connectors.postgres import (
    list_postgres_tables,
    probe_postgres_table,
    resolve_postgres_password,
)


class _Rec(dict[str, Any]):
    """Minimal asyncpg.Record stand-in (supports dict() and [])."""

    pass


def test_parse_postgres_connector_meta() -> None:
    cfg = parse_connector_config(
        {
            "connector": "postgres",
            "postgres": {
                "host": "pg.example",
                "port": 5432,
                "database": "mes",
                "user": "reader",
                "password_env": "MES_PG_PASSWORD",
                "schema": "public",
                "table": "device_info",
            },
        }
    )
    assert cfg is not None
    assert cfg.connector == "postgres"
    assert cfg.postgres is not None
    assert cfg.postgres.host == "pg.example"
    assert cfg.postgres.schema == "public"


def test_resolve_postgres_password_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MES_PG_PASSWORD", "secret")
    assert resolve_postgres_password(password_env="MES_PG_PASSWORD") == "secret"
    assert resolve_postgres_password(password="inline") == "inline"


@pytest.mark.asyncio
async def test_list_and_probe_postgres_table() -> None:
    conn = AsyncMock()
    conn.close = AsyncMock()
    conn.fetch = AsyncMock(
        return_value=[
            _Rec(
                name="device_info",
                table_type="BASE TABLE",
                approx_rows=2,
                comment="设备",
            )
        ]
    )
    conn.fetchrow = AsyncMock(return_value=_Rec(n=1))

    with patch(
        "app.services.structured.connectors.postgres.asyncpg.connect",
        new=AsyncMock(return_value=conn),
    ):
        tables = await list_postgres_tables(
            host="h",
            port=5432,
            user="u",
            password="p",
            database="mes",
            schema="public",
        )
        assert tables[0]["name"] == "device_info"

        conn.fetch = AsyncMock(
            side_effect=[
                [
                    _Rec(
                        column_name="device_code",
                        data_type="character varying",
                        udt_name="varchar",
                        is_nullable="NO",
                        character_maximum_length=64,
                    ),
                    _Rec(
                        column_name="device_name",
                        data_type="text",
                        udt_name="text",
                        is_nullable="YES",
                        character_maximum_length=None,
                    ),
                ],
                [_Rec(column_name="device_code")],
                [_Rec(device_code="X1", device_name="样例")],
            ]
        )
        out = await probe_postgres_table(
            host="h",
            port=5432,
            user="u",
            password="p",
            database="mes",
            table="device_info",
            schema="public",
        )
        assert out["table"] == "device_info"
        assert out["row_count"] == 1
        assert any(c["name"] == "device_code" and c["key"] == "PRI" for c in out["columns"])
        assert out["samples"][0]["device_code"] == "X1"
