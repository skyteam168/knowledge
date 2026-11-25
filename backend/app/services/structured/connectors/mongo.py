"""MongoDB connector: collection probe (schema from samples) + equipment pull.

Password is never stored in ``StructuredSource.meta`` — use ``password_env``.
Auth is optional: when ``user`` is empty, connects without credentials.
"""

from __future__ import annotations

import os
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from bson import ObjectId
from bson.decimal128 import Decimal128
from pymongo import ASCENDING, MongoClient
from pymongo.errors import PyMongoError

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

DEFAULT_AUTH_SOURCE = "admin"


def resolve_mongo_password(
    *,
    password: str | None = None,
    password_env: str = "MES_MONGO_PASSWORD",
    require: bool = True,
) -> str:
    if password:
        return password
    env_name = (password_env or "").strip() or "MES_MONGO_PASSWORD"
    value = os.environ.get(env_name) or ""
    if not value and require:
        raise ValidationAppError(
            "MongoDB password missing",
            detail={"password_env": env_name},
        )
    return value


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal128):
        return float(value.to_decimal())
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (bytes, memoryview)):
        return bytes(value).hex()
    if isinstance(value, list):
        return [_jsonable(v) for v in value[:20]]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in list(value.items())[:40]}
    return value


def _type_label(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, ObjectId):
        return "objectId"
    if isinstance(value, int) and not isinstance(value, bool):
        return "int"
    if isinstance(value, float):
        return "double"
    if isinstance(value, Decimal128):
        return "decimal"
    if isinstance(value, datetime):
        return "date"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _merge_type(existing: str | None, incoming: str) -> str:
    if existing is None or existing == incoming:
        return incoming
    if existing == "null":
        return incoming
    if incoming == "null":
        return existing
    parts = {p.strip() for p in existing.split("|")}
    parts.add(incoming)
    parts.discard("null")
    return "|".join(sorted(parts)) if len(parts) > 1 else next(iter(parts))


def _client(
    *,
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
    auth_source: str,
    connect_timeout: float,
) -> MongoClient[Any]:
    kwargs: dict[str, Any] = {
        "host": host,
        "port": port,
        "serverSelectionTimeoutMS": int(connect_timeout * 1000),
        "connectTimeoutMS": int(connect_timeout * 1000),
    }
    if user:
        kwargs["username"] = user
        kwargs["password"] = password
        kwargs["authSource"] = (auth_source or DEFAULT_AUTH_SOURCE).strip() or DEFAULT_AUTH_SOURCE
    try:
        client: MongoClient[Any] = MongoClient(**kwargs)
        # Force handshake early
        client.admin.command("ping")
        _ = database  # database selected by callers
        return client
    except PyMongoError as exc:
        raise ConnectorError(
            "MongoDB connection failed",
            detail={"host": host, "port": port, "error": str(exc)},
        ) from exc


def list_mongo_collections(
    *,
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
    auth_source: str = DEFAULT_AUTH_SOURCE,
    connect_timeout: float = 10.0,
) -> list[dict[str, Any]]:
    """List collections in a database (read-only)."""
    client = _client(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        auth_source=auth_source,
        connect_timeout=connect_timeout,
    )
    try:
        db = client[database]
        names = sorted(db.list_collection_names())
        out: list[dict[str, Any]] = []
        for name in names:
            if name.startswith("system."):
                continue
            approx = 0
            try:
                approx = int(db[name].estimated_document_count())
            except PyMongoError:
                approx = 0
            out.append(
                {
                    "name": name,
                    "table_type": "COLLECTION",
                    "approx_rows": approx,
                    "comment": None,
                }
            )
        return out
    finally:
        client.close()


def probe_mongo_collection(
    *,
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
    collection: str,
    auth_source: str = DEFAULT_AUTH_SOURCE,
    sample_limit: int = 3,
    infer_limit: int = 50,
    connect_timeout: float = 10.0,
) -> dict[str, Any]:
    """Infer field types from sample documents for ontology import."""
    coll_name = collection.strip()
    if not coll_name:
        raise ValidationAppError("Collection name required")
    client = _client(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        auth_source=auth_source,
        connect_timeout=connect_timeout,
    )
    try:
        db = client[database]
        if coll_name not in db.list_collection_names():
            raise ValidationAppError(
                "Collection not found",
                detail={"database": database, "collection": coll_name},
            )
        coll = db[coll_name]
        try:
            row_count = int(coll.estimated_document_count())
        except PyMongoError:
            row_count = 0
        infer_n = max(sample_limit, min(infer_limit, 200))
        docs = list(coll.find({}).limit(infer_n))
        type_map: dict[str, str] = {}
        nullable: dict[str, bool] = {}
        for doc in docs:
            seen = set(doc.keys())
            for key, value in doc.items():
                type_map[key] = _merge_type(type_map.get(key), _type_label(value))
                if value is None:
                    nullable[key] = True
            for key in type_map:
                if key not in seen:
                    nullable[key] = True
        if "_id" not in type_map:
            type_map["_id"] = "objectId"
        col_out = []
        # Prefer _id first, then alpha
        keys = sorted(type_map.keys(), key=lambda k: (0 if k == "_id" else 1, k))
        for name in keys:
            col_out.append(
                {
                    "name": name,
                    "type": type_map[name],
                    "nullable": "YES" if nullable.get(name) else "NO",
                    "key": "PRI" if name == "_id" else "",
                }
            )
        limit = max(1, min(sample_limit, 20))
        samples = [_jsonable(dict(d)) for d in docs[:limit]]
        return {
            "database": database,
            "table": coll_name,
            "columns": col_out,
            "row_count": row_count,
            "samples": samples,
        }
    finally:
        client.close()


