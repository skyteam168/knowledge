"""Resource-level access for knowledge bases and documents (on top of RBAC).

- Knowledge base: visibility=org grants `read` to every org member; resource_acl entries
  (user / group / role / dept incl. descendants) grant read / edit / manage.
- Document: acl_inherit=True -> the knowledge base permission applies (default);
  otherwise the document's own entries apply, while KB managers always keep `manage`.
- Superusers (`*`) can do everything.
"""

from collections.abc import Iterable, Sequence
from typing import Protocol

from sqlalchemy import ColumnElement, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.models import Document, KbVisibility, KnowledgeBase, ResourceAcl
from app.repositories.acl_repo import ResourceAclRepository
from app.services.authz import AclPermission, AclService, CurrentUser, ResourceRef

RESOURCE_KB = "kb"
RESOURCE_DOCUMENT = "document"
# Knowledge objects follow the document model: inherit the KB ACL or carry their own.
RESOURCE_KO = "ko"


class KbScopedResource(Protocol):
    """A resource inside a knowledge base that inherits its ACL or has its own entries."""

    @property
    def id(self) -> str: ...

    @property
    def acl_inherit(self) -> bool: ...


def _best(perms: Iterable[AclPermission | None]) -> AclPermission | None:
    best: AclPermission | None = None
    for perm in perms:
        if perm is not None and (best is None or perm.level > best.level):
            best = perm
    return best


def _satisfies(perm: AclPermission | None, required: AclPermission) -> bool:
    return perm is not None and perm.level >= required.level


