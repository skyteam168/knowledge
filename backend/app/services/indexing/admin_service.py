from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import run_after_commit
from app.core.exceptions import ConflictError, NotFoundError
from app.models import OutboxEvent, OutboxStatus
from app.repositories.base import paginate
from app.repositories.indexing_repo import OutboxRepository
from app.repositories.knowledge_repo import KnowledgeBaseRepository
from app.schemas.common import Page
from app.schemas.indexing import (
    BackendDiffOut,
    ConsistencyReportOut,
    IndexGenerationOut,
    OutboxEventOut,
    OutboxStatsOut,
    RepairQueuedOut,
    RetryResultOut,
)
from app.services.authz import AuthzCache
from app.services.context import BaseService, RequestContext
from app.services.indexing.consistency import BackendDiff, ConsistencyReport
from app.services.indexing.runtime import IndexingRuntime
from app.services.ingest.queue import TaskQueue

RESOURCE_OUTBOX = "outbox_event"
RESOURCE_KB = "kb"
RESOURCE_INDEX = "search_index"
SAMPLE_LIMIT = 200


def _diff_out(diff: BackendDiff) -> BackendDiffOut:
    return BackendDiffOut(
        count=diff.count,
        missing_count=len(diff.missing),
        extra_count=len(diff.extra),
        missing=diff.missing[:SAMPLE_LIMIT],
        extra=diff.extra[:SAMPLE_LIMIT],
    )


def report_out(report: ConsistencyReport) -> ConsistencyReportOut:
    return ConsistencyReportOut(
        kb_id=report.kb_id,
        generation=report.generation,
        checked_at=report.checked_at,
        consistent=report.consistent,
        pg_count=report.pg_count,
        qdrant=_diff_out(report.qdrant),
        opensearch=_diff_out(report.opensearch),
        reindex_documents=sorted(report.reindex),
        skipped_documents=len(report.skipped_documents),
    )


class IndexAdminService(BaseService):
    def __init__(
        self,
        session: AsyncSession,
        ctx: RequestContext,
        authz_cache: AuthzCache,
        *,
        runtime: IndexingRuntime,
        queue: TaskQueue,
    ) -> None:
        super().__init__(session, ctx, authz_cache)
        self.runtime = runtime
        self.queue = queue
        self.outbox = OutboxRepository(session)

    # ---- outbox ----

    async def outbox_stats(self) -> OutboxStatsOut:
        return OutboxStatsOut(**await self.outbox.status_counts(self.org_id))

    async def list_outbox(
        self, *, page: int, size: int, status: str | None, event_type: str | None
    ) -> Page[OutboxEventOut]:
        stmt = self.outbox.search_stmt(self.org_id, status, event_type)
        rows, total = await paginate(self.session, stmt, page, size)
        items = [OutboxEventOut.model_validate(r) for r in rows]
        return Page(items=items, total=total, page=page, size=size)

    async def _event(self, event_id: str) -> OutboxEvent:
        event = await self.outbox.get(event_id)
        if event is None or event.org_id != self.org_id:
            raise NotFoundError("Outbox event not found")
        return event

    async def retry_event(self, event_id: str) -> OutboxEventOut:
        event = await self._event(event_id)
        if event.status != OutboxStatus.DEAD.value:
            raise ConflictError("Only dead-letter events can be retried")
        before = {"status": event.status, "retry_count": event.retry_count}
        await self.outbox.requeue_dead(self.org_id, [event.id])
        await self.session.refresh(event)
        await self.audit.record(
            self.audit_ctx,
            "outbox.retry",
            RESOURCE_OUTBOX,
            event.id,
            before,
            {"status": event.status, "retry_count": event.retry_count},
        )
        return OutboxEventOut.model_validate(event)

    async def retry_all_dead(self) -> RetryResultOut:
        count = await self.outbox.requeue_dead(self.org_id)
        await self.audit.record(
            self.audit_ctx, "outbox.retry_all_dead", RESOURCE_OUTBOX, None, None, {"count": count}
        )
        return RetryResultOut(count=count)

    # ---- generations / consistency ----

    async def generations(self) -> list[IndexGenerationOut]:
        return [
            IndexGenerationOut.model_validate(g) for g in await self.runtime.registry.generations()
        ]

    async def _require_kb(self, kb_id: str) -> None:
        if await KnowledgeBaseRepository(self.session).get(self.org_id, kb_id) is None:
            raise NotFoundError("Knowledge base not found")

    async def check_kb(self, kb_id: str) -> ConsistencyReportOut:
        await self._require_kb(kb_id)
        # Scans can be long: don't keep the request transaction idle meanwhile.
        await self.session.commit()
        return report_out(await self.runtime.consistency.check(self.org_id, kb_id))

    async def queue_repair(self, kb_id: str) -> RepairQueuedOut:
        await self._require_kb(kb_id)
        await self.audit.record(self.audit_ctx, "index.repair", RESOURCE_KB, kb_id)
        org_id, queue = self.org_id, self.queue
        run_after_commit(self.session, lambda: queue.enqueue_index_repair(org_id, kb_id))
        return RepairQueuedOut(queued=True, kb_id=kb_id)

    async def reload_synonyms(self) -> None:
        target = await self.runtime.registry.active() or await self.runtime.registry.bootstrap()
        await self.runtime.backends.text.reload_search_analyzers(target.opensearch_index)
        await self.audit.record(
            self.audit_ctx, "index.reload_synonyms", RESOURCE_INDEX, target.opensearch_index
        )
