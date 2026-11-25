"""Record and query canonical entity state history (valid time)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entity_state_history import EntityStateHistory
from app.ontology.state_machines import DeviceState, normalize_device_status


class EntityStateHistoryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record_status(
        self,
        org_id: str,
        canonical_id: str,
        raw_status: object,
        *,
        at: datetime | None = None,
        source: str | None = None,
    ) -> EntityStateHistory:
        """Close open interval and append a new valid-time row."""
        when = at or datetime.now(UTC)
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        normalized = normalize_device_status(raw_status)
        await self.session.execute(
            update(EntityStateHistory)
            .where(
                EntityStateHistory.org_id == org_id,
                EntityStateHistory.canonical_id == canonical_id,
                EntityStateHistory.valid_to.is_(None),
            )
            .values(valid_to=when)
        )
        row = EntityStateHistory(
            org_id=org_id,
            canonical_id=canonical_id,
            standard_status=normalized.standard_status.value,
            status_label=normalized.status_label,
            valid_from=when,
            valid_to=None,
            source=source,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def list_in_window(
        self,
        org_id: str,
        canonical_id: str,
        *,
        window_from: datetime,
        window_to: datetime,
        standard_status: str | None = None,
    ) -> list[EntityStateHistory]:
        """Rows overlapping [window_from, window_to] (valid-time)."""
        if window_from.tzinfo is None:
            window_from = window_from.replace(tzinfo=UTC)
        if window_to.tzinfo is None:
            window_to = window_to.replace(tzinfo=UTC)
        filters = [
            EntityStateHistory.org_id == org_id,
            EntityStateHistory.canonical_id == canonical_id,
            EntityStateHistory.valid_from <= window_to,
            or_(
                EntityStateHistory.valid_to.is_(None),
                EntityStateHistory.valid_to >= window_from,
            ),
        ]
        if standard_status:
            filters.append(
                EntityStateHistory.standard_status == standard_status.strip().upper()
            )
        rows = await self.session.scalars(
            select(EntityStateHistory)
            .where(and_(*filters))
            .order_by(EntityStateHistory.valid_from)
        )
        return list(rows)

    async def downtime_windows(
        self,
        org_id: str,
        canonical_id: str,
        *,
        window_from: datetime,
        window_to: datetime,
    ) -> list[EntityStateHistory]:
        return await self.list_in_window(
            org_id,
            canonical_id,
            window_from=window_from,
            window_to=window_to,
            standard_status=DeviceState.STOPPED.value,
        )
