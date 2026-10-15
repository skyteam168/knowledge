from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import ColumnElement, Select, and_, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import (
    Chunk,
    Document,
    GenerationStatus,
    IndexGeneration,
    KnowledgeBase,
    KnowledgeObject,
    KoEntry,
    KoStatus,
    KoVersion,
    OutboxEvent,
    OutboxStatus,
    ResourceAcl,
)

# Children are the retrieval units; parents are expanded from PG at answer time.
INDEXED_CHUNK_LEVEL = 2


class OutboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def claim(self, now: datetime, limit: int, lease_until: datetime) -> list[OutboxEvent]:
        """Claim due events, at most one in flight per aggregate, in creation order.

        FOR UPDATE SKIP LOCKED lets several dispatchers run without double-claiming.
        """
        earlier = aliased(OutboxEvent)
        blocked_by_earlier = exists().where(
            earlier.aggregate_type == OutboxEvent.aggregate_type,
            earlier.aggregate_id == OutboxEvent.aggregate_id,
            earlier.status.in_([OutboxStatus.PENDING.value, OutboxStatus.PROCESSING.value]),
            or_(
                earlier.created_at < OutboxEvent.created_at,
                and_(earlier.created_at == OutboxEvent.created_at, earlier.id < OutboxEvent.id),
            ),
        )
        due = or_(
            and_(
                OutboxEvent.status == OutboxStatus.PENDING.value,
                or_(OutboxEvent.next_attempt_at.is_(None), OutboxEvent.next_attempt_at <= now),
            ),
            and_(
                OutboxEvent.status == OutboxStatus.PROCESSING.value,
                OutboxEvent.locked_until < now,
            ),
        )
        stmt = (
            select(OutboxEvent)
            .where(due, ~blocked_by_earlier)
            .order_by(OutboxEvent.created_at, OutboxEvent.id)
            .limit(limit)
            .with_for_update(skip_locked=True, of=OutboxEvent)
        )
        events = list((await self.session.execute(stmt)).scalars())
        for event in events:
            event.status = OutboxStatus.PROCESSING.value
            event.locked_until = lease_until
        await self.session.flush()
        return events

    async def get(self, event_id: str) -> OutboxEvent | None:
        return await self.session.get(OutboxEvent, event_id)

    def search_stmt(
        self, org_id: str, status: str | None, event_type: str | None
    ) -> Select[OutboxEvent]:
        stmt = select(OutboxEvent).where(OutboxEvent.org_id == org_id)
        if status:
            stmt = stmt.where(OutboxEvent.status == status)
        if event_type:
            stmt = stmt.where(OutboxEvent.event_type == event_type)
        return stmt.order_by(OutboxEvent.created_at.desc(), OutboxEvent.id)

    async def status_counts(self, org_id: str) -> dict[str, int]:
        stmt = (
            select(OutboxEvent.status, func.count())
            .where(OutboxEvent.org_id == org_id)
            .group_by(OutboxEvent.status)
        )
        return {status: int(n) for status, n in (await self.session.execute(stmt)).all()}

    async def requeue_dead(self, org_id: str, event_ids: Sequence[str] | None = None) -> int:
        stmt = (
            update(OutboxEvent)
            .where(OutboxEvent.org_id == org_id, OutboxEvent.status == OutboxStatus.DEAD.value)
            .values(
                status=OutboxStatus.PENDING.value,
                retry_count=0,
                next_attempt_at=None,
                locked_until=None,
            )
        )
        if event_ids is not None:
            stmt = stmt.where(OutboxEvent.id.in_(list(event_ids)))
        result = await self.session.execute(stmt)
        return int(getattr(result, "rowcount", 0) or 0)


class IndexGenerationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def all(self) -> list[IndexGeneration]:
        stmt = select(IndexGeneration).order_by(IndexGeneration.version.desc())
        return list((await self.session.execute(stmt)).scalars())

    async def by_status(self, *statuses: GenerationStatus) -> list[IndexGeneration]:
        stmt = (
            select(IndexGeneration)
            .where(IndexGeneration.status.in_([s.value for s in statuses]))
            .order_by(IndexGeneration.version)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def get_version(self, version: int) -> IndexGeneration | None:
        stmt = select(IndexGeneration).where(IndexGeneration.version == version)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def max_version(self) -> int:
        stmt = select(func.max(IndexGeneration.version))
        return int((await self.session.execute(stmt)).scalar_one() or 0)


class IndexingRepository:
    """PG reads used to build index records (PG is the source of truth)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def documents(self, document_ids: Sequence[str]) -> list[Document]:
        if not document_ids:
            return []
        stmt = select(Document).where(Document.id.in_(list(document_ids)))
        return list((await self.session.execute(stmt)).scalars())

    async def knowledge_bases(self, kb_ids: Sequence[str]) -> list[KnowledgeBase]:
        if not kb_ids:
            return []
        stmt = select(KnowledgeBase).where(KnowledgeBase.id.in_(list(kb_ids)))
        return list((await self.session.execute(stmt)).scalars())

    async def acl_rows(self, resource_type: str, resource_ids: Sequence[str]) -> list[ResourceAcl]:
        if not resource_ids:
            return []
        stmt = select(ResourceAcl).where(
            ResourceAcl.resource_type == resource_type,
            ResourceAcl.resource_id.in_(list(resource_ids)),
        )
        return list((await self.session.execute(stmt)).scalars())

    async def active_document_ids(self, org_id: str, kb_id: str) -> list[str]:
        stmt = select(Document.id).where(
            Document.org_id == org_id, Document.kb_id == kb_id, Document.deleted_at.is_(None)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def active_documents(self, org_id: str, kb_id: str) -> list[Document]:
        stmt = select(Document).where(
            Document.org_id == org_id, Document.kb_id == kb_id, Document.deleted_at.is_(None)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def index_chunks(self, document_id: str, version: int) -> list[Chunk]:
        stmt = (
            select(Chunk)
            .where(
                Chunk.document_id == document_id,
                Chunk.document_version == version,
                Chunk.level == INDEXED_CHUNK_LEVEL,
            )
            .order_by(Chunk.seq)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def index_chunk_ids(self, document_ids: Sequence[str]) -> list[tuple[str, str]]:
        """(chunk_id, document_id) of the current version of each given document."""
        if not document_ids:
            return []
        stmt = (
            select(Chunk.id, Chunk.document_id)
            .join(Document, Document.id == Chunk.document_id)
            .where(
                Chunk.document_id.in_(list(document_ids)),
                Chunk.document_version == Document.version,
                Chunk.level == INDEXED_CHUNK_LEVEL,
            )
        )
        return [(cid, did) for cid, did in (await self.session.execute(stmt)).all()]

    async def document_ids_after(
        self, statuses: Sequence[str], after_id: str | None, limit: int
    ) -> list[str]:
        """Keyset pagination over active documents in `statuses` (all tenants)."""
        stmt = select(Document.id).where(
            Document.deleted_at.is_(None), Document.status.in_(list(statuses))
        )
        if after_id is not None:
            stmt = stmt.where(Document.id > after_id)
        stmt = stmt.order_by(Document.id).limit(limit)
        return list((await self.session.execute(stmt)).scalars())

    # ---- knowledge objects ----

    @staticmethod
    def _indexable_ko() -> list[ColumnElement[bool]]:
        return [
            KnowledgeObject.published_version.is_not(None),
            KnowledgeObject.status != KoStatus.DEPRECATED.value,
        ]

    async def knowledge_objects(self, ko_ids: Sequence[str]) -> list[KnowledgeObject]:
        if not ko_ids:
            return []
        stmt = select(KnowledgeObject).where(KnowledgeObject.id.in_(list(ko_ids)))
        return list((await self.session.execute(stmt)).scalars())

    async def ko_version(self, ko_id: str, version: int) -> KoVersion | None:
        stmt = select(KoVersion).where(KoVersion.ko_id == ko_id, KoVersion.version == version)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def ko_entries(self, ko_id: str, version: int) -> list[KoEntry]:
        stmt = (
            select(KoEntry)
            .where(KoEntry.ko_id == ko_id, KoEntry.ko_version == version)
            .order_by(KoEntry.seq)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def indexable_ko_ids(self, org_id: str, kb_id: str) -> list[str]:
        stmt = select(KnowledgeObject.id).where(
            KnowledgeObject.org_id == org_id,
            KnowledgeObject.kb_id == kb_id,
            *self._indexable_ko(),
        )
        return list((await self.session.execute(stmt)).scalars())

    async def indexable_ko_ids_after(self, after_id: str | None, limit: int) -> list[str]:
        """Keyset pagination over published, non-deprecated KOs (all tenants)."""
        stmt = select(KnowledgeObject.id).where(*self._indexable_ko())
        if after_id is not None:
            stmt = stmt.where(KnowledgeObject.id > after_id)
        stmt = stmt.order_by(KnowledgeObject.id).limit(limit)
        return list((await self.session.execute(stmt)).scalars())

    async def indexable_ko_entry_ids(self, ko_ids: Sequence[str]) -> list[tuple[str, str, int]]:
        """(entry_id, ko_id, version) of the published version of the given indexable KOs."""
        if not ko_ids:
            return []
        stmt = (
            select(KoEntry.id, KoEntry.ko_id, KoEntry.ko_version)
            .join(KnowledgeObject, KnowledgeObject.id == KoEntry.ko_id)
            .where(
                KoEntry.ko_id.in_(list(ko_ids)),
                KoEntry.ko_version == KnowledgeObject.published_version,
                *self._indexable_ko(),
            )
        )
        return [(eid, kid, int(v)) for eid, kid, v in (await self.session.execute(stmt)).all()]

    async def count_indexable_ko_entries(self) -> int:
        stmt = (
            select(func.count())
            .select_from(KoEntry)
            .join(KnowledgeObject, KnowledgeObject.id == KoEntry.ko_id)
            .where(KoEntry.ko_version == KnowledgeObject.published_version, *self._indexable_ko())
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def count_index_chunks(self, statuses: Sequence[str]) -> int:
        stmt = (
            select(func.count())
            .select_from(Chunk)
            .join(Document, Document.id == Chunk.document_id)
            .where(
                Document.deleted_at.is_(None),
                Document.status.in_(list(statuses)),
                Chunk.document_version == Document.version,
                Chunk.level == INDEXED_CHUNK_LEVEL,
            )
        )
        return int((await self.session.execute(stmt)).scalar_one())
