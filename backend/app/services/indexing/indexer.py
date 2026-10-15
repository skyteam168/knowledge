"""Writes document chunks into Qdrant + OpenSearch. Every operation is idempotent.

Idempotency: points / docs are keyed by chunk_id (deterministic per document, version, seq),
stale versions are removed by doc_version, and work for a superseded version is skipped.
Races with concurrent changes are closed by re-reading PG after writing:
- the document got a new version or was deleted meanwhile -> remove what was just written;
- its ACL changed meanwhile -> re-apply the fresh principals (the acl.changed handler may
  have run before our points existed).
"""

import logging
from collections import defaultdict
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.llm import EmbeddingSpec, LLMGateway
from app.llm.usage import FEATURE_INDEXING, STAGE_INDEX, usage_scope
from app.models import Chunk, Document, DocumentStatus
from app.repositories.indexing_repo import IndexingRepository
from app.retrieval.backends import SearchBackends
from app.retrieval.records import ChunkRecord
from app.services.indexing.generations import GenerationRegistry, IndexTarget
from app.services.indexing.principals import compute_read_principals
from app.services.ingest.parsers.base import detect_kind

logger = logging.getLogger(__name__)

MAX_ERROR_LENGTH = 2000


class Backend(StrEnum):
    VECTOR = "qdrant"
    TEXT = "opensearch"


ALL_BACKENDS: frozenset[Backend] = frozenset(Backend)


class IndexOutcome(StrEnum):
    INDEXED = "indexed"
    ALREADY_INDEXED = "already_indexed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class IndexResult:
    outcome: IndexOutcome
    chunks: int = 0


def _is_current(doc: Document | None, version: int) -> bool:
    return doc is not None and doc.deleted_at is None and doc.version == version


def document_type(filename: str, mime_type: str | None) -> str:
    kind = detect_kind(filename, mime_type)
    return kind.value if kind is not None else "other"


def to_record(doc: Document, chunk: Chunk, principals: list[str]) -> ChunkRecord:
    return ChunkRecord(
        chunk_id=chunk.id,
        org_id=doc.org_id,
        kb_id=doc.kb_id,
        document_id=doc.id,
        doc_version=chunk.document_version,
        parent_id=chunk.parent_id,
        heading_path=list(chunk.heading_path or []),
        chunk_type=chunk.chunk_type,
        tags=list(doc.tags or []),
        created_at=chunk.created_at,
        acl_read_principals=principals,
        is_ko=False,
        title=doc.title,
        content=chunk.content,
        page_start=chunk.page_start,
        page_end=chunk.page_end,
        doc_type=document_type(doc.filename, doc.mime_type),
    )


