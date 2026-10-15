"""Dashboard queries. Usage / quality / latency come from the daily summary tables only;
content statistics are cheap indexed queries on documents, KOs and the outbox."""

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, and_, func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import PermissionDeniedError, ValidationAppError
from app.models import (
    ALL_KBS,
    AnalyticsDaily,
    AnalyticsDocCitation,
    AnalyticsTopQuestion,
    Document,
    DocumentStatus,
    KnowledgeBase,
    KnowledgeObject,
    KoStatus,
    Organization,
    OutboxEvent,
    OutboxStatus,
)
from app.models.base import utcnow
from app.repositories.acl_repo import ResourceAclRepository
from app.schemas.analytics import (
    AnalyticsContentOut,
    AnalyticsFiltersOut,
    AnalyticsOverviewOut,
    AnalyticsRefreshOut,
    ContentDocumentOut,
    ContentKoOut,
    DailyPointOut,
    IndexHealthOut,
    KbHeatOut,
    LatencyDailyOut,
    LatencyStatOut,
    NamedRef,
    QualitySummaryOut,
    StatusCountOut,
    TopQuestionOut,
    UsageSummaryOut,
)
from app.services.analytics.aggregator import AnalyticsAggregator
from app.services.analytics.latency import merge
from app.services.authz import AuthzCache
from app.services.context import BaseService, RequestContext
from app.services.knowledge.access import RESOURCE_DOCUMENT, KnowledgeAccess

DEFAULT_RANGE_DAYS = 30
MAX_RANGE_DAYS = 366
LATENCY_STAGES = ("retrieval", "rerank", "first_token", "total")
TOP_QUESTIONS = 20
LIST_LIMIT = 50
COUNTERS = (
    "active_users",
    "questions",
    "grounded",
    "uncertain",
    "low_grounding",
    "no_evidence",
    "chitchat",
    "out_of_scope",
    "errors",
    "citations",
    "feedback_up",
    "feedback_down",
    "gaps_new",
    "gaps_resolved",
)


