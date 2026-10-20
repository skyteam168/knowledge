"""Post-publish verification: confirm the KO is live and record gap.resolution.verify."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import KnowledgeGap, KnowledgeObject, KoStatus
from app.models.base import utcnow
from app.services.curation.notifications import NotificationKind, notify
from app.services.knowledge.access import RESOURCE_KO

logger = logging.getLogger(__name__)


async def verify_gaps_for_ko(
    session: AsyncSession,
    *,
    org_id: str,
    gap_ids: list[str],
    ko_id: str,
) -> dict[str, Any]:
    """Mark each gap's resolution.verify; notify assignees when the KO is not published."""
    ko = await session.get(KnowledgeObject, ko_id)
    ok = (
        ko is not None
        and ko.org_id == org_id
        and ko.status == KoStatus.PUBLISHED.value
        and ko.published_version is not None
    )
    now = utcnow().isoformat()
    verified = 0
    failed: list[str] = []
    for gap_id in gap_ids:
        gap = await session.get(KnowledgeGap, gap_id)
        if gap is None or gap.org_id != org_id:
            continue
        entry = {
            "checked_at": now,
            "ko_id": ko_id,
            "ok": ok,
            "reason": None if ok else "ko_not_published",
        }
        gap.resolution = {**(gap.resolution or {}), "verify": entry}
        verified += 1
        if not ok:
            failed.append(gap_id)
            if gap.assignee_id:
                await notify(
                    session,
                    org_id,
                    [gap.assignee_id],
                    kind=NotificationKind.GAP_ASSIGNED,
                    title=f"知识缺口发布后校验未通过：{(gap.query or '')[:80]}",
                    body="相关知识条目未处于已发布状态，请检查审核与索引。",
                    resource_type=RESOURCE_KO,
                    resource_id=ko_id,
                    link=f"/curation/gaps/{gap.id}",
                    dedupe_key=f"gap-verify-fail:{gap.id}:{ko_id}",
                )
    await session.commit()
    logger.info(
        "gap_verify_finished",
        extra={"org_id": org_id, "ko_id": ko_id, "verified": verified, "failed": len(failed)},
    )
    return {"verified": verified, "failed": failed, "ok": ok}


async def run_gap_verify(
    session_factory: async_sessionmaker[AsyncSession],
    org_id: str,
    gap_ids: list[str],
    ko_id: str,
) -> dict[str, Any]:
    async with session_factory() as session:
        return await verify_gaps_for_ko(session, org_id=org_id, gap_ids=gap_ids, ko_id=ko_id)


async def load_gap_ids_for_ko(session: AsyncSession, org_id: str, ko_id: str) -> list[str]:
    ko = await session.get(KnowledgeObject, ko_id)
    if ko is None or ko.org_id != org_id:
        return []
    return [str(i) for i in (ko.gap_ids or [])]
