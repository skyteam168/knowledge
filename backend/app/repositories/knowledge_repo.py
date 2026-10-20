from collections.abc import Iterable, Sequence
from datetime import datetime

from sqlalchemy import ColumnElement, Select, delete, func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Chunk,
    Document,
    DocumentPageAsset,
    DocumentVersion,
    KnowledgeBase,
    PageAssetKind,
)


class KnowledgeBaseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, org_id: str, kb_id: str) -> KnowledgeBase | None:
        stmt = select(KnowledgeBase).where(
            KnowledgeBase.org_id == org_id,
            KnowledgeBase.id == kb_id,
            KnowledgeBase.deleted_at.is_(None),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_by_ids(self, org_id: str, ids: Iterable[str]) -> list[KnowledgeBase]:
        wanted = list(dict.fromkeys(ids))
        if not wanted:
            return []
        stmt = select(KnowledgeBase).where(
            KnowledgeBase.org_id == org_id,
            KnowledgeBase.id.in_(wanted),
            KnowledgeBase.deleted_at.is_(None),
        )
        return list((await self.session.execute(stmt)).scalars())

    async def get_by_name(self, org_id: str, name: str) -> KnowledgeBase | None:
        stmt = select(KnowledgeBase).where(
            KnowledgeBase.org_id == org_id, KnowledgeBase.name == name
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    @staticmethod
    def search_stmt(
        org_id: str, keyword: str | None, readable: ColumnElement[bool] | None = None
    ) -> Select[KnowledgeBase]:
        stmt = select(KnowledgeBase).where(
            KnowledgeBase.org_id == org_id,
            KnowledgeBase.deleted_at.is_(None),
            readable if readable is not None else true(),
        )
        if keyword:
            like = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(KnowledgeBase.name.ilike(like), KnowledgeBase.description.ilike(like))
            )
        return stmt.order_by(KnowledgeBase.created_at.desc(), KnowledgeBase.id)

    async def add(self, kb: KnowledgeBase) -> KnowledgeBase:
        self.session.add(kb)
        await self.session.flush()
        return kb

    async def document_counts(self, org_id: str, kb_ids: Iterable[str]) -> dict[str, int]:
        ids = list(kb_ids)
        if not ids:
            return {}
        stmt = (
            select(Document.kb_id, func.count())
            .where(
                Document.org_id == org_id,
                Document.kb_id.in_(ids),
                Document.deleted_at.is_(None),
            )
            .group_by(Document.kb_id)
        )
        return {kb_id: int(n) for kb_id, n in (await self.session.execute(stmt)).all()}


class DocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _active(self, org_id: str) -> Select[Document]:
        return select(Document).where(Document.org_id == org_id, Document.deleted_at.is_(None))

    async def get(self, org_id: str, document_id: str) -> Document | None:
        stmt = self._active(org_id).where(Document.id == document_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def find_by_sha256(self, org_id: str, kb_id: str, sha256: str) -> Document | None:
        stmt = self._active(org_id).where(Document.kb_id == kb_id, Document.sha256 == sha256)
        return (await self.session.execute(stmt.limit(1))).scalar_one_or_none()

    async def find_by_filename(self, org_id: str, kb_id: str, filename: str) -> Document | None:
        stmt = self._active(org_id).where(Document.kb_id == kb_id, Document.filename == filename)
        return (await self.session.execute(stmt.limit(1))).scalar_one_or_none()

    def search_stmt(
        self,
        org_id: str,
        kb_id: str,
        *,
        status: str | None = None,
        keyword: str | None = None,
        visible: ColumnElement[bool] | None = None,
        review_due: tuple[datetime | None, datetime | None] | None = None,
        owner_id: str | None = None,
    ) -> Select[Document]:
        """`review_due` = (from, until): due dates in [from, until]; either end may be open."""
        stmt = self._active(org_id).where(Document.kb_id == kb_id)
        if visible is not None:
            stmt = stmt.where(visible)
        if status:
            stmt = stmt.where(Document.status == status)
        if review_due is not None:
            start, until = review_due
            stmt = stmt.where(Document.review_due_at.is_not(None))
            if start is not None:
                stmt = stmt.where(Document.review_due_at >= start)
            if until is not None:
                stmt = stmt.where(Document.review_due_at <= until)
        if owner_id:
            stmt = stmt.where(
                or_(
                    Document.owner_id == owner_id,
                    (Document.owner_id.is_(None)) & (Document.created_by == owner_id),
                )
            )
        if keyword:
            like = f"%{keyword.strip()}%"
            stmt = stmt.where(or_(Document.title.ilike(like), Document.filename.ilike(like)))
        return stmt.order_by(Document.updated_at.desc(), Document.id)

    async def inheriting_review(self, org_id: str, kb_id: str) -> list[Document]:
        """Documents that follow the knowledge base's review interval."""
        stmt = self._active(org_id).where(
            Document.kb_id == kb_id, Document.review_interval_days.is_(None)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def count_active(self, org_id: str, kb_id: str) -> int:
        stmt = select(func.count()).where(
            Document.org_id == org_id, Document.kb_id == kb_id, Document.deleted_at.is_(None)
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def add(self, document: Document) -> Document:
        self.session.add(document)
        await self.session.flush()
        return document

    async def versions(self, document_id: str) -> list[DocumentVersion]:
        stmt = (
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.version.desc())
        )
        return list((await self.session.execute(stmt)).scalars())

    async def get_version(self, document_id: str, version: int) -> DocumentVersion | None:
        stmt = select(DocumentVersion).where(
            DocumentVersion.document_id == document_id, DocumentVersion.version == version
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def add_version(self, version: DocumentVersion) -> DocumentVersion:
        self.session.add(version)
        await self.session.flush()
        return version


class ChunkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_document(
        self, document_id: str, version: int, limit: int = 5000
    ) -> list[Chunk]:
        stmt = (
            select(Chunk)
            .where(Chunk.document_id == document_id, Chunk.document_version == version)
            .order_by(Chunk.seq)
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars())


class DocumentPageAssetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def replace_for_version(
        self, document_id: str, version: int, assets: list[DocumentPageAsset]
    ) -> None:
        await self.session.execute(
            delete(DocumentPageAsset).where(
                DocumentPageAsset.document_id == document_id,
                DocumentPageAsset.document_version == version,
            )
        )
        self.session.add_all(assets)

    async def get(
        self, document_id: str, version: int, kind: str, page_index: int
    ) -> DocumentPageAsset | None:
        stmt = select(DocumentPageAsset).where(
            DocumentPageAsset.document_id == document_id,
            DocumentPageAsset.document_version == version,
            DocumentPageAsset.kind == kind,
            DocumentPageAsset.page_index == page_index,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_for_version(self, document_id: str, version: int) -> list[DocumentPageAsset]:
        stmt = (
            select(DocumentPageAsset)
            .where(
                DocumentPageAsset.document_id == document_id,
                DocumentPageAsset.document_version == version,
            )
            .order_by(DocumentPageAsset.kind, DocumentPageAsset.page_index)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def find_for_citation(
        self,
        document_id: str,
        version: int,
        *,
        slide_number: int | None,
        page_start: int | None,
    ) -> DocumentPageAsset | None:
        if slide_number is not None:
            asset = await self.get(document_id, version, PageAssetKind.SLIDE.value, slide_number)
            if asset is not None:
                return asset
        if page_start is not None:
            return await self.get(document_id, version, PageAssetKind.PAGE.value, page_start)
        return None

    async def list_by_indices(
        self,
        document_id: str,
        version: int,
        kind: str,
        indices: Sequence[int],
    ) -> list[DocumentPageAsset]:
        if not indices:
            return []
        stmt = (
            select(DocumentPageAsset)
            .where(
                DocumentPageAsset.document_id == document_id,
                DocumentPageAsset.document_version == version,
                DocumentPageAsset.kind == kind,
                DocumentPageAsset.page_index.in_(list(indices)),
            )
            .order_by(DocumentPageAsset.page_index)
        )
        return list((await self.session.execute(stmt)).scalars().all())
