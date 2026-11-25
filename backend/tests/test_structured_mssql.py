"""SQL Server connector schema probe + config parsing."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.structured.connectors.base import parse_connector_config
from app.services.structured.connectors.mssql import (
    list_mssql_tables,
    probe_mssql_table,
    resolve_mssql_password,
)


def test_parse_mssql_connector_meta() -> None:
    cfg = parse_connector_config(
        {
            "connector": "mssql",
            "mssql": {
                "host": "sql.example",
                "port": 1433,
                "database": "mes",
                "user": "reader",
                "password_env": "MES_MSSQL_PASSWORD",
                "schema": "dbo",
                "table": "device_info",
            },
        }
    )
    assert cfg is not None
    assert cfg.connector == "mssql"
    assert cfg.mssql is not None
    assert cfg.mssql.host == "sql.example"
    assert cfg.mssql.schema == "dbo"


def test_resolve_mssql_password_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MES_MSSQL_PASSWORD", "secret")
    assert resolve_mssql_password(password_env="MES_MSSQL_PASSWORD") == "secret"
    assert resolve_mssql_password(password="inline") == "inline"


def test_list_and_probe_mssql_table() -> None:
    cur = MagicMock()
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)
    cur.fetchall.side_effect = [
        [{"name": "device_info", "table_type": "BASE TABLE"}],
        [{"name": "device_info", "approx_rows": 3}],
        [
            {
                "column_name": "device_code",
                "data_type": "nvarchar",
                "is_nullable": "NO",
                "character_maximum_length": 64,
                "column_key": "PRI",
            },
            {
                "column_name": "device_name",
                "data_type": "nvarchar",
                "is_nullable": "YES",
                "character_maximum_length": 128,
                "column_key": "",
            },
        ],
        [{"device_code": "X1", "device_name": "样例"}],
    ]
    cur.fetchone.return_value = {"n": 1}

    conn = MagicMock()
    conn.cursor.return_value = cur

    with patch(
        "app.services.structured.connectors.mssql.pymssql.connect",
        return_value=conn,
    ):
        tables = list_mssql_tables(
            host="h",
            port=1433,
            user="u",
            password="p",
            database="mes",
            schema="dbo",
        )
        assert tables[0]["name"] == "device_info"
        assert tables[0]["approx_rows"] == 3

        # Reset side effects for probe (list used first two fetchalls)
        cur.fetchall.side_effect = [
            [
                {
                    "column_name": "device_code",
                    "data_type": "nvarchar",
                    "is_nullable": "NO",
                    "character_maximum_length": 64,
                    "column_key": "PRI",
                },
                {
                    "column_name": "device_name",
                    "data_type": "nvarchar",
                    "is_nullable": "YES",
                    "character_maximum_length": 128,
                    "column_key": "",
                },
            ],
            [{"device_code": "X1", "device_name": "样例"}],
        ]
        out = probe_mssql_table(
            host="h",
            port=1433,
            user="u",
            password="p",
            database="mes",
            table="device_info",
            schema="dbo",
        )
        assert out["table"] == "device_info"
        assert out["row_count"] == 1
        assert any(c["name"] == "device_code" and c["key"] == "PRI" for c in out["columns"])
        assert out["samples"][0]["device_code"] == "X1"
