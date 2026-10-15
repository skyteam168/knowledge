from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import (
    ColumnElement,
    Select,
    String,
    cast,
    delete,
    func,
    literal,
    or_,
    select,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ACTIVE_GAP_STATUSES,
    Document,
    GapCluster,
    GapStatus,
    KnowledgeBase,
    KnowledgeGap,
    KnowledgeObject,
    KoEntry,
    KoSourceRef,
    KoStatus,
    KoVersion,
    Notification,
    ReviewStatus,
    ReviewTask,
)


class GapRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, org_id: str, gap_id: str) -> KnowledgeGap | None:
        stmt = select(KnowledgeGap).where(KnowledgeGap.org_id == org_id, KnowledgeGap.id == gap_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def many(self, org_id: str, gap_ids: Sequence[str]) -> list[KnowledgeGap]:
        if not gap_ids:
            return []
        stmt = select(KnowledgeGap).where(
            KnowledgeGap.org_id == org_id, KnowledgeGap.id.in_(list(gap_ids))
        )
        return list((await self.session.execute(stmt)).scalars())

    def list_stmt(
        self,
        org_id: str,
        *,
        kb_scope: ColumnElement[bool],
        statuses: Sequence[str],
        gap_type: str | None,
        kb_id: str | None,
        cluster_id: str | None,
        assignee_id: str | None,
        keyword: str | None,
        sort: str,
    ) -> Select[KnowledgeGap]:
        stmt = select(KnowledgeGap).where(KnowledgeGap.org_id == org_id, kb_scope)
        if statuses:
            stmt = stmt.where(KnowledgeGap.status.in_(list(statuses)))
        if gap_type:
            stmt = stmt.where(KnowledgeGap.gap_type == gap_type)
        if kb_id:
            stmt = stmt.where(KnowledgeGap.kb_id == kb_id)
        if cluster_id:
            stmt = stmt.where(KnowledgeGap.cluster_id == cluster_id)
        if assignee_id:
            stmt = stmt.where(KnowledgeGap.assignee_id == assignee_id)
        if keyword:
            stmt = stmt.where(KnowledgeGap.query.ilike(f"%{keyword}%"))
        if sort == "recent":
            return stmt.order_by(KnowledgeGap.last_seen_at.desc(), KnowledgeGap.id)
        cluster_size = (
            select(GapCluster.occurrences)
            .where(GapCluster.id == KnowledgeGap.cluster_id)
            .scalar_subquery()
        )
        return stmt.order_by(
            func.coalesce(cluster_size, KnowledgeGap.occurrences).desc(),
            KnowledgeGap.occurrences.desc(),
            KnowledgeGap.last_seen_at.desc(),
            KnowledgeGap.id,
        )

    async def unclustered(self, limit: int, org_id: str | None = None) -> list[KnowledgeGap]:
        """Active gaps not yet clustered (of one org or all tenants), oldest first."""
        stmt = select(KnowledgeGap).where(
            KnowledgeGap.cluster_id.is_(None),
            KnowledgeGap.query_hash.is_(None),
            KnowledgeGap.status.in_(list(ACTIVE_GAP_STATUSES)),
        )
        if org_id is not None:
            stmt = stmt.where(KnowledgeGap.org_id == org_id)
        stmt = stmt.order_by(KnowledgeGap.created_at, KnowledgeGap.id).limit(limit)
        return list((await self.session.execute(stmt)).scalars())

    async def primary_in_cluster(
        self, cluster_id: str, query_hash: str, exclude_id: str
    ) -> KnowledgeGap | None:
        """The active, non-duplicate gap of a cluster with the same normalized question."""
        stmt = (
            select(KnowledgeGap)
            .where(
                KnowledgeGap.cluster_id == cluster_id,
                KnowledgeGap.query_hash == query_hash,
                KnowledgeGap.id != exclude_id,
                KnowledgeGap.status.in_(list(ACTIVE_GAP_STATUSES)),
            )
            .order_by(KnowledgeGap.created_at, KnowledgeGap.id)
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def cluster_members(self, org_id: str, cluster_id: str) -> list[KnowledgeGap]:
        stmt = (
            select(KnowledgeGap)
            .where(KnowledgeGap.org_id == org_id, KnowledgeGap.cluster_id == cluster_id)
            .order_by(KnowledgeGap.occurrences.desc(), KnowledgeGap.created_at)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def duplicates_of(self, org_id: str, gap_ids: Sequence[str]) -> list[KnowledgeGap]:
        if not gap_ids:
            return []
        stmt = select(KnowledgeGap).where(
            KnowledgeGap.org_id == org_id,
            KnowledgeGap.duplicate_of_id.in_(list(gap_ids)),
            KnowledgeGap.status == GapStatus.DUPLICATE.value,
        )
        return list((await self.session.execute(stmt)).scalars())

    async def status_counts(self, org_id: str, kb_scope: ColumnElement[bool]) -> dict[str, int]:
        stmt = (
            select(KnowledgeGap.status, func.count())
            .where(KnowledgeGap.org_id == org_id, kb_scope)
            .group_by(KnowledgeGap.status)
        )
        return {s: int(n) for s, n in (await self.session.execute(stmt)).all()}

    async def source_counts(self, org_id: str, kb_scope: ColumnElement[bool]) -> dict[str, int]:
        stmt = (
            select(KnowledgeGap.gap_type, func.sum(KnowledgeGap.occurrences))
            .where(
                KnowledgeGap.org_id == org_id,
                kb_scope,
                KnowledgeGap.status.in_(list(ACTIVE_GAP_STATUSES)),
            )
            .group_by(KnowledgeGap.gap_type)
        )
        return {t: int(n or 0) for t, n in (await self.session.execute(stmt)).all()}


class GapClusterRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, org_id: str, cluster_id: str) -> GapCluster | None:
        stmt = select(GapCluster).where(GapCluster.org_id == org_id, GapCluster.id == cluster_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def candidates(
        self, org_id: str, kb_id: str | None, model: str, dim: int, since: datetime
    ) -> list[GapCluster]:
        stmt = select(GapCluster).where(
            GapCluster.org_id == org_id,
            GapCluster.embedding_model == model,
            GapCluster.embedding_dim == dim,
            GapCluster.last_seen_at >= since,
            GapCluster.kb_id.is_(None) if kb_id is None else GapCluster.kb_id == kb_id,
        )
        return list((await self.session.execute(stmt)).scalars())

    def list_stmt(self, org_id: str, kb_id: str | None, open_only: bool) -> Select[GapCluster]:
        stmt = select(GapCluster).where(GapCluster.org_id == org_id)
        if kb_id:
            stmt = stmt.where(GapCluster.kb_id == kb_id)
        if open_only:
            stmt = stmt.where(GapCluster.open_count > 0)
        return stmt.order_by(
            GapCluster.occurrences.desc(), GapCluster.last_seen_at.desc(), GapCluster.id
        )

    async def stats(self, cluster_id: str) -> tuple[int, int, int, dict[str, int], datetime | None]:
        """(gap_count, occurrences, open_count, sources, last_seen_at) from the members."""
        stmt = select(
            KnowledgeGap.status,
            KnowledgeGap.gap_type,
            KnowledgeGap.occurrences,
            KnowledgeGap.last_seen_at,
        ).where(KnowledgeGap.cluster_id == cluster_id)
        gap_count = occurrences = open_count = 0
        sources: dict[str, int] = {}
        last: datetime | None = None
        for status, gap_type, occ, seen in (await self.session.execute(stmt)).all():
            if status == GapStatus.DUPLICATE.value:
                continue
            gap_count += 1
            occurrences += int(occ)
            if status in ACTIVE_GAP_STATUSES:
                open_count += 1
            sources[gap_type] = sources.get(gap_type, 0) + int(occ)
            if last is None or seen > last:
                last = seen
        return gap_count, occurrences, open_count, sources, last


class KnowledgeObjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, org_id: str, ko_id: str) -> KnowledgeObject | None:
        stmt = select(KnowledgeObject).where(
            KnowledgeObject.org_id == org_id, KnowledgeObject.id == ko_id
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    def list_stmt(
        self,
        org_id: str,
        *,
        kb_scope: ColumnElement[bool],
        kb_id: str | None,
        status: str | None,
        ko_type: str | None,
        owner_id: str | None,
        keyword: str | None,
    ) -> Select[KnowledgeObject]:
        stmt = select(KnowledgeObject).where(KnowledgeObject.org_id == org_id, kb_scope)
        if kb_id:
            stmt = stmt.where(KnowledgeObject.kb_id == kb_id)
        if status:
            stmt = stmt.where(KnowledgeObject.status == status)
        if ko_type:
            stmt = stmt.where(KnowledgeObject.ko_type == ko_type)
        if owner_id:
            stmt = stmt.where(KnowledgeObject.owner_id == owner_id)
        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where(
                or_(KnowledgeObject.title.ilike(like), KnowledgeObject.question.ilike(like))
            )
        return stmt.order_by(KnowledgeObject.updated_at.desc(), KnowledgeObject.id)

    async def objects_with_kbs(
        self, org_id: str, ko_ids: Sequence[str]
    ) -> list[tuple[KnowledgeObject, KnowledgeBase]]:
        if not ko_ids:
            return []
        stmt = (
            select(KnowledgeObject, KnowledgeBase)
            .join(KnowledgeBase, KnowledgeBase.id == KnowledgeObject.kb_id)
            .where(KnowledgeObject.org_id == org_id, KnowledgeObject.id.in_(list(ko_ids)))
        )
        return [(o, k) for o, k in (await self.session.execute(stmt)).all()]

    async def entries(self, org_id: str, entry_ids: Sequence[str]) -> list[KoEntry]:
        if not entry_ids:
            return []
        stmt = select(KoEntry).where(KoEntry.org_id == org_id, KoEntry.id.in_(list(entry_ids)))
        return list((await self.session.execute(stmt)).scalars())

    async def entries_of(self, ko_id: str, version: int) -> list[KoEntry]:
        stmt = (
            select(KoEntry)
            .where(KoEntry.ko_id == ko_id, KoEntry.ko_version == version)
            .order_by(KoEntry.seq)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def snapshots(self, keys: Sequence[tuple[str, int]]) -> dict[tuple[str, int], KoVersion]:
        if not keys:
            return {}
        ko_ids = sorted({k for k, _ in keys})
        stmt = select(KoVersion).where(KoVersion.ko_id.in_(ko_ids))
        wanted = set(keys)
        return {
            (v.ko_id, v.version): v
            for v in (await self.session.execute(stmt)).scalars()
            if (v.ko_id, v.version) in wanted
        }

    async def version(self, ko_id: str, version: int) -> KoVersion | None:
        stmt = select(KoVersion).where(KoVersion.ko_id == ko_id, KoVersion.version == version)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def versions(self, ko_id: str) -> list[KoVersion]:
        stmt = select(KoVersion).where(KoVersion.ko_id == ko_id).order_by(KoVersion.version.desc())
        return list((await self.session.execute(stmt)).scalars())

    async def mark_versions(self, ko_id: str, from_status: str, to_status: str) -> None:
        await self.session.execute(
            update(KoVersion)
            .where(KoVersion.ko_id == ko_id, KoVersion.status == from_status)
            .values(status=to_status)
        )

    async def replace_entries(self, ko: KnowledgeObject, entries: list[KoEntry]) -> None:
        await self.session.execute(delete(KoEntry).where(KoEntry.ko_id == ko.id))
        self.session.add_all(entries)

    async def replace_source_refs(self, ko: KnowledgeObject, refs: list[KoSourceRef]) -> None:
        await self.session.execute(delete(KoSourceRef).where(KoSourceRef.ko_id == ko.id))
        self.session.add_all(refs)

    async def clear_index_rows(self, ko_id: str) -> None:
        await self.session.execute(delete(KoEntry).where(KoEntry.ko_id == ko_id))
        await self.session.execute(delete(KoSourceRef).where(KoSourceRef.ko_id == ko_id))

    async def published_citing(
        self, org_id: str, document_ids: Sequence[str], exclude: Sequence[str] = ()
    ) -> list[tuple[str, str]]:
        """(document_id, ko_id) of published, non-deprecated KOs citing the documents."""
        if not document_ids:
            return []
        stmt = (
            select(KoSourceRef.document_id, KoSourceRef.ko_id)
            .join(KnowledgeObject, KnowledgeObject.id == KoSourceRef.ko_id)
            .where(
                KoSourceRef.org_id == org_id,
                KoSourceRef.document_id.in_(list(document_ids)),
                KnowledgeObject.published_version.is_not(None),
                KnowledgeObject.status != KoStatus.DEPRECATED.value,
            )
            .order_by(KnowledgeObject.published_at.desc(), KoSourceRef.ko_id)
        )
        if exclude:
            stmt = stmt.where(KoSourceRef.ko_id.not_in(list(exclude)))
        return [(d, k) for d, k in (await self.session.execute(stmt)).all()]

    async def expired(self, now: datetime, limit: int) -> list[KnowledgeObject]:
        """Live KOs past effective_to (all tenants)."""
        stmt = (
            select(KnowledgeObject)
            .where(
                KnowledgeObject.published_version.is_not(None),
                KnowledgeObject.status != KoStatus.DEPRECATED.value,
                KnowledgeObject.effective_to.is_not(None),
                KnowledgeObject.effective_to <= now,
            )
            .order_by(KnowledgeObject.effective_to)
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def expiring(self, now: datetime, until: datetime, limit: int) -> list[KnowledgeObject]:
        """Live KOs expiring within (now, until] whose owners were not reminded yet."""
        stmt = (
            select(KnowledgeObject)
            .where(
                KnowledgeObject.published_version.is_not(None),
                KnowledgeObject.status != KoStatus.DEPRECATED.value,
                KnowledgeObject.effective_to > now,
                KnowledgeObject.effective_to <= until,
                or_(
                    KnowledgeObject.expiry_notified_at.is_(None),
                    KnowledgeObject.expiry_notified_at < KnowledgeObject.published_at,
                ),
            )
            .order_by(KnowledgeObject.effective_to)
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def expiring_documents(
        self, now: datetime, until: datetime, limit: int
    ) -> list[Document]:
        stmt = (
            select(Document)
            .where(
                Document.deleted_at.is_(None),
                Document.created_by.is_not(None),
                Document.effective_to.is_not(None),
                Document.effective_to > now,
                Document.effective_to <= until,
                ~select(Notification.id)
                .where(
                    Notification.resource_type == "document",
                    Notification.resource_id == Document.id,
                    Notification.dedupe_key
                    == literal("doc-expiry:")
                    + Document.id
                    + literal(":")
                    + cast(Document.version, String),
                )
                .exists(),
            )
            .order_by(Document.effective_to)
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars())


class ReviewTaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def pending_for(self, ko_id: str) -> ReviewTask | None:
        stmt = (
            select(ReviewTask)
            .where(ReviewTask.ko_id == ko_id, ReviewTask.status == ReviewStatus.PENDING.value)
            .order_by(ReviewTask.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def for_ko(self, ko_id: str) -> list[ReviewTask]:
        stmt = (
            select(ReviewTask)
            .where(ReviewTask.ko_id == ko_id)
            .order_by(ReviewTask.created_at.desc())
        )
        return list((await self.session.execute(stmt)).scalars())

    def list_stmt(
        self, org_id: str, kb_scope: ColumnElement[bool], status: str | None
    ) -> Select[ReviewTask]:
        stmt = (
            select(ReviewTask)
            .join(KnowledgeObject, KnowledgeObject.id == ReviewTask.ko_id)
            .where(ReviewTask.org_id == org_id, kb_scope)
        )
        if status:
            stmt = stmt.where(ReviewTask.status == status)
        return stmt.order_by(ReviewTask.created_at.desc(), ReviewTask.id)


class NotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def exists(self, user_id: str, dedupe_key: str) -> bool:
        stmt = select(Notification.id).where(
            Notification.user_id == user_id, Notification.dedupe_key == dedupe_key
        )
        return (await self.session.execute(stmt)).first() is not None

    def list_stmt(self, org_id: str, user_id: str, unread_only: bool) -> Select[Notification]:
        stmt = select(Notification).where(
            Notification.org_id == org_id, Notification.user_id == user_id
        )
        if unread_only:
            stmt = stmt.where(Notification.read_at.is_(None))
        return stmt.order_by(Notification.created_at.desc(), Notification.id)

    async def unread_count(self, org_id: str, user_id: str) -> int:
        stmt = select(func.count()).where(
            Notification.org_id == org_id,
            Notification.user_id == user_id,
            Notification.read_at.is_(None),
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def mark_read(
        self, org_id: str, user_id: str, ids: Sequence[str] | None, now: datetime
    ) -> int:
        stmt = (
            update(Notification)
            .where(
                Notification.org_id == org_id,
                Notification.user_id == user_id,
                Notification.read_at.is_(None),
            )
            .values(read_at=now)
        )
        if ids is not None:
            stmt = stmt.where(Notification.id.in_(list(ids)))
        result = await self.session.execute(stmt)
        return int(getattr(result, "rowcount", 0) or 0)
