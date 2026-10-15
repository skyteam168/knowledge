from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog


@dataclass
class AuditQuery:
    actor_id: str | None = None
    action: str | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    trace_id: str | None = None
    start: datetime | None = None
    end: datetime | None = None


class AuditLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, log: AuditLog) -> AuditLog:
        self.session.add(log)
        await self.session.flush()
        return log

    def _stmt(self, org_id: str, q: AuditQuery) -> Select[AuditLog]:
        stmt = select(AuditLog).where(AuditLog.org_id == org_id)
        if q.actor_id:
            stmt = stmt.where(AuditLog.actor_id == q.actor_id)
        if q.action:
            stmt = stmt.where(AuditLog.action.startswith(q.action, autoescape=True))
        if q.resource_type:
            stmt = stmt.where(AuditLog.resource_type == q.resource_type)
        if q.resource_id:
            stmt = stmt.where(AuditLog.resource_id == q.resource_id)
        if q.trace_id:
            stmt = stmt.where(AuditLog.trace_id == q.trace_id)
        if q.start:
            stmt = stmt.where(AuditLog.created_at >= q.start)
        if q.end:
            stmt = stmt.where(AuditLog.created_at <= q.end)
        return stmt

    async def search(
        self, org_id: str, q: AuditQuery, page: int, size: int
    ) -> tuple[list[AuditLog], int]:
        stmt = self._stmt(org_id, q)
        total = (
            await self.session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()
        rows = await self.session.execute(
            stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        return list(rows.scalars()), int(total)
