from collections.abc import Sequence

from sqlalchemy import ColumnElement, Select, String, cast, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chunk, Document, KnowledgeBase, RetrievalProfile, RetrievalTrace


class SearchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def chunks_with_documents(
        self, org_id: str, chunk_ids: Sequence[str]
    ) -> list[tuple[Chunk, Document, KnowledgeBase]]:
        if not chunk_ids:
            return []
        stmt = (
            select(Chunk, Document, KnowledgeBase)
            .join(Document, Document.id == Chunk.document_id)
            .join(KnowledgeBase, KnowledgeBase.id == Document.kb_id)
            .where(Chunk.org_id == org_id, Chunk.id.in_(list(chunk_ids)))
        )
        return [(c, d, k) for c, d, k in (await self.session.execute(stmt)).all()]

    async def readable_kbs(
        self,
        org_id: str,
        readable: ColumnElement[bool],
        *,
        ids: Sequence[str] = (),
        names: Sequence[str] = (),
    ) -> list[KnowledgeBase]:
        if not ids and not names:
            return []
        stmt = select(KnowledgeBase).where(
            KnowledgeBase.org_id == org_id, KnowledgeBase.deleted_at.is_(None), readable
        )
        match = []
        if ids:
            match.append(KnowledgeBase.id.in_(list(ids)))
        if names:
            match.append(KnowledgeBase.name.in_(list(names)))
        stmt = stmt.where(or_(*match))
        return list((await self.session.execute(stmt)).scalars())

    async def visible_document_facets(
        self, org_id: str, visible: ColumnElement[bool], limit: int
    ) -> list[tuple[list[str], str, str]]:
        """(tags, filename, mime_type) of up to `limit` recent visible documents."""
        stmt = (
            select(Document.tags, Document.filename, Document.mime_type)
            .join(KnowledgeBase, KnowledgeBase.id == Document.kb_id)
            .where(
                Document.org_id == org_id,
                Document.deleted_at.is_(None),
                KnowledgeBase.deleted_at.is_(None),
                visible,
            )
            .order_by(Document.updated_at.desc())
            .limit(limit)
        )
        return [(list(t or []), f, m) for t, f, m in (await self.session.execute(stmt)).all()]


class RetrievalProfileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self, org_id: str) -> list[RetrievalProfile]:
        stmt = (
            select(RetrievalProfile)
            .where(RetrievalProfile.org_id == org_id)
            .order_by(RetrievalProfile.is_active.desc(), RetrievalProfile.name)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def get(self, org_id: str, profile_id: str) -> RetrievalProfile | None:
        stmt = select(RetrievalProfile).where(
            RetrievalProfile.org_id == org_id, RetrievalProfile.id == profile_id
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_name(self, org_id: str, name: str) -> RetrievalProfile | None:
        stmt = select(RetrievalProfile).where(
            RetrievalProfile.org_id == org_id, RetrievalProfile.name == name
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def active(self, org_id: str) -> RetrievalProfile | None:
        stmt = select(RetrievalProfile).where(
            RetrievalProfile.org_id == org_id, RetrievalProfile.is_active.is_(True)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def deactivate_all(self, org_id: str) -> None:
        await self.session.execute(
            update(RetrievalProfile)
            .where(RetrievalProfile.org_id == org_id, RetrievalProfile.is_active.is_(True))
            .values(is_active=False)
        )
        await self.session.flush()


class RetrievalTraceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, trace: RetrievalTrace) -> RetrievalTrace:
        self.session.add(trace)
        await self.session.flush()
        return trace

    async def get(self, org_id: str, trace_id: str) -> RetrievalTrace | None:
        stmt = select(RetrievalTrace).where(
            RetrievalTrace.org_id == org_id, RetrievalTrace.id == trace_id
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    @staticmethod
    def search_stmt(
        org_id: str,
        *,
        user_id: str | None = None,
        keyword: str | None = None,
        degraded_only: bool = False,
    ) -> Select[RetrievalTrace]:
        stmt = select(RetrievalTrace).where(RetrievalTrace.org_id == org_id)
        if user_id:
            stmt = stmt.where(RetrievalTrace.user_id == user_id)
        if keyword:
            stmt = stmt.where(RetrievalTrace.query.ilike(f"%{keyword.strip()}%"))
        if degraded_only:
            stmt = stmt.where(cast(RetrievalTrace.degraded, String) != "[]")
        return stmt.order_by(RetrievalTrace.created_at.desc(), RetrievalTrace.id)
