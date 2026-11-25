"""CSV file connector for equipment mirror rows."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from app.core.config import Settings
from app.core.exceptions import ValidationAppError
from app.services.structured.connectors.base import (
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

DEFAULT_DEVICE_MAP = {
    "external_id": "external_id",
    "name": "name",
    "status": "status",
    "location": "location",
    "updated_at": "updated_at",
}
DEFAULT_WO_MAP = {
    "external_id": "external_id",
    "title": "title",
    "status": "status",
    "device_external_id": "device_external_id",
    "opened_at": "opened_at",
    "updated_at": "updated_at",
}
DEFAULT_PART_MAP = {
    "external_id": "external_id",
    "name": "name",
    "sku": "sku",
    "qty_on_hand": "qty_on_hand",
    "updated_at": "updated_at",
}


def _cell(row: dict[str, str], column: str | None) -> str:
    if not column:
        return ""
    return (row.get(column) or "").strip()


def _parse_opened_at(value: str) -> datetime | None:
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValidationAppError(
            "Invalid opened_at in CSV", detail={"value": value}
        ) from exc


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise ValidationAppError("CSV file not found", detail={"path": str(path)})
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise ValidationAppError("CSV has no header", detail={"path": str(path)})
        return [{k: (v or "").strip() for k, v in row.items() if k is not None} for row in reader]


def _normalize_ts(value: str) -> str | None:
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        datetime.fromisoformat(text)
    except ValueError:
        return None
    return text


def _after_cursor(value: str | None, since: str | None) -> bool:
    """True when row watermark is strictly newer than since (or since missing)."""
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


class CsvEquipmentConnector(EquipmentConnector):
    kind = "csv"

    def __init__(self, config: StructuredConnectorConfig, settings: Settings) -> None:
        super().__init__(config, settings)
        assert config.csv is not None

    def _map(self, object_kind: str, defaults: dict[str, str]) -> dict[str, str]:
        override = self.config.column_map.get(object_kind) or {}
        return {**defaults, **override}

    async def fetch(
        self,
        *,
        cursor: SyncCursor | None = None,
        force_full: bool = False,
    ) -> FetchResult:
        warnings: list[str] = []
        devices: list[DeviceRow] = []
        work_orders: list[WorkOrderRow] = []
        spare_parts: list[SparePartRow] = []
        csv_cfg = self.config.csv
        assert csv_cfg is not None

        use_cursor = (
            self.config.incremental.enabled
            and not force_full
            and cursor is not None
            and bool(cursor.watermarks)
        )
        watermarks = dict(cursor.watermarks) if use_cursor else {}
        next_marks: dict[str, str] = dict(watermarks)
        mode = "incremental" if use_cursor else "full"

        track = self.config.incremental.enabled
        if csv_cfg.devices:
            devices, next_marks["devices"], note = self._load_devices(
                Path(csv_cfg.devices),
                since=watermarks.get("devices") if use_cursor else None,
                track=track,
            )
            if note:
                warnings.append(note)
        else:
            warnings.append("csv.devices not configured")
        if csv_cfg.work_orders:
            work_orders, next_marks["work_orders"], note = self._load_work_orders(
                Path(csv_cfg.work_orders),
                since=watermarks.get("work_orders") if use_cursor else None,
                track=track,
            )
            if note:
                warnings.append(note)
        if csv_cfg.spare_parts:
            spare_parts, next_marks["spare_parts"], note = self._load_spare_parts(
                Path(csv_cfg.spare_parts),
                since=watermarks.get("spare_parts") if use_cursor else None,
                track=track,
            )
            if note:
                warnings.append(note)

        next_cursor = None
        if self.config.incremental.enabled:
            cleaned = {k: v for k, v in next_marks.items() if v}
            next_cursor = SyncCursor(watermarks=cleaned)

        return FetchResult(
            snapshot=EquipmentSnapshot(
                devices=devices,
                work_orders=work_orders,
                spare_parts=spare_parts,
                warnings=warnings,
            ),
            next_cursor=next_cursor,
            mode=mode,  # type: ignore[arg-type]
        )

    def _updated_col(self, cmap: dict[str, str]) -> str | None:
        field = self.config.incremental.field
        return cmap.get(field) or cmap.get("updated_at") or field

    def _load_devices(
        self, path: Path, *, since: str | None, track: bool
    ) -> tuple[list[DeviceRow], str | None, str | None]:
        cmap = self._map("devices", DEFAULT_DEVICE_MAP)
        updated_col = self._updated_col(cmap)
        rows: list[DeviceRow] = []
        high: str | None = since
        missing_ts = 0
        for raw in _read_csv(path):
            external_id = _cell(raw, cmap.get("external_id"))
            name = _cell(raw, cmap.get("name"))
            if not external_id or not name:
                continue
            ts = _normalize_ts(_cell(raw, updated_col)) if updated_col else None
            if track and not ts:
                missing_ts += 1
            if since is not None and not _after_cursor(ts, since):
                continue
            extra = {
                k: v
                for k, v in raw.items()
                if k and k not in set(cmap.values()) and v
            }
            if ts:
                high = advance_watermark(high, ts)
                extra = {**extra, "updated_at": ts}
            rows.append(
                DeviceRow(
                    external_id=external_id,
                    name=name,
                    status=_cell(raw, cmap.get("status")) or "active",
                    location=_cell(raw, cmap.get("location")) or None,
                    meta={"connector": "csv", **extra} if extra else {"connector": "csv"},
                )
            )
        note = None
        if track and missing_ts and since is None:
            note = "csv devices missing updated_at; incremental filter skipped for those rows"
        return rows, high, note

    def _load_work_orders(
        self, path: Path, *, since: str | None, track: bool
    ) -> tuple[list[WorkOrderRow], str | None, str | None]:
        cmap = self._map("work_orders", DEFAULT_WO_MAP)
        updated_col = self._updated_col(cmap)
        rows: list[WorkOrderRow] = []
        high: str | None = since
        for raw in _read_csv(path):
            external_id = _cell(raw, cmap.get("external_id"))
            title = _cell(raw, cmap.get("title"))
            if not external_id or not title:
                continue
            ts = _normalize_ts(_cell(raw, updated_col)) if updated_col else None
            if since is not None and not _after_cursor(ts, since):
                continue
            if ts:
                high = advance_watermark(high, ts)
            rows.append(
                WorkOrderRow(
                    external_id=external_id,
                    title=title,
                    status=_cell(raw, cmap.get("status")) or "open",
                    device_external_id=_cell(raw, cmap.get("device_external_id")) or None,
                    opened_at=_parse_opened_at(_cell(raw, cmap.get("opened_at"))),
                    meta={"connector": "csv", **({"updated_at": ts} if ts else {})},
                )
            )
        return rows, high, None

    def _load_spare_parts(
        self, path: Path, *, since: str | None, track: bool
    ) -> tuple[list[SparePartRow], str | None, str | None]:
        cmap = self._map("spare_parts", DEFAULT_PART_MAP)
        updated_col = self._updated_col(cmap)
        rows: list[SparePartRow] = []
        high: str | None = since
        for raw in _read_csv(path):
            external_id = _cell(raw, cmap.get("external_id"))
            name = _cell(raw, cmap.get("name"))
            if not external_id or not name:
                continue
            ts = _normalize_ts(_cell(raw, updated_col)) if updated_col else None
            if since is not None and not _after_cursor(ts, since):
                continue
            qty_raw = _cell(raw, cmap.get("qty_on_hand")) or "0"
            try:
                qty = float(qty_raw)
            except ValueError as exc:
                raise ValidationAppError(
                    "Invalid qty_on_hand in CSV",
                    detail={"value": qty_raw, "external_id": external_id},
                ) from exc
            if ts:
                high = advance_watermark(high, ts)
            rows.append(
                SparePartRow(
                    external_id=external_id,
                    name=name,
                    sku=_cell(raw, cmap.get("sku")) or None,
                    qty_on_hand=qty,
                    meta={"connector": "csv", **({"updated_at": ts} if ts else {})},
                )
            )
        return rows, high, None
