from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.repositories.indexing_repo import IndexingRepository
from app.retrieval.cache import ResultCache
from app.services.indexing.indexer import DocumentIndexer
from app.services.indexing.ko_indexer import KnowledgeObjectIndexer
from app.services.indexing.outbox import EventEnvelope, EventHandler, PermanentEventError
from app.services.knowledge.access import RESOURCE_DOCUMENT, RESOURCE_KB, RESOURCE_KO
from app.services.outbox_service import (
    ACL_CHANGED,
    DOCUMENT_CHUNKS_READY,
    DOCUMENT_DELETED,
    KO_DEPRECATED,
    KO_PUBLISHED,
)


class IndexEventHandlers:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        indexer: DocumentIndexer,
        ko_indexer: KnowledgeObjectIndexer,
        result_cache: ResultCache | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.indexer = indexer
        self.ko_indexer = ko_indexer
        self.result_cache = result_cache

    def mapping(self) -> dict[str, EventHandler]:
        return {
            DOCUMENT_CHUNKS_READY: self.on_chunks_ready,
            DOCUMENT_DELETED: self.on_document_deleted,
            ACL_CHANGED: self.on_acl_changed,
            KO_PUBLISHED: self.on_ko_published,
            KO_DEPRECATED: self.on_ko_deprecated,
        }

    async def on_chunks_ready(self, event: EventEnvelope) -> None:
        await self.indexer.index_document(
            str(event.require("document_id")), int(event.require("version"))
        )

    async def on_document_deleted(self, event: EventEnvelope) -> None:
        await self.indexer.delete_document(str(event.require("document_id")))

    async def on_ko_published(self, event: EventEnvelope) -> None:
        await self.ko_indexer.index(str(event.require("ko_id")), int(event.require("version")))

    async def on_ko_deprecated(self, event: EventEnvelope) -> None:
        await self.ko_indexer.delete(str(event.require("ko_id")))

    async def on_acl_changed(self, event: EventEnvelope) -> None:
        resource_type = str(event.require("resource_type"))
        resource_id = str(event.require("resource_id"))
        if resource_type == RESOURCE_KB:
            # KB entries reach every document / KO: inherited ones fully, own-ACL ones via
            # managers.
            async with self.session_factory() as session:
                repo = IndexingRepository(session)
                ids = await repo.active_document_ids(event.org_id, resource_id)
                ko_ids = await repo.indexable_ko_ids(event.org_id, resource_id)
            await self.indexer.refresh_acl(ids)
            await self.ko_indexer.refresh_acl(ko_ids)
        elif resource_type == RESOURCE_DOCUMENT:
            await self.indexer.refresh_acl([resource_id])
        elif resource_type == RESOURCE_KO:
            await self.ko_indexer.refresh_acl([resource_id])
        else:
            raise PermanentEventError(f"unsupported resource_type '{resource_type}'")
        # Only after the indexes carry the new ACL, or a search in between re-caches stale results.
        if self.result_cache is not None:
            await self.result_cache.invalidate_org(event.org_id)

    async def on_dead(self, event: EventEnvelope) -> None:
        if event.event_type != DOCUMENT_CHUNKS_READY:
            return
        document_id = event.payload.get("document_id")
        version = event.payload.get("version")
        if document_id is None or version is None:
            return
        await self.indexer.mark_failed(
            str(document_id),
            int(version),
            f"索引失败（已重试 {event.retry_count + 1} 次），可在管理页重试",
        )