class DocumentIndexer:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        backends: SearchBackends,
        gateway: LLMGateway,
        registry: GenerationRegistry,
    ) -> None:
        self.session_factory = session_factory
        self.backends = backends
        self.gateway = gateway
        self.registry = registry

    # ---- document.chunks_ready ----

    async def index_document(
        self,
        document_id: str,
        version: int | None = None,
        *,
        force: bool = False,
        targets: Sequence[IndexTarget] | None = None,
        backends: Collection[Backend] = ALL_BACKENDS,
        update_status: bool = True,
    ) -> IndexResult:
        """Index the given version (None = current) of a document into `targets`.

        `force` re-indexes a document already marked indexed (repair / rebuild);
        `update_status=False` leaves documents.status alone (rebuild into a new generation).
        """
        async with self.session_factory() as session:
            doc = await session.get(Document, document_id)
            if version is None and doc is not None:
                version = doc.version
            if version is None or not _is_current(doc, version):
                logger.info(
                    "index_skipped_superseded",
                    extra={"document_id": document_id, "version": version},
                )
                return IndexResult(IndexOutcome.SKIPPED)
            assert doc is not None
            if doc.status == DocumentStatus.INDEXED.value and not force:
                return IndexResult(IndexOutcome.ALREADY_INDEXED)
            if update_status:
                doc.status = DocumentStatus.INDEXING.value
                doc.error_message = None
                await session.commit()
            chunks = await IndexingRepository(session).index_chunks(document_id, version)
            principals = (await compute_read_principals(session, [doc]))[doc.id]
            records = [to_record(doc, c, principals) for c in chunks]

        targets = list(targets) if targets is not None else await self.registry.write_targets()
        await self.write_records(records, targets, document_id, version, backends)

        async with self.session_factory() as session:
            doc = await session.get(Document, document_id)
            if not _is_current(doc, version):
                await self.remove_ids(targets, [r.chunk_id for r in records], backends)
                logger.info(
                    "index_superseded_during_write",
                    extra={"document_id": document_id, "version": version},
                )
                return IndexResult(IndexOutcome.SKIPPED)
            assert doc is not None
            fresh = (await compute_read_principals(session, [doc]))[doc.id]
            if fresh != principals:
                await self.set_acl(targets, [document_id], fresh, backends)
            if update_status:
                doc.status = DocumentStatus.INDEXED.value
                doc.error_message = None
                await session.commit()
        logger.info(
            "document_indexed",
            extra={
                "document_id": document_id,
                "version": version,
                "chunks": len(records),
                "targets": [t.version for t in targets],
            },
        )
        return IndexResult(IndexOutcome.INDEXED, len(records))

    async def write_records(
        self,
        records: list[ChunkRecord],
        targets: Sequence[IndexTarget],
        document_id: str,
        version: int,
        backends: Collection[Backend],
    ) -> None:
        # Embed for every target before writing anything: a failing model call leaves no
        # partial state, and generations sharing an embedding space share the vectors.
        vectors: dict[EmbeddingSpec, list[list[float]]] = {}
        if Backend.VECTOR in backends and records:
            texts = [r.embedding_text() for r in records]
            with usage_scope(feature=FEATURE_INDEXING, stage=STAGE_INDEX, org_id=records[0].org_id):
                for target in targets:
                    if target.embedding not in vectors:
                        vectors[target.embedding] = await self.gateway.embedding(
                            target.embedding
                        ).embed(texts)

        for target in targets:
            if Backend.VECTOR in backends:
                if records:
                    await self.backends.vector.upsert(
                        target.qdrant_collection, records, vectors[target.embedding]
                    )
                await self.backends.vector.delete_stale_versions(
                    target.qdrant_collection, document_id, version
                )
            if Backend.TEXT in backends:
                if records:
                    await self.backends.text.upsert(target.opensearch_index, records)
                await self.backends.text.delete_stale_versions(
                    target.opensearch_index, document_id, version
                )

    async def remove_ids(
        self, targets: Sequence[IndexTarget], chunk_ids: list[str], backends: Collection[Backend]
    ) -> None:
        if not chunk_ids:
            return
        for target in targets:
            if Backend.VECTOR in backends:
                await self.backends.vector.delete_ids(target.qdrant_collection, chunk_ids)
            if Backend.TEXT in backends:
                await self.backends.text.delete_ids(target.opensearch_index, chunk_ids)

    async def set_acl(
        self,
        targets: Sequence[IndexTarget],
        document_ids: list[str],
        principals: list[str],
        backends: Collection[Backend] = ALL_BACKENDS,
    ) -> None:
        for target in targets:
            if Backend.VECTOR in backends:
                await self.backends.vector.set_acl(
                    target.qdrant_collection, document_ids, principals
                )
            if Backend.TEXT in backends:
                await self.backends.text.set_acl(target.opensearch_index, document_ids, principals)

    # ---- document.deleted ----

    async def delete_document(self, document_id: str) -> bool:
        async with self.session_factory() as session:
            doc = await session.get(Document, document_id)
            if doc is not None and doc.deleted_at is None:
                logger.warning("index_delete_skipped_active", extra={"document_id": document_id})
                return False
        for target in await self.registry.write_targets():
            await self.backends.vector.delete_documents(target.qdrant_collection, [document_id])
            await self.backends.text.delete_documents(target.opensearch_index, [document_id])
        logger.info("document_unindexed", extra={"document_id": document_id})
        return True

    # ---- acl.changed ----

    async def refresh_acl(self, document_ids: Sequence[str]) -> int:
        """Re-materialize acl_read_principals of documents in place (no re-embedding)."""
        async with self.session_factory() as session:
            docs = [
                d
                for d in await IndexingRepository(session).documents(document_ids)
                if d.deleted_at is None
            ]
            principals = await compute_read_principals(session, docs)
        groups: dict[tuple[str, ...], list[str]] = defaultdict(list)
        for doc_id, tokens in principals.items():
            groups[tuple(tokens)].append(doc_id)
        targets = await self.registry.write_targets()
        for group, ids in groups.items():
            await self.set_acl(targets, sorted(ids), list(group))
        logger.info("index_acl_refreshed", extra={"documents": len(docs), "groups": len(groups)})
        return len(docs)

    async def mark_failed(self, document_id: str, version: int, error: str) -> None:
        async with self.session_factory() as session:
            doc = await session.get(Document, document_id)
            if not _is_current(doc, version):
                return
            assert doc is not None
            if doc.status in (DocumentStatus.PARSED.value, DocumentStatus.INDEXING.value):
                doc.status = DocumentStatus.FAILED.value
                doc.error_message = error[:MAX_ERROR_LENGTH]
                await session.commit()
