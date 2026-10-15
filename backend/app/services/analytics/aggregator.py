"""Rebuild the daily analytics summaries of recent days (idempotent: delete + insert per day).

Sources: qa_traces (+ the answer message's citations and the conversation's KB scope),
retrieval_traces (rerank timings), message_feedback and knowledge_gaps. One org-day is
read at a time, so the job never scans whole tables.
"""

import logging
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import case, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.models import (
    ALL_KBS,
    NO_USER,
    AnalyticsDaily,
    AnalyticsDocCitation,
    AnalyticsLlmUsage,
    AnalyticsTopQuestion,
    Conversation,
    GapStatus,
    Grounding,
    KnowledgeGap,
    LlmUsage,
    Message,
    MessageFeedback,
    Organization,
    QaTrace,
    RetrievalTrace,
)
from app.models.base import utcnow
from app.services.analytics.latency import summarize
from app.services.curation.clustering import question_hash

logger = logging.getLogger(__name__)

ID_BATCH = 500
QUERY_MAX_CHARS = 500
# qa_traces.timings key per latency stage; "rerank" comes from the retrieval traces.
TRACE_STAGES = {"retrieval": "retrieval_ms", "first_token": "first_token_ms", "total": "total_ms"}
GENERATED = {Grounding.GROUNDED.value, Grounding.UNCERTAIN.value, Grounding.LOW_GROUNDING.value}
UNANSWERED = {Grounding.NO_EVIDENCE.value, Grounding.LOW_GROUNDING.value}


@dataclass
class _Bucket:
    users: set[str] = field(default_factory=set)
    counts: Counter[str] = field(default_factory=Counter)
    latency: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    # question hash -> [query, count, unanswered]
    questions: dict[str, list[Any]] = field(default_factory=dict)


@dataclass
class AggregationResult:
    days: list[str] = field(default_factory=list)
    orgs: int = 0
    rows: int = 0


def _kb_keys(kbs: Iterable[str | None]) -> list[str]:
    return [ALL_KBS, *sorted({k for k in kbs if k})]


def _citation_kbs(citations: Sequence[dict[str, Any]] | None) -> set[str]:
    return {str(c["kb_id"]) for c in citations or [] if c.get("kb_id")}


