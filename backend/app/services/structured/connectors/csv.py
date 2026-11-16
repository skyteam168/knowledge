"""CSV file connector for equipment mirror rows."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.core.exceptions import ValidationAppError
from app.services.structured.connectors.base import (
    DeviceRow,
    EquipmentConnector,
    EquipmentSnapshot,
    SparePartRow,
    StructuredConnectorConfig,
    WorkOrderRow,
)

DEFAULT_DEVICE_MAP = {
    "external_id": "external_id",
    "name": "name",
    "status": "status",
    "location": "location",
}
DEFAULT_WO_MAP = {
    "external_id": "external_id",
    "title": "title",
    "status": "status",
    "device_external_id": "device_external_id",
    "opened_at": "opened_at",
}
DEFAULT_PART_MAP = {
    "external_id": "external_id",
    "name": "name",
    "sku": "sku",
    "qty_on_hand": "qty_on_hand",
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


class CsvEquipmentConnector(EquipmentConnector):
    kind = "csv"

    def __init__(self, config: StructuredConnectorConfig, settings: Settings) -> None:
        super().__init__(config, settings)
        assert config.csv is not None

    def _map(self, object_kind: str, defaults: dict[str, str]) -> dict[str, str]:
        override = self.config.column_map.get(object_kind) or {}
        return {**defaults, **override}

    async def fetch(self) -> EquipmentSnapshot:
        warnings: list[str] = []
        devices: list[DeviceRow] = []
        work_orders: list[WorkOrderRow] = []
        spare_parts: list[SparePartRow] = []
        csv_cfg = self.config.csv
        assert csv_cfg is not None

        if csv_cfg.devices:
            devices = self._load_devices(Path(csv_cfg.devices))
        else:
            warnings.append("csv.devices not configured")
        if csv_cfg.work_orders:
            work_orders = self._load_work_orders(Path(csv_cfg.work_orders))
        if csv_cfg.spare_parts:
            spare_parts = self._load_spare_parts(Path(csv_cfg.spare_parts))

        return EquipmentSnapshot(
            devices=devices,
            work_orders=work_orders,
            spare_parts=spare_parts,
            warnings=warnings,
        )

    def _load_devices(self, path: Path) -> list[DeviceRow]:
        cmap = self._map("devices", DEFAULT_DEVICE_MAP)
        rows: list[DeviceRow] = []
        for raw in _read_csv(path):
            external_id = _cell(raw, cmap.get("external_id"))
            name = _cell(raw, cmap.get("name"))
            if not external_id or not name:
                continue
            extra = {
                k: v
                for k, v in raw.items()
                if k and k not in set(cmap.values()) and v
            }
            rows.append(
                DeviceRow(
                    external_id=external_id,
                    name=name,
                    status=_cell(raw, cmap.get("status")) or "active",
                    location=_cell(raw, cmap.get("location")) or None,
                    meta={"connector": "csv", **extra} if extra else {"connector": "csv"},
                )
            )
        return rows

    def _load_work_orders(self, path: Path) -> list[WorkOrderRow]:
        cmap = self._map("work_orders", DEFAULT_WO_MAP)
        rows: list[WorkOrderRow] = []
        for raw in _read_csv(path):
            external_id = _cell(raw, cmap.get("external_id"))
            title = _cell(raw, cmap.get("title"))
            if not external_id or not title:
                continue
            rows.append(
                WorkOrderRow(
                    external_id=external_id,
                    title=title,
                    status=_cell(raw, cmap.get("status")) or "open",
                    device_external_id=_cell(raw, cmap.get("device_external_id")) or None,
                    opened_at=_parse_opened_at(_cell(raw, cmap.get("opened_at"))),
                    meta={"connector": "csv"},
                )
            )
        return rows

    def _load_spare_parts(self, path: Path) -> list[SparePartRow]:
        cmap = self._map("spare_parts", DEFAULT_PART_MAP)
        rows: list[SparePartRow] = []
        for raw in _read_csv(path):
            external_id = _cell(raw, cmap.get("external_id"))
            name = _cell(raw, cmap.get("name"))
            if not external_id or not name:
                continue
            qty_raw = _cell(raw, cmap.get("qty_on_hand")) or "0"
            try:
                qty = float(qty_raw)
            except ValueError as exc:
                raise ValidationAppError(
                    "Invalid qty_on_hand in CSV",
                    detail={"value": qty_raw, "external_id": external_id},
                ) from exc
            rows.append(
                SparePartRow(
                    external_id=external_id,
                    name=name,
                    sku=_cell(raw, cmap.get("sku")) or None,
                    qty_on_hand=qty,
                    meta={"connector": "csv"},
                )
            )
        return rows
