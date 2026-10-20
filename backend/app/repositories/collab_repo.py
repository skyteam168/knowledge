from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DocumentComment, Favorite, RecentView


class FavoriteRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, user_id: str, resource_type: str, resource_id: str) -> Favorite | None:
        stmt = select(Favorite).where(
            Favorite.user_id == user_id,
            Favorite.resource_type == resource_type,
            Favorite.resource_id == resource_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_for_user(self, org_id: str, user_id: str, limit: int) -> list[Favorite]:
        stmt = (
            select(Favorite)
            .where(Favorite.org_id == org_id, Favorite.user_id == user_id)
            .order_by(Favorite.created_at.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def count_for_user(self, org_id: str, user_id: str) -> int:
        stmt = select(func.count()).where(Favorite.org_id == org_id, Favorite.user_id == user_id)
        return int((await self.session.execute(stmt)).scalar_one())

    async def add(self, favorite: Favorite) -> None:
        self.session.add(favorite)
        await self.session.flush()

    async def remove(self, favorite: Favorite) -> None:
        await self.session.delete(favorite)
        await self.session.flush()


class RecentViewRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def touch(
        self, org_id: str, user_id: str, resource_type: str, resource_id: str, now: datetime
    ) -> None:
        stmt = select(RecentView).where(
            RecentView.user_id == user_id,
            RecentView.resource_type == resource_type,
            RecentView.resource_id == resource_id,
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        if row is None:
            self.session.add(
                RecentView(
                    org_id=org_id,
                    user_id=user_id,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    viewed_at=now,
                )
            )
        else:
            row.viewed_at = now
        await self.session.flush()

    async def list_for_user(self, org_id: str, user_id: str, limit: int) -> list[RecentView]:
        stmt = (
            select(RecentView)
            .where(RecentView.org_id == org_id, RecentView.user_id == user_id)
            .order_by(RecentView.viewed_at.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def prune(self, org_id: str, user_id: str, keep: int) -> None:
        """Drop all but the `keep` most recent views of a user."""
        newest = (
            select(RecentView.id)
            .where(RecentView.org_id == org_id, RecentView.user_id == user_id)
            .order_by(RecentView.viewed_at.desc())
            .limit(keep)
        )
        await self.session.execute(
            delete(RecentView).where(
                RecentView.org_id == org_id,
                RecentView.user_id == user_id,
                RecentView.id.not_in(newest.scalar_subquery()),
            )
        )


class CommentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, org_id: str, comment_id: str) -> DocumentComment | None:
        stmt = select(DocumentComment).where(
            DocumentComment.org_id == org_id, DocumentComment.id == comment_id
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_for_document(self, document_id: str) -> list[DocumentComment]:
        stmt = (
            select(DocumentComment)
            .where(DocumentComment.document_id == document_id)
            .order_by(DocumentComment.created_at, DocumentComment.id)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def open_counts(self, document_ids: list[str]) -> dict[str, int]:
        if not document_ids:
            return {}
        stmt = (
            select(DocumentComment.document_id, func.count())
            .where(
                DocumentComment.document_id.in_(document_ids),
                DocumentComment.parent_id.is_(None),
                DocumentComment.deleted_at.is_(None),
                DocumentComment.resolved_at.is_(None),
            )
            .group_by(DocumentComment.document_id)
        )
        return {doc_id: int(n) for doc_id, n in (await self.session.execute(stmt)).all()}

    async def add(self, comment: DocumentComment) -> None:
        self.session.add(comment)
        await self.session.flush()
