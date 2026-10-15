"""Full rebuild from PG into a new generation, then an atomic alias switch (zero downtime).

While building, event handlers write to both the active and the new generation, so changes
made during the rebuild are not lost; readers keep using the aliases until the switch.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.llm import EmbeddingSpec
from app.models import DocumentStatus
from app.repositories.indexing_repo import IndexingRepository
from app.retrieval.backends import SearchBackends
from app.services.indexing.generations import GenerationRegistry, IndexTarget
from app.services.indexing.indexer import DocumentIndexer, IndexOutcome
from app.services.indexing.ko_indexer import KnowledgeObjectIndexer

logger = logging.getLogger(__name__)

REBUILD_STATUSES = (DocumentStatus.INDEXED.value,)


class RebuildVerificationError(Exception):
    pass


@dataclass
class RebuildResult:
    version: int
    documents: int
    chunks: int
    pg_chunks: int
    qdrant_points: int
    opensearch_docs: int
    activated: bool

    def stats(self) -> dict[str, object]:
        return {
            "documents": self.documents,
            "chunks": self.chunks,
            "pg_chunks": self.pg_chunks,
            "qdrant_points": self.qdrant_points,
            "opensearch_docs": self.opensearch_docs,
        }


class IndexRebuilder:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        backends: SearchBackends,
        registry: GenerationRegistry,
        indexer: DocumentIndexer,
        ko_indexer: KnowledgeObjectIndexer,
    ) -> None:
        self.session_factory = session_factory
        self.backends = backends
        self.registry = registry
        self.indexer = indexer
        self.ko_indexer = ko_indexer

    async def rebuild(
        self,
        spec: EmbeddingSpec | None = None,
        *,
        batch_size: int = 100,
        strict: bool = False,
        activate: bool = True,
        drop_old: bool = False,
        progress: Callable[[int, int], None] | None = None,
    ) -> RebuildResult:
        previous = await self.registry.active()
        target = await self.registry.create_building(spec or self.indexer.gateway.default_embedding)
        logger.info("index_rebuild_started", extra={"version": target.version})
        try:
            documents, chunks = await self._copy_all(target, batch_size, progress)
            result = await self._verify(target, documents, chunks)
            if strict and not (result.pg_chunks == result.qdrant_points == result.opensearch_docs):
                raise RebuildVerificationError(f"count mismatch after rebuild: {result.stats()}")
            if activate:
                await self.registry.activate(target.version, result.stats())
                result.activated = True
        except BaseException as exc:
            await self.registry.mark_failed(target.version, f"{type(exc).__name__}: {exc}")
            raise
        if activate and drop_old and previous is not None:
            await self.registry.drop_physical(previous.version)
        logger.info("index_rebuild_finished", extra={"version": target.version, **result.stats()})
        return result

    async def _copy_all(
        self,
        target: IndexTarget,
        batch_size: int,
        progress: Callable[[int, int], None] | None,
    ) -> tuple[int, int]:
        documents = chunks = 0
        after: str | None = None
        while True:
            async with self.session_factory() as session:
                ids = await IndexingRepository(session).document_ids_after(
                    REBUILD_STATUSES, after, batch_size
                )
            if not ids:
                break
            for document_id in ids:
                result = await self.indexer.index_document(
                    document_id, force=True, targets=[target], update_status=False
                )
                if result.outcome == IndexOutcome.INDEXED:
                    documents += 1
                    chunks += result.chunks
            after = ids[-1]
            if progress is not None:
                progress(documents, chunks)

        # Published knowledge objects are derived from PG too (their entries count as chunks).
        after = None
        while True:
            async with self.session_factory() as session:
                ids = await IndexingRepository(session).indexable_ko_ids_after(after, batch_size)
            if not ids:
                return documents, chunks
            for ko_id in ids:
                result = await self.ko_indexer.index(ko_id, targets=[target])
                if result.outcome == IndexOutcome.INDEXED:
                    chunks += result.chunks
            after = ids[-1]
            if progress is not None:
                progress(documents, chunks)

    async def _verify(self, target: IndexTarget, documents: int, chunks: int) -> RebuildResult:
        async with self.session_factory() as session:
            repo = IndexingRepository(session)
            pg_chunks = await repo.count_index_chunks(REBUILD_STATUSES)
            pg_chunks += await repo.count_indexable_ko_entries()
        await self.backends.text.refresh(target.opensearch_index)
        return RebuildResult(
            version=target.version,
            documents=documents,
            chunks=chunks,
            pg_chunks=pg_chunks,
            qdrant_points=await self.backends.vector.count(target.qdrant_collection),
            opensearch_docs=await self.backends.text.count(target.opensearch_index),
            activated=False,
        )