def _ratio(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def _rates(c: dict[str, int]) -> dict[str, float | None]:
    answered = c["grounded"] + c["uncertain"] + c["low_grounding"]
    return {
        "like_rate": _ratio(c["feedback_up"], c["feedback_up"] + c["feedback_down"]),
        "refusal_rate": _ratio(c["no_evidence"], answered + c["no_evidence"]),
        "low_grounding_rate": _ratio(c["low_grounding"], answered),
        "avg_citations": _ratio(c["citations"], answered),
    }


class AnalyticsService(BaseService):
    def __init__(
        self,
        session: AsyncSession,
        ctx: RequestContext,
        authz_cache: AuthzCache,
        *,
        settings: Settings,
    ) -> None:
        super().__init__(session, ctx, authz_cache)
        self.settings = settings
        self.tz = ZoneInfo(settings.analytics_timezone)

    # ---- scope ------------------------------------------------------------------------

    def _org(self, org_id: str | None) -> str:
        if not org_id or org_id == self.org_id:
            return self.org_id
        if not self.ctx.user.is_platform_admin:
            raise PermissionDeniedError("Only platform administrators can view other organizations")
        return org_id

    def _own(self, org_id: str) -> bool:
        return org_id == self.org_id

    def _readable_kbs(self, org_id: str) -> ColumnElement[bool]:
        if not self._own(org_id):
            return true()
        return KnowledgeAccess(self.session).readable_kb_clause(self.ctx.user)

    def _visible_documents(self, org_id: str) -> ColumnElement[bool]:
        user = self.ctx.user
        if not self._own(org_id) or user.is_superuser:
            return true()
        granted = ResourceAclRepository.granted_ids_stmt(
            org_id, RESOURCE_DOCUMENT, user.principals.pairs()
        )
        return or_(
            Document.acl_inherit.is_(True)
            & Document.kb_id.in_(
                select(KnowledgeBase.id).where(
                    KnowledgeBase.org_id == org_id, self._readable_kbs(org_id)
                )
            ),
            Document.id.in_(granted),
        )

    async def _kbs(self, org_id: str) -> list[NamedRef]:
        stmt = (
            select(KnowledgeBase.id, KnowledgeBase.name)
            .where(
                KnowledgeBase.org_id == org_id,
                KnowledgeBase.deleted_at.is_(None),
                self._readable_kbs(org_id),
            )
            .order_by(KnowledgeBase.name)
        )
        return [NamedRef(id=i, name=n) for i, n in (await self.session.execute(stmt)).all()]

    async def _check_kb(self, org_id: str, kb_id: str | None) -> None:
        if kb_id and kb_id not in {k.id for k in await self._kbs(org_id)}:
            raise PermissionDeniedError("Knowledge base not accessible")

    def _range(self, date_from: date | None, date_to: date | None) -> tuple[date, date]:
        end = date_to or datetime.now(self.tz).date()
        start = date_from or end - timedelta(days=DEFAULT_RANGE_DAYS - 1)
        if start > end:
            raise ValidationAppError("date_from must not be after date_to")
        if (end - start).days + 1 > MAX_RANGE_DAYS:
            raise ValidationAppError(f"The range is limited to {MAX_RANGE_DAYS} days")
        return start, end

    # ---- filters ----------------------------------------------------------------------

    async def filters(self, org_id: str | None) -> AnalyticsFiltersOut:
        org = self._org(org_id)
        stmt = select(Organization.id, Organization.name).order_by(Organization.name)
        if not self.ctx.user.is_platform_admin:
            stmt = stmt.where(Organization.id == self.org_id)
        orgs = [NamedRef(id=i, name=n) for i, n in (await self.session.execute(stmt)).all()]
        return AnalyticsFiltersOut(
            orgs=orgs,
            kbs=await self._kbs(org),
            org_id=org,
            timezone=self.settings.analytics_timezone,
        )

    # ---- usage / quality / latency ------------------------------------------------------

    async def overview(
        self,
        org_id: str | None,
        kb_id: str | None,
        date_from: date | None,
        date_to: date | None,
    ) -> AnalyticsOverviewOut:
        org = self._org(org_id)
        await self._check_kb(org, kb_id)
        start, end = self._range(date_from, date_to)
        key = kb_id or ALL_KBS
        rows = (
            (
                await self.session.execute(
                    select(AnalyticsDaily)
                    .where(
                        AnalyticsDaily.org_id == org,
                        AnalyticsDaily.kb_id == key,
                        AnalyticsDaily.day >= start,
                        AnalyticsDaily.day <= end,
                    )
                    .order_by(AnalyticsDaily.day)
                )
            )
            .scalars()
            .all()
        )
        by_day = {r.day: r for r in rows}
        daily: list[DailyPointOut] = []
        totals: dict[str, int] = defaultdict(int)
        day = start
        while day <= end:
            r = by_day.get(day)
            counts = {c: int(getattr(r, c)) if r else 0 for c in COUNTERS}
            for c, v in counts.items():
                totals[c] += v
            daily.append(DailyPointOut(day=day, **counts, **_rates(counts)))
            day += timedelta(days=1)

        answered = totals["grounded"] + totals["uncertain"] + totals["low_grounding"]
        days = len(daily)
        rates = _rates(totals)
        usage = UsageSummaryOut(
            questions=totals["questions"],
            active_users_avg=round(totals["active_users"] / days, 2) if days else 0.0,
            active_users_peak=max((p.active_users for p in daily), default=0),
            knowledge_questions=answered + totals["no_evidence"],
            answered=answered,
        )
        quality = QualitySummaryOut(
            feedback_up=totals["feedback_up"],
            feedback_down=totals["feedback_down"],
            like_rate=rates["like_rate"],
            refusal_rate=rates["refusal_rate"],
            low_grounding_rate=rates["low_grounding_rate"],
            avg_citations=rates["avg_citations"],
            error_rate=_ratio(totals["errors"], totals["questions"]),
            gaps_new=totals["gaps_new"],
            gaps_resolved=totals["gaps_resolved"],
        )
        latency = [
            LatencyStatOut(stage=s, **merge((r.latency or {}).get(s, {}) for r in rows))
            for s in LATENCY_STAGES
        ]
        latency_daily = [
            LatencyDailyOut(
                day=r.day,
                stages=[
                    LatencyStatOut(stage=s, **merge([(r.latency or {}).get(s, {})]))
                    for s in LATENCY_STAGES
                ],
            )
            for r in rows
        ]
        return AnalyticsOverviewOut(
            org_id=org,
            kb_id=kb_id,
            date_from=start,
            date_to=end,
            usage=usage,
            quality=quality,
            daily=daily,
            latency=latency,
            latency_daily=latency_daily,
            kb_heat=[] if kb_id else await self._kb_heat(org, start, end),
            top_questions=await self._top_questions(org, key, start, end),
            refreshed_at=max((r.refreshed_at for r in rows), default=None),
        )

    async def _kb_heat(self, org_id: str, start: date, end: date) -> list[KbHeatOut]:
        names = {k.id: k.name for k in await self._kbs(org_id)}
        if not names:
            return []
        in_range = and_(
            AnalyticsDaily.org_id == org_id,
            AnalyticsDaily.day >= start,
            AnalyticsDaily.day <= end,
            AnalyticsDaily.kb_id.in_(list(names)),
        )
        stmt = (
            select(
                AnalyticsDaily.kb_id,
                func.sum(AnalyticsDaily.questions),
                func.max(AnalyticsDaily.active_users),
                func.sum(AnalyticsDaily.feedback_down),
                func.sum(AnalyticsDaily.gaps_new),
            )
            .where(in_range)
            .group_by(AnalyticsDaily.kb_id)
        )
        usage = {row[0]: row[1:] for row in (await self.session.execute(stmt)).all()}
        cited_stmt = (
            select(AnalyticsDocCitation.kb_id, func.sum(AnalyticsDocCitation.citations))
            .where(
                AnalyticsDocCitation.org_id == org_id,
                AnalyticsDocCitation.day >= start,
                AnalyticsDocCitation.day <= end,
                AnalyticsDocCitation.kb_id.in_(list(names)),
            )
            .group_by(AnalyticsDocCitation.kb_id)
        )
        cited = {k: int(v or 0) for k, v in (await self.session.execute(cited_stmt)).all()}
        heat = [
            KbHeatOut(
                kb_id=kb_id,
                kb_name=name,
                questions=int((usage.get(kb_id) or (0,))[0] or 0),
                active_users_peak=int((usage.get(kb_id) or (0, 0))[1] or 0),
                feedback_down=int((usage.get(kb_id) or (0, 0, 0))[2] or 0),
                gaps_new=int((usage.get(kb_id) or (0, 0, 0, 0))[3] or 0),
                citations=cited.get(kb_id, 0),
            )
            for kb_id, name in names.items()
        ]
        heat.sort(key=lambda h: (-h.questions, -h.citations, h.kb_name))
        return heat

    async def _top_questions(
        self, org_id: str, kb_key: str, start: date, end: date
    ) -> list[TopQuestionOut]:
        total = func.sum(AnalyticsTopQuestion.count)
        stmt = (
            select(
                func.max(AnalyticsTopQuestion.query),
                total,
                func.sum(AnalyticsTopQuestion.unanswered),
            )
            .where(
                AnalyticsTopQuestion.org_id == org_id,
                AnalyticsTopQuestion.kb_id == kb_key,
                AnalyticsTopQuestion.day >= start,
                AnalyticsTopQuestion.day <= end,
            )
            .group_by(AnalyticsTopQuestion.query_hash)
            .order_by(total.desc())
            .limit(TOP_QUESTIONS)
        )
        return [
            TopQuestionOut(query=q, count=int(c or 0), unanswered=int(u or 0))
            for q, c, u in (await self.session.execute(stmt)).all()
        ]

    # ---- content ----------------------------------------------------------------------

    async def content(self, org_id: str | None, kb_id: str | None) -> AnalyticsContentOut:
        org = self._org(org_id)
        await self._check_kb(org, kb_id)
        kbs = {k.id: k.name for k in await self._kbs(org)}
        visible = self._visible_documents(org)
        live = [Document.org_id == org, Document.deleted_at.is_(None), visible]
        live.append(Document.kb_id == kb_id if kb_id else Document.kb_id.in_(list(kbs)))
        now = utcnow()

        status_rows = (
            await self.session.execute(
                select(
                    Document.status, func.count(), func.coalesce(func.sum(Document.chunk_count), 0)
                )
                .where(*live)
                .group_by(Document.status)
            )
        ).all()
        document_status = [StatusCountOut(status=s, count=int(c)) for s, c, _ in status_rows]
        documents = sum(s.count for s in document_status)
        chunks = sum(int(n or 0) for _, _, n in status_rows)

        ko_scope = [
            KnowledgeObject.org_id == org,
            KnowledgeObject.published_version.is_not(None),
            KnowledgeObject.status != KoStatus.DEPRECATED.value,
            KnowledgeObject.kb_id == kb_id if kb_id else KnowledgeObject.kb_id.in_(list(kbs)),
        ]
        published_kos = int(
            (await self.session.execute(select(func.count()).where(*ko_scope))).scalar_one()
        )

        def doc_out(d: Document, last_cited: date | None = None) -> ContentDocumentOut:
            return ContentDocumentOut(
                id=d.id,
                title=d.title,
                filename=d.filename,
                kb_id=d.kb_id,
                kb_name=kbs.get(d.kb_id, ""),
                status=d.status,
                created_at=d.created_at,
                updated_at=d.updated_at,
                effective_to=d.effective_to,
                last_cited=last_cited,
                error_message=d.error_message,
            )

        failed = (
            (
                await self.session.execute(
                    select(Document)
                    .where(*live, Document.status == DocumentStatus.FAILED.value)
                    .order_by(Document.updated_at.desc())
                    .limit(LIST_LIMIT)
                )
            )
            .scalars()
            .all()
        )
        index = IndexHealthOut(
            **await self._outbox(org), failed_documents=[doc_out(d) for d in failed]
        )

        zombie_days = self.settings.analytics_zombie_days
        cutoff = now - timedelta(days=zombie_days)
        cutoff_day = (now.astimezone(self.tz) - timedelta(days=zombie_days)).date()
        cited_recently = select(AnalyticsDocCitation.document_id).where(
            AnalyticsDocCitation.org_id == org, AnalyticsDocCitation.day >= cutoff_day
        )
        zombie_where = [
            *live,
            Document.status == DocumentStatus.INDEXED.value,
            Document.created_at < cutoff,
            Document.id.not_in(cited_recently),
        ]
        zombie_total = int(
            (await self.session.execute(select(func.count()).where(*zombie_where))).scalar_one()
        )
        zombies = (
            (
                await self.session.execute(
                    select(Document)
                    .where(*zombie_where)
                    .order_by(Document.created_at)
                    .limit(LIST_LIMIT)
                )
            )
            .scalars()
            .all()
        )
        last_cited = await self._last_cited(org, [d.id for d in zombies])

        expiring_days = self.settings.analytics_expiring_days
        horizon = now + timedelta(days=expiring_days)
        expired = int(
            (
                await self.session.execute(
                    select(func.count()).where(
                        *live, Document.effective_to.is_not(None), Document.effective_to < now
                    )
                )
            ).scalar_one()
        )
        expiring = (
            (
                await self.session.execute(
                    select(Document)
                    .where(*live, Document.effective_to >= now, Document.effective_to <= horizon)
                    .order_by(Document.effective_to)
                    .limit(LIST_LIMIT)
                )
            )
            .scalars()
            .all()
        )
        expiring_kos = (
            (
                await self.session.execute(
                    select(KnowledgeObject)
                    .where(
                        *ko_scope,
                        KnowledgeObject.effective_to >= now,
                        KnowledgeObject.effective_to <= horizon,
                    )
                    .order_by(KnowledgeObject.effective_to)
                    .limit(LIST_LIMIT)
                )
            )
            .scalars()
            .all()
        )
        return AnalyticsContentOut(
            org_id=org,
            kb_id=kb_id,
            knowledge_bases=1 if kb_id else len(kbs),
            documents=documents,
            chunks=chunks,
            published_kos=published_kos,
            document_status=document_status,
            index=index,
            zombie_days=zombie_days,
            zombie_total=zombie_total,
            zombie_documents=[doc_out(d, last_cited.get(d.id)) for d in zombies],
            expiring_days=expiring_days,
            expired_documents=expired,
            expiring_documents=[doc_out(d) for d in expiring],
            expiring_kos=[
                ContentKoOut(
                    id=k.id,
                    title=k.title,
                    kb_id=k.kb_id,
                    kb_name=kbs.get(k.kb_id, ""),
                    effective_to=k.effective_to,
                )
                for k in expiring_kos
            ],
        )

    async def _outbox(self, org_id: str) -> dict[str, Any]:
        rows = (
            await self.session.execute(
                select(OutboxEvent.status, func.count(), func.min(OutboxEvent.created_at))
                .where(
                    OutboxEvent.org_id == org_id,
                    OutboxEvent.status.in_(
                        [
                            OutboxStatus.PENDING.value,
                            OutboxStatus.PROCESSING.value,
                            OutboxStatus.DEAD.value,
                        ]
                    ),
                )
                .group_by(OutboxEvent.status)
            )
        ).all()
        counts = {s: int(c) for s, c, _ in rows}
        oldest = next((m for s, _, m in rows if s == OutboxStatus.PENDING.value), None)
        if oldest is not None and oldest.tzinfo is None:
            oldest = oldest.replace(tzinfo=UTC)
        return {
            "outbox_pending": counts.get(OutboxStatus.PENDING.value, 0),
            "outbox_processing": counts.get(OutboxStatus.PROCESSING.value, 0),
            "outbox_dead": counts.get(OutboxStatus.DEAD.value, 0),
            "oldest_pending_seconds": (
                round((utcnow() - oldest).total_seconds(), 1) if oldest else None
            ),
        }

    async def _last_cited(self, org_id: str, ids: list[str]) -> dict[str, date]:
        if not ids:
            return {}
        stmt = (
            select(AnalyticsDocCitation.document_id, func.max(AnalyticsDocCitation.day))
            .where(AnalyticsDocCitation.org_id == org_id, AnalyticsDocCitation.document_id.in_(ids))
            .group_by(AnalyticsDocCitation.document_id)
        )
        return {d: day for d, day in (await self.session.execute(stmt)).all()}

    # ---- refresh ----------------------------------------------------------------------

    async def refresh(self, aggregator: AnalyticsAggregator, days: int) -> AnalyticsRefreshOut:
        result = await aggregator.run_once(days, org_ids=[self.org_id])
        await self.audit.record(
            self.audit_ctx, "analytics.refresh", "analytics", self.org_id, None, {"days": days}
        )
        return AnalyticsRefreshOut(days=result.days, rows=result.rows)