def _ms(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


class AnalyticsAggregator:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], settings: Settings):
        self.session_factory = session_factory
        self.settings = settings
        self.tz = ZoneInfo(settings.analytics_timezone)

    def today(self) -> date:
        return datetime.now(self.tz).date()

    def bounds(self, day: date) -> tuple[datetime, datetime]:
        """[start, end) of a local day, in UTC."""
        start = datetime.combine(day, time.min, tzinfo=self.tz)
        return start.astimezone(UTC), (start + timedelta(days=1)).astimezone(UTC)

    async def run_once(
        self, days: int | None = None, org_ids: Sequence[str] | None = None
    ) -> AggregationResult:
        days = max(1, days or self.settings.analytics_refresh_days)
        today = self.today()
        async with self.session_factory() as session:
            orgs = list(org_ids or (await session.execute(select(Organization.id))).scalars())
        result = AggregationResult(orgs=len(orgs))
        for offset in range(days):
            day = today - timedelta(days=offset)
            result.days.append(day.isoformat())
            for org_id in orgs:
                result.rows += await self.refresh_day(org_id, day)
        return result

    async def refresh_day(self, org_id: str, day: date) -> int:
        start, end = self.bounds(day)
        buckets: dict[str, _Bucket] = defaultdict(_Bucket)
        doc_citations: Counter[tuple[str, str, bool]] = Counter()
        async with self.session_factory() as session:
            await self._questions(session, org_id, start, end, buckets, doc_citations)
            await self._feedback(session, org_id, start, end, buckets)
            await self._gaps(session, org_id, start, end, buckets)

            usage_rows = await self._llm_usage(session, org_id, day, start, end)

            for model in (
                AnalyticsDaily,
                AnalyticsTopQuestion,
                AnalyticsDocCitation,
                AnalyticsLlmUsage,
            ):
                await session.execute(delete(model).where(model.org_id == org_id, model.day == day))
            now = utcnow()
            rows: list[Any] = list(usage_rows)
            top_n = self.settings.analytics_top_questions_per_day
            for kb_id, b in buckets.items():
                rows.append(
                    AnalyticsDaily(
                        org_id=org_id,
                        day=day,
                        kb_id=kb_id,
                        active_users=len(b.users),
                        questions=b.counts["questions"],
                        grounded=b.counts[Grounding.GROUNDED.value],
                        uncertain=b.counts[Grounding.UNCERTAIN.value],
                        low_grounding=b.counts[Grounding.LOW_GROUNDING.value],
                        no_evidence=b.counts[Grounding.NO_EVIDENCE.value],
                        chitchat=b.counts[Grounding.CHITCHAT.value],
                        out_of_scope=b.counts[Grounding.OUT_OF_SCOPE.value],
                        errors=b.counts["errors"],
                        citations=b.counts["citations"],
                        feedback_up=b.counts["feedback_up"],
                        feedback_down=b.counts["feedback_down"],
                        gaps_new=b.counts["gaps_new"],
                        gaps_resolved=b.counts["gaps_resolved"],
                        latency={stage: summarize(v) for stage, v in b.latency.items() if v},
                        refreshed_at=now,
                    )
                )
                ranked = sorted(b.questions.items(), key=lambda kv: (-kv[1][1], kv[0]))[:top_n]
                rows.extend(
                    AnalyticsTopQuestion(
                        org_id=org_id,
                        day=day,
                        kb_id=kb_id,
                        query_hash=qhash,
                        query=query,
                        count=count,
                        unanswered=unanswered,
                    )
                    for qhash, (query, count, unanswered) in ranked
                )
            rows.extend(
                AnalyticsDocCitation(
                    org_id=org_id,
                    day=day,
                    kb_id=kb_id,
                    document_id=document_id,
                    is_ko=is_ko,
                    citations=count,
                )
                for (kb_id, document_id, is_ko), count in doc_citations.items()
            )
            session.add_all(rows)
            await session.commit()
        return len(rows)

    # ---- sources ----------------------------------------------------------------------

    async def _llm_usage(
        self, session: AsyncSession, org_id: str, day: date, start: datetime, end: datetime
    ) -> list[AnalyticsLlmUsage]:
        user = func.coalesce(LlmUsage.user_id, NO_USER)
        keys = (user, LlmUsage.feature, LlmUsage.kind, LlmUsage.model)
        stmt = (
            select(
                *keys,
                func.count(),
                func.sum(case((LlmUsage.status == "error", 1), else_=0)),
                func.sum(case((LlmUsage.estimated.is_(True), 1), else_=0)),
                func.sum(case((LlmUsage.fallback.is_(True), 1), else_=0)),
                func.sum(LlmUsage.prompt_tokens),
                func.sum(LlmUsage.completion_tokens),
                func.sum(LlmUsage.total_tokens),
                func.sum(LlmUsage.latency_ms),
            )
            .where(
                LlmUsage.org_id == org_id, LlmUsage.created_at >= start, LlmUsage.created_at < end
            )
            .group_by(*keys)
        )
        return [
            AnalyticsLlmUsage(
                org_id=org_id,
                day=day,
                user_id=user_id,
                feature=feature,
                kind=kind,
                model=model,
                calls=int(calls),
                errors=int(errors or 0),
                estimated_calls=int(estimated or 0),
                fallback_calls=int(fallback or 0),
                prompt_tokens=int(prompt or 0),
                completion_tokens=int(completion or 0),
                total_tokens=int(total or 0),
                latency_ms=int(latency or 0),
            )
            for (
                user_id,
                feature,
                kind,
                model,
                calls,
                errors,
                estimated,
                fallback,
                prompt,
                completion,
                total,
                latency,
            ) in (await session.execute(stmt)).all()
        ]

    async def _questions(
        self,
        session: AsyncSession,
        org_id: str,
        start: datetime,
        end: datetime,
        buckets: dict[str, _Bucket],
        doc_citations: Counter[tuple[str, str, bool]],
    ) -> None:
        stmt = (
            select(
                QaTrace.user_id,
                QaTrace.query,
                QaTrace.grounding,
                QaTrace.status,
                QaTrace.timings,
                QaTrace.retrieval_trace_ids,
                Message.citations,
                Conversation.kb_ids,
            )
            .outerjoin(Message, Message.id == QaTrace.message_id)
            .outerjoin(Conversation, Conversation.id == QaTrace.conversation_id)
            .where(QaTrace.org_id == org_id, QaTrace.created_at >= start, QaTrace.created_at < end)
        )
        traces = (await session.execute(stmt)).all()
        rerank = await self._rerank_ms(
            session, org_id, [rid for t in traces for rid in t.retrieval_trace_ids or []]
        )
        for t in traces:
            citations: list[dict[str, Any]] = list(t.citations or [])
            outcome = "errors" if t.status != "ok" else (t.grounding or "errors")
            samples = {
                stage: _ms((t.timings or {}).get(key)) for stage, key in TRACE_STAGES.items()
            }
            rerank_samples = [rerank[rid] for rid in t.retrieval_trace_ids or [] if rid in rerank]
            if rerank_samples:
                samples["rerank"] = sum(rerank_samples)
            qhash = question_hash(t.query)
            for key in _kb_keys([*_citation_kbs(citations), *(t.kb_ids or [])]):
                b = buckets[key]
                b.counts["questions"] += 1
                b.counts[outcome] += 1
                if t.user_id:
                    b.users.add(t.user_id)
                if outcome in GENERATED:
                    b.counts["citations"] += len(citations)
                for stage, value in samples.items():
                    if value is not None:
                        b.latency[stage].append(value)
                entry = b.questions.setdefault(qhash, [t.query.strip()[:QUERY_MAX_CHARS], 0, 0])
                entry[1] += 1
                if outcome in UNANSWERED:
                    entry[2] += 1
            for c in citations:
                if c.get("document_id"):
                    doc_citations[
                        (str(c.get("kb_id") or ""), str(c["document_id"]), bool(c.get("is_ko")))
                    ] += 1

    async def _rerank_ms(
        self, session: AsyncSession, org_id: str, ids: list[str]
    ) -> dict[str, float]:
        out: dict[str, float] = {}
        unique = list(dict.fromkeys(ids))
        for i in range(0, len(unique), ID_BATCH):
            stmt = select(RetrievalTrace.id, RetrievalTrace.timings).where(
                RetrievalTrace.org_id == org_id, RetrievalTrace.id.in_(unique[i : i + ID_BATCH])
            )
            for rid, timings in (await session.execute(stmt)).all():
                value = _ms((timings or {}).get("rerank_ms"))
                if value is not None:
                    out[rid] = value
        return out

    async def _feedback(
        self,
        session: AsyncSession,
        org_id: str,
        start: datetime,
        end: datetime,
        buckets: dict[str, _Bucket],
    ) -> None:
        stmt = (
            select(MessageFeedback.rating, Message.citations, Conversation.kb_ids)
            .join(Message, Message.id == MessageFeedback.message_id)
            .outerjoin(Conversation, Conversation.id == Message.conversation_id)
            .where(
                MessageFeedback.org_id == org_id,
                MessageFeedback.updated_at >= start,
                MessageFeedback.updated_at < end,
            )
        )
        for rating, citations, kb_ids in (await session.execute(stmt)).all():
            for key in _kb_keys([*_citation_kbs(citations), *(kb_ids or [])]):
                buckets[key].counts[f"feedback_{rating}"] += 1

    async def _gaps(
        self,
        session: AsyncSession,
        org_id: str,
        start: datetime,
        end: datetime,
        buckets: dict[str, _Bucket],
    ) -> None:
        def kbs(kb_id: str | None, kb_ids: list[str] | None) -> list[str]:
            return _kb_keys([kb_id] if kb_id else list(kb_ids or []))

        new = select(KnowledgeGap.kb_id, KnowledgeGap.kb_ids).where(
            KnowledgeGap.org_id == org_id,
            KnowledgeGap.created_at >= start,
            KnowledgeGap.created_at < end,
        )
        for kb_id, kb_ids in (await session.execute(new)).all():
            for key in kbs(kb_id, kb_ids):
                buckets[key].counts["gaps_new"] += 1
        resolved = select(KnowledgeGap.kb_id, KnowledgeGap.kb_ids).where(
            KnowledgeGap.org_id == org_id,
            KnowledgeGap.status == GapStatus.RESOLVED.value,
            KnowledgeGap.resolved_at >= start,
            KnowledgeGap.resolved_at < end,
        )
        for kb_id, kb_ids in (await session.execute(resolved)).all():
            for key in kbs(kb_id, kb_ids):
                buckets[key].counts["gaps_resolved"] += 1
