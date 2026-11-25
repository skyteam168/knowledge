"""REST JSON connector for equipment mirror rows."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any
from urllib.parse import urljoin

import httpx

from app.core.config import Settings
from app.services.structured.connectors.base import (
    ConnectorError,
    DeviceRow,
    EquipmentConnector,
    EquipmentSnapshot,
    FetchResult,
    SparePartRow,
    StructuredConnectorConfig,
    SyncCursor,
    WorkOrderRow,
    advance_watermark,
)


def _items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("items", "data", "results", "records"):
            raw = payload.get(key)
            if isinstance(raw, list):
                return [x for x in raw if isinstance(x, dict)]
        # single object
        if "external_id" in payload:
            return [payload]
    raise ConnectorError("Unexpected REST payload shape", detail=str(payload)[:500])


def _str(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _parse_opened_at(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise ConnectorError("Invalid opened_at in REST payload", detail={"value": value}) from exc


def _row_watermark(row: dict[str, Any], field: str) -> str | None:
    value = row.get(field)
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        datetime.fromisoformat(text)
    except ValueError:
        return None
    return text


class RestEquipmentConnector(EquipmentConnector):
    kind = "rest"

    def __init__(
        self,
        config: StructuredConnectorConfig,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(config, settings)
        assert config.rest is not None
        self.transport = transport

    def _token(self) -> str | None:
        rest = self.config.rest
        assert rest is not None
        if rest.bearer_token:
            return rest.bearer_token
        if rest.bearer_env:
            return os.environ.get(rest.bearer_env) or None
        return None

    def _client(self) -> httpx.AsyncClient:
        headers: dict[str, str] = {"Accept": "application/json"}
        token = self._token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return httpx.AsyncClient(
            timeout=self.settings.structured_http_timeout_seconds,
            transport=self.transport,
            headers=headers,
        )

    async def _get_list(
        self,
        client: httpx.AsyncClient,
        path: str | None,
        *,
        since: str | None = None,
    ) -> list[dict[str, Any]]:
        if not path:
            return []
        rest = self.config.rest
        assert rest is not None
        url = urljoin(rest.base_url.rstrip("/") + "/", path.lstrip("/"))
        params: dict[str, str] = {}
        if since and self.config.incremental.enabled:
            params[self.config.incremental.param] = since
        response = await client.get(url, params=params or None)
        if response.status_code >= 400:
            raise ConnectorError(
                f"HTTP {response.status_code}",
                detail={"url": url, "body": response.text[:500]},
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise ConnectorError("Invalid JSON response", detail=response.text[:500]) from exc
        return _items(payload)

    def _advance(
        self, high: str | None, rows: list[dict[str, Any]]
    ) -> str | None:
        field = self.config.incremental.field
        for row in rows:
            high = advance_watermark(high, _row_watermark(row, field))
        return high

    async def fetch(
        self,
        *,
        cursor: SyncCursor | None = None,
        force_full: bool = False,
    ) -> FetchResult:
        rest = self.config.rest
        assert rest is not None
        use_cursor = (
            self.config.incremental.enabled
            and not force_full
            and cursor is not None
            and bool(cursor.watermarks)
        )
        watermarks = dict(cursor.watermarks) if use_cursor else {}
        mode = "incremental" if use_cursor else "full"

        async with self._client() as client:
            device_raw = await self._get_list(
                client,
                rest.paths.devices,
                since=watermarks.get("devices") if use_cursor else None,
            )
            wo_raw = await self._get_list(
                client,
                rest.paths.work_orders,
                since=watermarks.get("work_orders") if use_cursor else None,
            )
            part_raw = await self._get_list(
                client,
                rest.paths.spare_parts,
                since=watermarks.get("spare_parts") if use_cursor else None,
            )

        devices = [
            DeviceRow(
                external_id=_str(r, "external_id", "id", "device_code", "code"),
                name=_str(r, "name", "title", "label"),
                status=_str(r, "status") or "active",
                location=_str(r, "location") or None,
                meta={"connector": "rest", **{k: v for k, v in r.items() if k.startswith("attr_")}},
            )
            for r in device_raw
            if _str(r, "external_id", "id", "device_code", "code")
            and _str(r, "name", "title", "label")
        ]
        work_orders = [
            WorkOrderRow(
                external_id=_str(r, "external_id", "id", "wo_code", "code"),
                title=_str(r, "title", "name", "summary"),
                status=_str(r, "status") or "open",
                device_external_id=_str(r, "device_external_id", "device_id", "device_code")
                or None,
                opened_at=_parse_opened_at(r.get("opened_at")),
                meta={"connector": "rest"},
            )
            for r in wo_raw
            if _str(r, "external_id", "id", "wo_code", "code")
            and _str(r, "title", "name", "summary")
        ]
        spare_parts = [
            SparePartRow(
                external_id=_str(r, "external_id", "id", "part_code", "code"),
                name=_str(r, "name", "title"),
                sku=_str(r, "sku") or None,
                qty_on_hand=float(r.get("qty_on_hand") or r.get("qty") or 0),
                meta={"connector": "rest"},
            )
            for r in part_raw
            if _str(r, "external_id", "id", "part_code", "code") and _str(r, "name", "title")
        ]

        next_cursor = None
        if self.config.incremental.enabled:
            next_marks: dict[str, str] = {}
            for kind, raw, prev in (
                ("devices", device_raw, watermarks.get("devices")),
                ("work_orders", wo_raw, watermarks.get("work_orders")),
                ("spare_parts", part_raw, watermarks.get("spare_parts")),
            ):
                high = self._advance(prev, raw)
                if high:
                    next_marks[kind] = high
            next_cursor = SyncCursor(watermarks=next_marks)

        return FetchResult(
            snapshot=EquipmentSnapshot(
                devices=devices, work_orders=work_orders, spare_parts=spare_parts
            ),
            next_cursor=next_cursor,
            mode=mode,  # type: ignore[arg-type]
        )
