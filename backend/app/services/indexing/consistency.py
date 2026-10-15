"""Per-KB comparison of PG (truth) with Qdrant and OpenSearch, plus repair."""

import logging
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Document, DocumentStatus
from app.models.base import utcnow
from app.repositories.indexing_repo import IndexingRepository
from app.retrieval.backends import SearchBackends
from app.retrieval.records import IndexedRef
from app.services.indexing.generations import GenerationRegistry, IndexTarget
from app.services.indexing.indexer import Backend, DocumentIndexer, IndexOutcome
from app.services.indexing.ko_indexer import KnowledgeObjectIndexer

logger = logging.getLogger(__name__)


@dataclass
class BackendDiff:
    count: int
    missing: list[str] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)

    @property
    def consistent(self) -> bool:
        return not self.missing and not self.extra


@dataclass
class ConsistencyReport:
    org_id: str
    kb_id: str
    generation: int
    checked_at: datetime
    pg_count: int
    qdrant: BackendDiff
    opensearch: BackendDiff
    # Documents to re-index (chunks missing in at least one backend) -> missing backends.
    reindex: dict[str, list[Backend]] = field(default_factory=dict)
    # Published knowledge objects with missing entries -> missing backends.
    reindex_kos: dict[str, list[Backend]] = field(default_factory=dict)
    # In-flight documents (being parsed / indexed) are excluded from the comparison.
    skipped_documents: list[str] = field(default_factory=list)

    @property
    def consistent(self) -> bool:
        return self.qdrant.consistent and self.opensearch.consistent


@dataclass
class RepairResult:
    reindexed_documents: list[str]
    reindexed_kos: list[str]
    deleted_qdrant: int
    deleted_opensearch: int
    report: ConsistencyReport


def _expected_documents(docs: list[Document]) -> tuple[set[str], set[str]]:
    """(documents whose current chunks must be indexed, documents to ignore)."""
    expected: set[str] = set()
    for doc in docs:
        if doc.status == DocumentStatus.INDEXED.value:
            expected.add(doc.id)
        elif doc.status == DocumentStatus.FAILED.value and doc.chunked_at is not None:
            # Chunked but indexing failed: repair should index it.
            expected.add(doc.id)
    return expected, {d.id for d in docs} - expected


def _diff(expected: dict[str, str], found: dict[str, IndexedRef], ignored: set[str]) -> BackendDiff:
    return BackendDiff(
        count=len(found),
        missing=sorted(set(expected) - set(found)),
        extra=sorted(
            cid
            for cid, ref in found.items()
            if cid not in expected and ref.document_id not in ignored
        ),
    )


class ConsistencyChecker:
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

    async def _target(self) -> IndexTarget:
        return await self.registry.active() or await self.registry.bootstrap()

    async def check(self, org_id: str, kb_id: str) -> ConsistencyReport:
        target = await self._target()
        async with self.session_factory() as session:
            repo = IndexingRepository(session)
            docs = await repo.active_documents(org_id, kb_id)
            expected_docs, ignored = _expected_documents(docs)
            expected = dict(await repo.index_chunk_ids(sorted(expected_docs)))
            ko_ids = await repo.indexable_ko_ids(org_id, kb_id)
            ko_entries = {eid: kid for eid, kid, _ in await repo.indexable_ko_entry_ids(ko_ids)}
        expected.update(ko_entries)

        await self.backends.text.refresh(target.opensearch_index)
        in_qdrant = await self.backends.vector.scan(target.qdrant_collection, org_id, kb_id)
        in_opensearch = await self.backends.text.scan(target.opensearch_index, org_id, kb_id)
        qdrant = _diff(expected, in_qdrant, ignored)
        opensearch = _diff(expected, in_opensearch, ignored)

        reindex: dict[str, list[Backend]] = {}
        reindex_kos: dict[str, list[Backend]] = {}
        for backend, diff in ((Backend.VECTOR, qdrant), (Backend.TEXT, opensearch)):
            for cid in diff.missing:
                bucket = reindex_kos if cid in ko_entries else reindex
                backends = bucket.setdefault(expected[cid], [])
                if backend not in backends:
                    backends.append(backend)
        # Failed documents are re-indexed even when nothing is missing (status must recover).
        for doc in docs:
            if doc.id in expected_docs and doc.status == DocumentStatus.FAILED.value:
                reindex.setdefault(doc.id, [Backend.VECTOR, Backend.TEXT])

        report = ConsistencyReport(
            org_id=org_id,
            kb_id=kb_id,
            generation=target.version,
            checked_at=utcnow(),
            pg_count=len(expected),
            qdrant=qdrant,
            opensearch=opensearch,
            reindex=reindex,
            reindex_kos=reindex_kos,
            skipped_documents=sorted(ignored),
        )
        logger.info(
            "index_consistency_checked",
            extra={
                "kb_id": kb_id,
                "consistent": report.consistent,
                "pg": report.pg_count,
                "qdrant": qdrant.count,
                "opensearch": opensearch.count,
            },
        )
        return report

    async def repair(self, org_id: str, kb_id: str) -> RepairResult:
        report = await self.check(org_id, kb_id)
        target = await self._target()
        if report.qdrant.extra:
            await self.backends.vector.delete_ids(target.qdrant_collection, report.qdrant.extra)
        if report.opensearch.extra:
            await self.backends.text.delete_ids(target.opensearch_index, report.opensearch.extra)
        reindexed: list[str] = []
        for document_id, backends in sorted(report.reindex.items()):
            result = await self.indexer.index_document(
                document_id, force=True, targets=[target], backends=set(backends)
            )
            if result.outcome == IndexOutcome.INDEXED:
                reindexed.append(document_id)
        reindexed_kos: list[str] = []
        for ko_id, backends in sorted(report.reindex_kos.items()):
            result = await self.ko_indexer.index(ko_id, targets=[target], backends=set(backends))
            if result.outcome == IndexOutcome.INDEXED:
                reindexed_kos.append(ko_id)
        after = await self.check(org_id, kb_id)
        logger.info(
            "index_repaired",
            extra={"kb_id": kb_id, "reindexed": len(reindexed), "consistent": after.consistent},
        )
        return RepairResult(
            reindexed_documents=reindexed,
            reindexed_kos=reindexed_kos,
            deleted_qdrant=len(report.qdrant.extra),
            deleted_opensearch=len(report.opensearch.extra),
            report=after,
        )