class KnowledgeAccess:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.acl = AclService(session)
        self.repo = ResourceAclRepository(session)

    async def entries(self, org_id: str, resource_type: str, resource_id: str) -> list[ResourceAcl]:
        rows = await self.repo.list_for_resource(org_id, resource_type, resource_id)
        order = {"manage": 0, "edit": 1, "read": 2}
        return sorted(rows, key=lambda r: (order.get(r.permission, 9), r.principal_type))

    async def replace_entries(
        self,
        org_id: str,
        resource_type: str,
        resource_id: str,
        entries: Iterable[tuple[str, str, str]],
        created_by: str | None,
    ) -> None:
        await self.repo.delete_for_resource(org_id, resource_type, resource_id)
        for ptype, pid, perm in entries:
            self.session.add(
                ResourceAcl(
                    org_id=org_id,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    principal_type=ptype,
                    principal_id=pid,
                    permission=perm,
                    created_by=created_by,
                )
            )
        await self.session.flush()

    # ---- knowledge bases ----

    async def kb_permission(self, user: CurrentUser, kb: KnowledgeBase) -> AclPermission | None:
        if user.is_superuser:
            return AclPermission.MANAGE
        granted = await self.acl.effective_permission(
            user.principals, ResourceRef(RESOURCE_KB, kb.id)
        )
        base = AclPermission.READ if kb.visibility == KbVisibility.ORG.value else None
        return _best([granted, base])

    async def kb_permissions(
        self, user: CurrentUser, kbs: list[KnowledgeBase]
    ) -> dict[str, AclPermission | None]:
        if user.is_superuser:
            return {kb.id: AclPermission.MANAGE for kb in kbs}
        rows = await self.repo.list_matching_many(
            user.org_id, RESOURCE_KB, [kb.id for kb in kbs], user.principals.pairs()
        )
        result: dict[str, AclPermission | None] = {
            kb.id: AclPermission.READ if kb.visibility == KbVisibility.ORG.value else None
            for kb in kbs
        }
        for row in rows:
            result[row.resource_id] = _best(
                [result.get(row.resource_id), AclPermission(row.permission)]
            )
        return result

    def readable_kb_clause(self, user: CurrentUser) -> ColumnElement[bool]:
        if user.is_superuser:
            return true()
        granted = self.repo.granted_ids_stmt(user.org_id, RESOURCE_KB, user.principals.pairs())
        return or_(
            KnowledgeBase.visibility == KbVisibility.ORG.value, KnowledgeBase.id.in_(granted)
        )

    async def require_kb(
        self, user: CurrentUser, kb: KnowledgeBase, required: AclPermission
    ) -> AclPermission:
        """404 when the user cannot even read (existence is not disclosed), 403 otherwise."""
        perm = await self.kb_permission(user, kb)
        if perm is None:
            raise NotFoundError("Knowledge base not found")
        if not _satisfies(perm, required):
            raise PermissionDeniedError(detail={"required_acl": required.value})
        return perm

    # ---- documents ----

    async def document_permission(
        self,
        user: CurrentUser,
        document: Document,
        kb: KnowledgeBase,
        kb_perm: AclPermission | None = None,
    ) -> AclPermission | None:
        kb_perm = kb_perm if kb_perm is not None else await self.kb_permission(user, kb)
        if document.acl_inherit or kb_perm == AclPermission.MANAGE:
            return kb_perm
        return await self.acl.effective_permission(
            user.principals, ResourceRef(RESOURCE_DOCUMENT, document.id)
        )

    async def document_permissions(
        self,
        user: CurrentUser,
        documents: Sequence[Document],
        kb_perm: AclPermission | None,
    ) -> dict[str, AclPermission | None]:
        return await self.resource_permissions(user, documents, kb_perm, RESOURCE_DOCUMENT)

    async def resource_permissions(
        self,
        user: CurrentUser,
        items: Sequence[KbScopedResource],
        kb_perm: AclPermission | None,
        resource_type: str,
    ) -> dict[str, AclPermission | None]:
        """Permissions on resources of one knowledge base, given the KB permission."""
        result: dict[str, AclPermission | None] = {}
        overriding = []
        for item in items:
            if item.acl_inherit or kb_perm == AclPermission.MANAGE:
                result[item.id] = kb_perm
            else:
                result[item.id] = None
                overriding.append(item.id)
        rows = await self.repo.list_matching_many(
            user.org_id, resource_type, overriding, user.principals.pairs()
        )
        for row in rows:
            result[row.resource_id] = _best(
                [result[row.resource_id], AclPermission(row.permission)]
            )
        return result

    async def readable_documents(
        self, user: CurrentUser, document_ids: Iterable[str]
    ) -> dict[str, tuple[Document, KnowledgeBase]]:
        """Live documents (of live knowledge bases) among `document_ids` the user can read."""
        ids = list(dict.fromkeys(document_ids))
        if not ids:
            return {}
        stmt = (
            select(Document, KnowledgeBase)
            .join(KnowledgeBase, KnowledgeBase.id == Document.kb_id)
            .where(
                Document.org_id == user.org_id,
                Document.id.in_(ids),
                Document.deleted_at.is_(None),
                KnowledgeBase.deleted_at.is_(None),
            )
        )
        rows = [(d, k) for d, k in (await self.session.execute(stmt)).all()]
        kbs = {kb.id: kb for _, kb in rows}
        kb_perms = await self.kb_permissions(user, list(kbs.values()))
        result: dict[str, tuple[Document, KnowledgeBase]] = {}
        for kb_id, kb in kbs.items():
            docs = [d for d, k in rows if k.id == kb_id]
            perms = await self.document_permissions(user, docs, kb_perms.get(kb_id))
            result.update({d.id: (d, kb) for d in docs if perms.get(d.id) is not None})
        return result

    def visible_document_clause(
        self, user: CurrentUser, kb_perm: AclPermission | None
    ) -> ColumnElement[bool]:
        """Documents of one knowledge base the user can read, given their KB permission."""
        if kb_perm == AclPermission.MANAGE:
            return true()
        granted = self.repo.granted_ids_stmt(
            user.org_id, RESOURCE_DOCUMENT, user.principals.pairs()
        )
        overridden = Document.id.in_(granted)
        if kb_perm is None:
            return overridden
        return or_(Document.acl_inherit.is_(True), overridden)

    async def require_document(
        self,
        user: CurrentUser,
        document: Document,
        kb: KnowledgeBase,
        required: AclPermission,
    ) -> AclPermission:
        perm = await self.document_permission(user, document, kb)
        if perm is None:
            raise NotFoundError("Document not found")
        if not _satisfies(perm, required):
            raise PermissionDeniedError(detail={"required_acl": required.value})
        return perm
