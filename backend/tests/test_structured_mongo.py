"""MongoDB connector schema probe + config parsing."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.services.structured.connectors.base import parse_connector_config
from app.services.structured.connectors.mongo import (
    list_mongo_collections,
    probe_mongo_collection,
    resolve_mongo_password,
)


def test_parse_mongo_connector_meta() -> None:
    cfg = parse_connector_config(
        {
            "connector": "mongo",
            "mongo": {
                "host": "mongo.example",
                "port": 27017,
                "database": "mes",
                "user": "reader",
                "password_env": "MES_MONGO_PASSWORD",
                "auth_source": "admin",
                "collection": "devices",
            },
        }
    )
    assert cfg is not None
    assert cfg.connector == "mongo"
    assert cfg.mongo is not None
    assert cfg.mongo.host == "mongo.example"
    assert cfg.mongo.collection == "devices"


def test_resolve_mongo_password_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MES_MONGO_PASSWORD", "secret")
    assert resolve_mongo_password(password_env="MES_MONGO_PASSWORD") == "secret"
    assert resolve_mongo_password(password="inline") == "inline"
    assert resolve_mongo_password(password_env="MISSING", require=False) == ""


def test_list_and_probe_mongo_collection() -> None:
    coll = MagicMock()
    coll.estimated_document_count.return_value = 2
    coll.find.return_value.limit.return_value = [
        {"_id": "a1", "device_code": "X1", "device_name": "样例", "status": "active"},
        {"_id": "a2", "device_code": "X2", "device_name": None, "tags": ["a"]},
    ]

    db = MagicMock()
    db.list_collection_names.return_value = ["devices", "system.indexes"]
    db.__getitem__.return_value = coll

    client = MagicMock()
    client.__getitem__.return_value = db
    client.admin.command.return_value = {"ok": 1}

    with patch(
        "app.services.structured.connectors.mongo.MongoClient",
        return_value=client,
    ):
        tables = list_mongo_collections(
            host="h",
            port=27017,
            user="",
            password="",
            database="mes",
        )
        assert len(tables) == 1
        assert tables[0]["name"] == "devices"
        assert tables[0]["table_type"] == "COLLECTION"

        out = probe_mongo_collection(
            host="h",
            port=27017,
            user="",
            password="",
            database="mes",
            collection="devices",
            sample_limit=2,
        )
        assert out["table"] == "devices"
        assert out["row_count"] == 2
        names = {c["name"] for c in out["columns"]}
        assert "_id" in names
        assert "device_code" in names
        assert any(c["name"] == "_id" and c["key"] == "PRI" for c in out["columns"])
        assert out["samples"][0]["device_code"] == "X1"
