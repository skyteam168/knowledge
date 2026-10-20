"""Personal favorites and recently viewed documents / knowledge bases.

Lists are filtered by the caller's current permissions: items they can no longer read are
hidden (not deleted), so access granted again brings them back.
"""

from collections.abc import Sequence
from datetime import datetime

from app.core.exceptions import ConflictError, NotFoundError
from app.models import Favorite
from app.models.base import utcnow
from app.repositories.collab_repo import FavoriteRepository, RecentViewRepository
from app.repositories.knowledge_repo import DocumentRepository, KnowledgeBaseRepository
from app.schemas.collab import ResourceType, SavedItemOut
from app.services.authz import AclPermission
from app.services.context import BaseService
from app.services.knowledge.access import KnowledgeAccess

MAX_FAVORITES = 500
RECENT_KEEP = 50


def _link(resource_type: str, resource_id: str, kb_id: str) -> str:
    if resource_type == "document":
        return f"/knowledge/{kb_id}/documents/{resource_id}"
    return f"/knowledge/{kb_id}"


class FavoriteService(BaseService):
    @property
    def access(self) -> KnowledgeAccess:
        return KnowledgeAccess(self.session)

    async def _require_readable(self, resource_type: ResourceType, resource_id: str) -> None:
        if resource_type == "document":
            doc = await DocumentRepository(self.session).get(self.org_id, resource_id)
            kb = (
                await KnowledgeBaseRepository(self.session).get(self.org_id, doc.kb_id)
                if doc
                else None
            )
            if doc is None or kb is None:
                raise NotFoundError("Document not found")
            await self.access.require_document(self.ctx.user, doc, kb, AclPermission.READ)
            return
        kb = await KnowledgeBaseRepository(self.session).get(self.org_id, resource_id)
        if kb is None:
            raise NotFoundError("Knowledge base not found")
        await self.access.require_kb(self.ctx.user, kb, AclPermission.READ)

    async def _readable_items(
        self, rows: Sequence[tuple[str, str, datetime]]
    ) -> list[SavedItemOut]:
        """(resource_type, resource_id, time) -> items the caller can read, in input order."""
        user = self.ctx.user
        docs = await self.access.readable_documents(
            user, [rid for rtype, rid, _ in rows if rtype == "document"]
        )
        kbs = await KnowledgeBaseRepository(self.session).list_by_ids(
            self.org_id, [rid for rtype, rid, _ in rows if rtype == "kb"]
        )
        kb_perms = await self.access.kb_permissions(user, kbs)
        readable_kbs = {kb.id: kb for kb in kbs if kb_perms.get(kb.id) is not None}
        items: list[SavedItemOut] = []
        for rtype, rid, at in rows:
            if rtype == "document" and rid in docs:
                doc, kb = docs[rid]
                items.append(
                    SavedItemOut(
                        resource_type="document",
                        resource_id=rid,
                        title=doc.title,
                        kb_id=kb.id,
                        kb_name=kb.name,
                        filename=doc.filename,
                        link=_link(rtype, rid, kb.id),
                        at=at,
                    )
                )
            elif rtype == "kb" and rid in readable_kbs:
                kb = readable_kbs[rid]
                items.append(
                    SavedItemOut(
                        resource_type="kb",
                        resource_id=rid,
                        title=kb.name,
                        kb_id=kb.id,
                        kb_name=kb.name,
                        link=_link(rtype, rid, kb.id),
                        at=at,
                    )
                )
        return items

    # ---- favorites ----

    async def favorites(self) -> list[SavedItemOut]:
        rows = await FavoriteRepository(self.session).list_for_user(
            self.org_id, self.ctx.user.id, MAX_FAVORITES
        )
        return await self._readable_items(
            [(r.resource_type, r.resource_id, r.created_at) for r in rows]
        )

    async def is_favorite(self, resource_type: ResourceType, resource_id: str) -> bool:
        repo = FavoriteRepository(self.session)
        return await repo.get(self.ctx.user.id, resource_type, resource_id) is not None

    async def add(self, resource_type: ResourceType, resource_id: str) -> None:
        await self._require_readable(resource_type, resource_id)
        repo = FavoriteRepository(self.session)
        if await repo.get(self.ctx.user.id, resource_type, resource_id) is not None:
            return
        if await repo.count_for_user(self.org_id, self.ctx.user.id) >= MAX_FAVORITES:
            raise ConflictError(
                "Too many favorites", code="FAVORITES_FULL", detail={"max": MAX_FAVORITES}
            )
        await repo.add(
            Favorite(
                org_id=self.org_id,
                user_id=self.ctx.user.id,
                resource_type=resource_type,
                resource_id=resource_id,
            )
        )

    async def remove(self, resource_type: ResourceType, resource_id: str) -> None:
        repo = FavoriteRepository(self.session)
        row = await repo.get(self.ctx.user.id, resource_type, resource_id)
        if row is not None:
            await repo.remove(row)

    # ---- recently viewed ----

    async def touch(self, resource_type: ResourceType, resource_id: str) -> None:
        await self._require_readable(resource_type, resource_id)
        repo = RecentViewRepository(self.session)
        await repo.touch(self.org_id, self.ctx.user.id, resource_type, resource_id, utcnow())
        await repo.prune(self.org_id, self.ctx.user.id, RECENT_KEEP)

    async def recent(self, limit: int) -> list[SavedItemOut]:
        rows = await RecentViewRepository(self.session).list_for_user(
            self.org_id, self.ctx.user.id, limit
        )
        return await self._readable_items(
            [(r.resource_type, r.resource_id, r.viewed_at) for r in rows]
        )
