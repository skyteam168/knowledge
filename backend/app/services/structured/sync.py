"""Apply equipment connector snapshots into local mirror tables."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.exceptions import NotFoundError, ValidationAppError
from app.models import EquipDevice, EquipSparePart, EquipWorkOrder, StructuredSource
from app.repositories.structured_repo import StructuredRepository
from app.services.structured.connectors.base import (
    EquipmentSnapshot,
    build_connector,
    parse_connector_config,
)

logger = logging.getLogger(__name__)


def _counter() -> dict[str, int]:
    return {"created": 0, "updated": 0, "unchanged": 0}


class StructuredSyncExecutor:
    """Pull from a configured CSV/REST connector and upsert equip_* rows."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings | None = None,
        *,
        transport: Any | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.repo = StructuredRepository(session)
        self.transport = transport

    async def sync_source(
        self,
        org_id: str,
        source_id: str,
        *,
        dry_run: bool = False,
        triggered_by: str | None = None,
    ) -> dict[str, Any]:
        source = await self.repo.get_source(org_id, source_id)
        if source is None:
            raise NotFoundError("Structured source not found")
        if not source.enabled:
            raise ValidationAppError("Structured source is disabled")
        config = parse_connector_config(source.meta)
        if config is None:
            raise ValidationAppError(
                "Source has no connector in meta (set meta.connector=csv|rest)"
            )

        connector = build_connector(config, self.settings, transport=self.transport)
        try:
            snapshot = await connector.fetch()
        except Exception as exc:
            await self._mark_failure(source, str(exc), dry_run=dry_run)
            raise

        stats = await self._apply(org_id, source, snapshot, dry_run=dry_run)
        result = {
            "source_id": source.id,
            "source_name": source.name,
            "connector": config.connector,
            "status": "ok",
            "dry_run": dry_run,
            "stats": stats,
            "warnings": list(snapshot.warnings),
            "triggered_by": triggered_by,
            "synced_at": datetime.now(UTC).isoformat(),
        }
        if not dry_run:
            meta = dict(source.meta or {})
            meta["last_sync_at"] = result["synced_at"]
            meta["last_sync_status"] = "ok"
            meta["last_sync_stats"] = stats
            meta.pop("last_sync_error", None)
            source.meta = meta
            await self.session.flush()
        return result

    async def _mark_failure(
        self, source: StructuredSource, error: str, *, dry_run: bool
    ) -> None:
        if dry_run:
            return
        meta = dict(source.meta or {})
        meta["last_sync_at"] = datetime.now(UTC).isoformat()
        meta["last_sync_status"] = "error"
        meta["last_sync_error"] = error[:1000]
        source.meta = meta
        await self.session.flush()

    async def _apply(
        self,
        org_id: str,
        source: StructuredSource,
        snapshot: EquipmentSnapshot,
        *,
        dry_run: bool,
    ) -> dict[str, Any]:
        stats: dict[str, Any] = {
            "devices": _counter(),
            "work_orders": _counter(),
            "spare_parts": _counter(),
        }

        for row in snapshot.devices:
            existing = await self.repo.get_device_by_external(
                org_id, row.external_id, source_id=source.id
            )
            if existing is None:
                stats["devices"]["created"] += 1
                if not dry_run:
                    self.repo.add_device(
                        EquipDevice(
                            org_id=org_id,
                            source_id=source.id,
                            external_id=row.external_id,
                            name=row.name,
                            status=row.status,
                            location=row.location,
                            meta=dict(row.meta),
                        )
                    )
            else:
                changed = (
                    existing.name != row.name
                    or existing.status != row.status
                    or existing.location != row.location
                )
                if changed:
                    stats["devices"]["updated"] += 1
                    if not dry_run:
                        existing.name = row.name
                        existing.status = row.status
                        existing.location = row.location
                        existing.meta = {**(existing.meta or {}), **row.meta}
                else:
                    stats["devices"]["unchanged"] += 1

        for row in snapshot.work_orders:
            existing = await self.repo.get_work_order_by_external(
                org_id, row.external_id, source_id=source.id
            )
            if existing is None:
                stats["work_orders"]["created"] += 1
                if not dry_run:
                    self.repo.add_work_order(
                        EquipWorkOrder(
                            org_id=org_id,
                            source_id=source.id,
                            external_id=row.external_id,
                            device_external_id=row.device_external_id,
                            title=row.title,
                            status=row.status,
                            opened_at=row.opened_at,
                            meta=dict(row.meta),
                        )
                    )
            else:
                changed = (
                    existing.title != row.title
                    or existing.status != row.status
                    or existing.device_external_id != row.device_external_id
                    or existing.opened_at != row.opened_at
                )
                if changed:
                    stats["work_orders"]["updated"] += 1
                    if not dry_run:
                        existing.title = row.title
                        existing.status = row.status
                        existing.device_external_id = row.device_external_id
                        existing.opened_at = row.opened_at
                        existing.meta = {**(existing.meta or {}), **row.meta}
                else:
                    stats["work_orders"]["unchanged"] += 1

        for row in snapshot.spare_parts:
            existing = await self.repo.get_spare_part_by_external(
                org_id, row.external_id, source_id=source.id
            )
            if existing is None:
                stats["spare_parts"]["created"] += 1
                if not dry_run:
                    self.repo.add_spare_part(
                        EquipSparePart(
                            org_id=org_id,
                            source_id=source.id,
                            external_id=row.external_id,
                            name=row.name,
                            sku=row.sku,
                            qty_on_hand=row.qty_on_hand,
                            meta=dict(row.meta),
                        )
                    )
            else:
                changed = (
                    existing.name != row.name
                    or existing.sku != row.sku
                    or float(existing.qty_on_hand) != float(row.qty_on_hand)
                )
                if changed:
                    stats["spare_parts"]["updated"] += 1
                    if not dry_run:
                        existing.name = row.name
                        existing.sku = row.sku
                        existing.qty_on_hand = row.qty_on_hand
                        existing.meta = {**(existing.meta or {}), **row.meta}
                else:
                    stats["spare_parts"]["unchanged"] += 1

        if not dry_run:
            await self.session.flush()
        return stats


async def due_structured_sources(session: AsyncSession) -> list[StructuredSource]:
    """Sources with connector + sync_interval_minutes > 0 that are past due."""
    from sqlalchemy import select

    rows = await session.scalars(
        select(StructuredSource).where(StructuredSource.enabled.is_(True))
    )
    due: list[StructuredSource] = []
    now = datetime.now(UTC)
    for source in rows:
        meta = dict(source.meta or {})
        if not meta.get("connector"):
            continue
        try:
            interval = int(meta.get("sync_interval_minutes") or 0)
        except (TypeError, ValueError):
            continue
        if interval <= 0:
            continue
        last_raw = meta.get("last_sync_at")
        if last_raw:
            try:
                last = datetime.fromisoformat(str(last_raw).replace("Z", "+00:00"))
            except ValueError:
                last = None
            if last is not None and last.tzinfo is None:
                last = last.replace(tzinfo=UTC)
            if last is not None and last + timedelta(minutes=interval) > now:
                continue
        due.append(source)
    return due
