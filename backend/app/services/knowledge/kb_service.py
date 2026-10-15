from app.core.exceptions import ConflictError, NotFoundError
from app.models import KbVisibility, KnowledgeBase
from app.models.base import utcnow
from app.repositories.base import paginate
from app.repositories.knowledge_repo import DocumentRepository, KnowledgeBaseRepository
from app.schemas.common import Page
from app.schemas.knowledge import (
    KbAclOut,
    KbAclUpdate,
    KnowledgeBaseCreate,
    KnowledgeBaseOut,
    KnowledgeBaseUpdate,
)
from app.services.audit_service import snapshot
from app.services.authz import AclPermission
from app.services.context import BaseService
from app.services.knowledge.access import RESOURCE_KB, KnowledgeAccess
from app.services.knowledge.directory import PrincipalDirectory
from app.services.outbox_service import ACL_CHANGED, OutboxService


def to_kb_out(
    kb: KnowledgeBase, perm: AclPermission | None, document_count: int = 0
) -> KnowledgeBaseOut:
    return KnowledgeBaseOut.model_validate(kb).model_copy(
        update={"my_permission": perm.value if perm else None, "document_count": document_count}
    )


class KnowledgeBaseService(BaseService):
    @property
    def repo(self) -> KnowledgeBaseRepository:
        return KnowledgeBaseRepository(self.session)

    @property
    def access(self) -> KnowledgeAccess:
        return KnowledgeAccess(self.session)

    async def load(
        self, kb_id: str, required: AclPermission = AclPermission.READ
    ) -> tuple[KnowledgeBase, AclPermission]:
        kb = await self.repo.get(self.org_id, kb_id)
        if kb is None:
            raise NotFoundError("Knowledge base not found")
        perm = await self.access.require_kb(self.ctx.user, kb, required)
        return kb, perm

    async def search(
        self, *, page: int, size: int, keyword: str | None = None
    ) -> Page[KnowledgeBaseOut]:
        stmt = self.repo.search_stmt(
            self.org_id, keyword, self.access.readable_kb_clause(self.ctx.user)
        )
        kbs, total = await paginate(self.session, stmt, page, size)
        perms = await self.access.kb_permissions(self.ctx.user, kbs)
        counts = await self.repo.document_counts(self.org_id, [kb.id for kb in kbs])
        items = [to_kb_out(kb, perms.get(kb.id), counts.get(kb.id, 0)) for kb in kbs]
        return Page(items=items, total=total, page=page, size=size)

    async def get(self, kb_id: str) -> KnowledgeBaseOut:
        kb, perm = await self.load(kb_id)
        counts = await self.repo.document_counts(self.org_id, [kb.id])
        return to_kb_out(kb, perm, counts.get(kb.id, 0))

    async def create(self, data: KnowledgeBaseCreate) -> KnowledgeBaseOut:
        if await self.repo.get_by_name(self.org_id, data.name):
            raise ConflictError(f"Knowledge base '{data.name}' already exists")
        kb = await self.repo.add(
            KnowledgeBase(
                org_id=self.org_id,
                name=data.name,
                description=data.description,
                visibility=data.visibility,
                created_by=self.ctx.user.id,
            )
        )
        await self.access.replace_entries(
            self.org_id,
            RESOURCE_KB,
            kb.id,
            [("user", self.ctx.user.id, AclPermission.MANAGE.value)],
            self.ctx.user.id,
        )
        await self.audit.record(self.audit_ctx, "kb.create", RESOURCE_KB, kb.id, None, snapshot(kb))
        return to_kb_out(kb, AclPermission.MANAGE)

    async def update(self, kb_id: str, data: KnowledgeBaseUpdate) -> KnowledgeBaseOut:
        kb, _ = await self.load(kb_id, AclPermission.MANAGE)
        before = snapshot(kb)
        if data.name is not None and data.name != kb.name:
            if await self.repo.get_by_name(self.org_id, data.name):
                raise ConflictError(f"Knowledge base '{data.name}' already exists")
            kb.name = data.name
        if "description" in data.model_fields_set:
            kb.description = data.description
        await self.session.flush()
        await self.audit.record(
            self.audit_ctx, "kb.update", RESOURCE_KB, kb.id, before, snapshot(kb)
        )
        return await self.get(kb.id)

    async def delete(self, kb_id: str) -> None:
        kb, _ = await self.load(kb_id, AclPermission.MANAGE)
        if await DocumentRepository(self.session).count_active(self.org_id, kb.id):
            raise ConflictError("Knowledge base still contains documents")
        before = snapshot(kb)
        kb.deleted_at = utcnow()
        # Free the unique name so it can be reused.
        kb.name = f"{kb.name[:100]}#deleted-{kb.id[:12]}"
        await self.session.flush()
        await self.audit.record(
            self.audit_ctx, "kb.delete", RESOURCE_KB, kb.id, before, snapshot(kb)
        )

    async def get_acl(self, kb_id: str) -> KbAclOut:
        kb, _ = await self.load(kb_id, AclPermission.MANAGE)
        rows = await self.access.entries(self.org_id, RESOURCE_KB, kb.id)
        directory = PrincipalDirectory(self.session, self.org_id)
        entries = await directory.describe(
            (r.principal_type, r.principal_id, r.permission) for r in rows
        )
        return KbAclOut(visibility=kb.visibility, entries=entries)

    async def set_acl(self, kb_id: str, data: KbAclUpdate) -> KbAclOut:
        kb, _ = await self.load(kb_id, AclPermission.MANAGE)
        entries = await PrincipalDirectory(self.session, self.org_id).validate(data.entries)
        if not self.ctx.user.is_superuser and not any(
            e.permission == AclPermission.MANAGE.value for e in entries
        ):
            raise ConflictError("At least one principal must keep 'manage' permission")
        before_rows = await self.access.entries(self.org_id, RESOURCE_KB, kb.id)
        before = {
            "visibility": kb.visibility,
            "entries": sorted(
                f"{r.principal_type}:{r.principal_id}:{r.permission}" for r in before_rows
            ),
        }
        kb.visibility = KbVisibility(data.visibility).value
        await self.access.replace_entries(
            self.org_id,
            RESOURCE_KB,
            kb.id,
            [(e.principal_type, e.principal_id, e.permission) for e in entries],
            self.ctx.user.id,
        )
        after = {
            "visibility": kb.visibility,
            "entries": sorted(
                f"{e.principal_type}:{e.principal_id}:{e.permission}" for e in entries
            ),
        }
        if before != after:
            await OutboxService(self.session).publish(
                self.org_id,
                RESOURCE_KB,
                kb.id,
                ACL_CHANGED,
                {"resource_type": RESOURCE_KB, "resource_id": kb.id, "kb_id": kb.id},
            )
        await self.audit.record(self.audit_ctx, "kb.set_acl", RESOURCE_KB, kb.id, before, after)
        return await self.get_acl(kb.id)
