"""S5: row-level ACL for structured / industrial objects (reuse resource_acl).

Visibility (aligned with document ACL under org-visible KB):
- No ACL rows → readable by anyone in the org (default open within tenant).
- Any ALLOW row → restricted; caller needs a matching allow.
- DENY always wins over allow / org-default.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.models import ResourceAcl
from app.repositories.acl_repo import EFFECT_ALLOW, EFFECT_DENY, ResourceAclRepository
from app.services.authz import (
    AclPermission,
    AclService,
    CurrentUser,
    ResourceRef,
)

RESOURCE_STRUCTURED = "structured"
RESOURCE_STRUCTURED_FIELD = "structured_field"
RESOURCE_OBJECT_RELATION = "object_relation"


def structured_ref(object_id: str) -> ResourceRef:
    return ResourceRef(RESOURCE_STRUCTURED, object_id)


def structured_field_ref(object_id: str, field: str) -> ResourceRef:
    return ResourceRef(RESOURCE_STRUCTURED_FIELD, f"{object_id}:{field}")


def object_relation_ref(relation_id: str) -> ResourceRef:
    return ResourceRef(RESOURCE_OBJECT_RELATION, relation_id)


class StructuredAccess:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.acl = AclService(session)
        self.repo = ResourceAclRepository(session)

    async def entries(self, org_id: str, object_id: str) -> list[ResourceAcl]:
        rows = await self.repo.list_for_resource(org_id, RESOURCE_STRUCTURED, object_id)
        order = {"manage": 0, "edit": 1, "read": 2}
        effect_order = {EFFECT_DENY: 0, EFFECT_ALLOW: 1}
        return sorted(
            rows,
            key=lambda r: (
                effect_order.get(r.effect or EFFECT_ALLOW, 9),
                order.get(r.permission, 9),
                r.principal_type,
            ),
        )

    async def replace_entries(
        self,
        org_id: str,
        object_id: str,
        entries: Iterable[tuple[str, str, str, str]],
        created_by: str | None,
    ) -> None:
        await self.repo.delete_for_resource(org_id, RESOURCE_STRUCTURED, object_id)
        for ptype, pid, perm, effect in entries:
            self.session.add(
                ResourceAcl(
                    org_id=org_id,
                    resource_type=RESOURCE_STRUCTURED,
                    resource_id=object_id,
                    principal_type=ptype,
                    principal_id=pid,
                    permission=perm,
                    effect=effect or EFFECT_ALLOW,
                    created_by=created_by,
                )
            )
        await self.session.flush()

    async def _restricted_ids(self, org_id: str, object_ids: Sequence[str]) -> set[str]:
        """Object ids that have at least one ALLOW ACL entry (restricted mode)."""
        ids = list(object_ids)
        if not ids:
            return set()
        rows = await self.session.scalars(
            select(ResourceAcl.resource_id).where(
                ResourceAcl.org_id == org_id,
                ResourceAcl.resource_type == RESOURCE_STRUCTURED,
                ResourceAcl.resource_id.in_(ids),
                ResourceAcl.effect == EFFECT_ALLOW,
            )
        )
        return set(rows)

    async def can_read(self, user: CurrentUser, object_id: str) -> bool:
        if user.is_superuser:
            return True
        ref = structured_ref(object_id)
        if await self.acl.is_denied(user.principals, ref):
            return False
        restricted = await self._restricted_ids(user.org_id, [object_id])
        if object_id not in restricted:
            return True
        granted = await self.acl.effective_permission(user.principals, ref)
        return granted is not None and granted.level >= AclPermission.READ.level

    async def require_read(self, user: CurrentUser, object_id: str) -> None:
        """404 when unreadable (do not leak existence), matching KnowledgeAccess.require_kb."""
        if not await self.can_read(user, object_id):
            raise NotFoundError("Structured object not found")

    async def filter_readable(
        self, user: CurrentUser, object_ids: Sequence[str]
    ) -> list[str]:
        ids = list(dict.fromkeys(object_ids))
        if not ids:
            return []
        if user.is_superuser:
            return ids
        pairs = user.principals.pairs()
        denied_rows = await self.repo.list_matching_many(
            user.org_id, RESOURCE_STRUCTURED, ids, pairs, effect=EFFECT_DENY
        )
        denied = {r.resource_id for r in denied_rows}
        restricted = await self._restricted_ids(user.org_id, ids)
        if not restricted and not denied:
            return ids
        granted_rows = await self.repo.list_matching_many(
            user.org_id, RESOURCE_STRUCTURED, ids, pairs, effect=EFFECT_ALLOW
        )
        granted = {r.resource_id for r in granted_rows}
        out: list[str] = []
        for oid in ids:
            if oid in denied:
                continue
            if oid in restricted and oid not in granted:
                continue
            out.append(oid)
        return out

    async def require_manage(self, user: CurrentUser, object_id: str) -> None:
        """Admin ACL edits: platform/admin bypass via is_superuser; else need manage grant."""
        if user.is_superuser:
            return
        ref = structured_ref(object_id)
        if await self.acl.is_denied(user.principals, ref):
            raise PermissionDeniedError(detail={"required_acl": "manage"})
        # Org-default objects: admin:retrieval callers already gated at route; allow manage.
        restricted = await self._restricted_ids(user.org_id, [object_id])
        if object_id not in restricted:
            return
        perm = await self.acl.effective_permission(user.principals, ref)
        if perm is None or perm.level < AclPermission.MANAGE.level:
            raise PermissionDeniedError(detail={"required_acl": "manage"})

    async def can_read_field(
        self, user: CurrentUser, object_id: str, field: str
    ) -> bool:
        """Field ACL: no rows → inherit object readability; DENY wins; ALLOW restricts."""
        if user.is_superuser:
            return True
        if not await self.can_read(user, object_id):
            return False
        ref = structured_field_ref(object_id, field)
        if await self.acl.is_denied(user.principals, ref):
            return False
        rows = await self.repo.list_for_resource(
            user.org_id, RESOURCE_STRUCTURED_FIELD, ref.id
        )
        allows = [r for r in rows if (r.effect or EFFECT_ALLOW) == EFFECT_ALLOW]
        if not allows:
            return True
        granted = await self.acl.effective_permission(user.principals, ref)
        return granted is not None and granted.level >= AclPermission.READ.level

    async def filter_attrs(
        self,
        user: CurrentUser,
        object_id: str,
        attrs: dict[str, object],
    ) -> dict[str, object]:
        """Drop attribute keys the caller cannot read (field-level ACL)."""
        if user.is_superuser or not attrs:
            return dict(attrs)
        out: dict[str, object] = {}
        for key, value in attrs.items():
            if key.startswith("_"):
                out[key] = value
                continue
            if await self.can_read_field(user, object_id, key):
                out[key] = value
        return out

    async def can_read_relation(self, user: CurrentUser, relation_id: str) -> bool:
        if user.is_superuser:
            return True
        ref = object_relation_ref(relation_id)
        if await self.acl.is_denied(user.principals, ref):
            return False
        rows = await self.repo.list_for_resource(
            user.org_id, RESOURCE_OBJECT_RELATION, relation_id
        )
        allows = [r for r in rows if (r.effect or EFFECT_ALLOW) == EFFECT_ALLOW]
        if not allows:
            return True
        granted = await self.acl.effective_permission(user.principals, ref)
        return granted is not None and granted.level >= AclPermission.READ.level