class MongoEquipmentConnector(EquipmentConnector):
    kind = "mongo"

    def __init__(self, config: StructuredConnectorConfig, settings: Settings) -> None:
        super().__init__(config, settings)

    def _mongo_cfg(self):
        cfg = self.config.mongo
        assert cfg is not None
        return cfg

    def _connect(self) -> MongoClient[Any]:
        cfg = self._mongo_cfg()
        password = ""
        if cfg.user:
            password = resolve_mongo_password(
                password=cfg.password, password_env=cfg.password_env, require=True
            )
        return _client(
            host=cfg.host,
            port=cfg.port,
            user=cfg.user,
            password=password,
            database=cfg.database,
            auth_source=cfg.auth_source,
            connect_timeout=float(cfg.connect_timeout_seconds),
        )

    def _device_map(self) -> dict[str, str]:
        return dict(self.config.column_map.get("devices") or {})

    def _fetch_devices(
        self, client: MongoClient[Any], *, since: str | None
    ) -> tuple[list[DeviceRow], str | None, list[str]]:
        cfg = self._mongo_cfg()
        cmap = self._device_map()
        updated_keys = _mapped_keys(
            cmap, "updated_at", DEFAULT_DEVICE_FIELDS["updated_at"]
        )
        updated_col = cmap.get("updated_at")
        coll = client[cfg.database][cfg.collection]
        query: dict[str, Any] = {}
        warnings: list[str] = []
        if since:
            if updated_col:
                query[updated_col] = {"$gt": since}
            else:
                warnings.append(
                    "incremental requested but column_map.devices.updated_at unset; "
                    "fetched full collection and filtered in memory"
                )
        cursor = coll.find(query).sort("_id", ASCENDING).limit(
            max(1, min(cfg.row_limit, 100_000))
        )
        devices: list[DeviceRow] = []
        high: str | None = since
        for raw in cursor:
            row = {str(k): v for k, v in dict(raw).items()}
            # stringify ObjectId for pick helpers
            flat = {k: (_jsonable(v) if not isinstance(v, (dict, list)) else v) for k, v in row.items()}
            for k, v in list(flat.items()):
                if isinstance(v, (dict, list)):
                    flat[k] = str(_jsonable(v))
            external_id = _pick(
                flat, *_mapped_keys(cmap, "external_id", DEFAULT_DEVICE_FIELDS["external_id"])
            )
            if not external_id and "_id" in flat:
                external_id = str(flat["_id"])
            name = _pick(flat, *_mapped_keys(cmap, "name", DEFAULT_DEVICE_FIELDS["name"]))
            if not external_id or not name:
                continue
            status = (
                _pick(flat, *_mapped_keys(cmap, "status", DEFAULT_DEVICE_FIELDS["status"]))
                or "active"
            )
            location = _pick(
                flat, *_mapped_keys(cmap, "location", DEFAULT_DEVICE_FIELDS["location"])
            )
            watermark = None
            for key in updated_keys:
                raw_v = row.get(key)
                if raw_v is None:
                    lower = {str(k).lower(): k for k in row}
                    real = lower.get(key.lower())
                    raw_v = row.get(real) if real else None
                watermark = _normalize_ts(raw_v)
                if watermark:
                    break
            high = advance_watermark(high, watermark)
            extras: dict[str, Any] = {}
            for k, v in flat.items():
                if len(extras) >= 12:
                    break
                text = str(v)
                if len(text) > 200:
                    text = text[:200]
                extras[f"col_{k}"] = text
            meta = {
                "connector": "mongo",
                "collection": cfg.collection,
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

        cfg = self._mongo_cfg()
        use_cursor = (
            self.config.incremental.enabled
            and not force_full
            and cursor is not None
            and bool(cursor.watermarks)
        )
        mode = "incremental" if use_cursor else "full"
        since = cursor.watermarks.get("devices") if use_cursor and cursor else None

        def _run() -> tuple[list[DeviceRow], str | None, list[str]]:
            client = self._connect()
            try:
                return self._fetch_devices(client, since=since)
            finally:
                client.close()

        try:
            devices, high, warnings = await asyncio.to_thread(_run)
        except ConnectorError:
            raise
        except Exception as exc:
            raise ConnectorError(
                "MongoDB query failed",
                detail={"collection": cfg.collection, "error": str(exc)},
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
