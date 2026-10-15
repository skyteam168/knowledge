"""Writes published knowledge objects into the same indexes as document chunks.

Each entry (standard question / variant) of the published version is one index record with
is_ko=True, document_id=ko_id and doc_version=published version, so the chunk machinery
(stale-version cleanup, ACL updates, delete by document) applies unchanged.
"""

import logging
import uuid
from collections import defaultdict
from collections.abc import Collection, Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import KnowledgeObject, KoEntry, KoStatus, KoVersion
from app.repositories.indexing_repo import IndexingRepository
from app.retrieval.records import ChunkRecord
from app.services.indexing.generations import IndexTarget
from app.services.indexing.indexer import (
    ALL_BACKENDS,
    Backend,
    DocumentIndexer,
    IndexOutcome,
    IndexResult,
)
from app.services.indexing.principals import compute_read_principals
from app.services.knowledge.access import RESOURCE_KO

logger = logging.getLogger(__name__)

KO_CHUNK_TYPE = "ko"
KO_DOC_TYPE = "ko"


_ENTRY_NAMESPACE = uuid.UUID("6f0b6a52-5c1e-4c43-9a4e-3f1f0c2b7d10")


def ko_entry_id(ko_id: str, version: int, seq: int) -> str:
    """Deterministic index id of an entry (re-publishing the same version is idempotent)."""
    return uuid.uuid5(_ENTRY_NAMESPACE, f"{ko_id}:{version}:{seq}").hex


def is_indexable(ko: KnowledgeObject | None) -> bool:
    return (
        ko is not None
        and ko.published_version is not None
        and ko.status != KoStatus.DEPRECATED.value
    )


def ko_entry_text(question: str, answer: str) -> str:
    return f"{question}\n{answer}"


def to_ko_record(
    ko: KnowledgeObject, snapshot: KoVersion, entry: KoEntry, principals: list[str]
) -> ChunkRecord:
    return ChunkRecord(
        chunk_id=entry.id,
        org_id=ko.org_id,
        kb_id=ko.kb_id,
        document_id=ko.id,
        doc_version=snapshot.version,
        parent_id=None,
        heading_path=[],
        chunk_type=KO_CHUNK_TYPE,
        tags=[snapshot.ko_type],
        created_at=entry.created_at,
        acl_read_principals=principals,
        is_ko=True,
        title=snapshot.title,
        content=ko_entry_text(entry.question, snapshot.answer),
        doc_type=KO_DOC_TYPE,
    )


@dataclass
class _Loaded:
    ko: KnowledgeObject
    version: int
    records: list[ChunkRecord]


class KnowledgeObjectIndexer:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], documents: DocumentIndexer
    ) -> None:
        self.session_factory = session_factory
        self.documents = documents

    async def _load(self, session: AsyncSession, ko_id: str) -> _Loaded | None:
        ko = await session.get(KnowledgeObject, ko_id)
        if not is_indexable(ko):
            return None
        assert ko is not None and ko.published_version is not None
        repo = IndexingRepository(session)
        snapshot = await repo.ko_version(ko.id, ko.published_version)
        if snapshot is None:
            return None
        entries = await repo.ko_entries(ko.id, ko.published_version)
        principals = (await compute_read_principals(session, [ko], RESOURCE_KO))[ko.id]
        records = [to_ko_record(ko, snapshot, e, principals) for e in entries]
        return _Loaded(ko, ko.published_version, records)

    # ---- ko.published ----

    async def index(
        self,
        ko_id: str,
        version: int | None = None,
        *,
        targets: Sequence[IndexTarget] | None = None,
        backends: Collection[Backend] = ALL_BACKENDS,
    ) -> IndexResult:
        """Index the published version of a KO; `version` skips superseded events."""
        async with self.session_factory() as session:
            loaded = await self._load(session, ko_id)
        if loaded is None or (version is not None and loaded.version != version):
            logger.info("ko_index_skipped", extra={"ko_id": ko_id, "version": version})
            return IndexResult(IndexOutcome.SKIPPED)

        targets = (
            list(targets) if targets is not None else await self.documents.registry.write_targets()
        )
        await self.documents.write_records(loaded.records, targets, ko_id, loaded.version, backends)

        async with self.session_factory() as session:
            fresh = await self._load(session, ko_id)
        if fresh is None or fresh.version != loaded.version:
            # Deprecated or republished meanwhile: the later event owns the index state.
            await self.documents.remove_ids(targets, [r.chunk_id for r in loaded.records], backends)
            return IndexResult(IndexOutcome.SKIPPED)
        principals = fresh.records[0].acl_read_principals if fresh.records else []
        if loaded.records and principals != loaded.records[0].acl_read_principals:
            await self.documents.set_acl(targets, [ko_id], principals, backends)
        logger.info(
            "ko_indexed",
            extra={"ko_id": ko_id, "version": loaded.version, "entries": len(loaded.records)},
        )
        return IndexResult(IndexOutcome.INDEXED, len(loaded.records))

    # ---- ko.deprecated ----

    async def delete(self, ko_id: str) -> bool:
        async with self.session_factory() as session:
            if is_indexable(await session.get(KnowledgeObject, ko_id)):
                logger.warning("ko_unindex_skipped_live", extra={"ko_id": ko_id})
                return False
        for target in await self.documents.registry.write_targets():
            await self.documents.backends.vector.delete_documents(target.qdrant_collection, [ko_id])
            await self.documents.backends.text.delete_documents(target.opensearch_index, [ko_id])
        logger.info("ko_unindexed", extra={"ko_id": ko_id})
        return True

    # ---- acl.changed ----

    async def refresh_acl(self, ko_ids: Sequence[str]) -> int:
        async with self.session_factory() as session:
            kos = [
                k
                for k in await IndexingRepository(session).knowledge_objects(ko_ids)
                if is_indexable(k)
            ]
            principals = await compute_read_principals(session, kos, RESOURCE_KO)
        groups: dict[tuple[str, ...], list[str]] = defaultdict(list)
        for ko_id, tokens in principals.items():
            groups[tuple(tokens)].append(ko_id)
        targets = await self.documents.registry.write_targets()
        for group, ids in groups.items():
            await self.documents.set_acl(targets, sorted(ids), list(group))
        return len(kos)
