"""Knowledge objects: drafting (manual / AI), review workflow, publishing, ACL, versions.

State machine of the working copy: draft -> pending_review -> published -> deprecated.
Editing a published KO starts a new draft while the published version stays live.
"""

from collections.abc import Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import (
    AppError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationAppError,
)
from app.llm import LLMError, LLMGateway
from app.models import (
    ACTIVE_GAP_STATUSES,
    Document,
    GapStatus,
    KnowledgeBase,
    KnowledgeGap,
    KnowledgeObject,
    KoOrigin,
    KoStatus,
    KoVersion,
    KoVersionStatus,
    ReviewStatus,
    ReviewTask,
    User,
)
from app.models.base import utcnow
from app.repositories.base import paginate
from app.repositories.chat_repo import ChunkRepository as AnswerChunkRepository
from app.repositories.curation_repo import (
    GapRepository,
    KnowledgeObjectRepository,
    ReviewTaskRepository,
)
from app.repositories.indexing_repo import IndexingRepository
from app.repositories.knowledge_repo import DocumentRepository, KnowledgeBaseRepository
from app.retrieval.pipeline import RetrievalPipeline
from app.schemas.common import Page
from app.schemas.curation import (
    FaqGenerateIn,
    GapDraftIn,
    KoCreate,
    KoDetailOut,
    KoOut,
    KoSourceIn,
    KoSourceOut,
    KoUpdate,
    KoVersionOut,
    ReviewTaskOut,
)
from app.schemas.knowledge import DocumentAclOut, DocumentAclUpdate
from app.services.authz import AclPermission, AuthzCache
from app.services.context import BaseService, RequestContext
from app.services.curation.clustering import gap_text, refresh_cluster_stats
from app.services.curation.common import (
    RESOURCE_KO_AUDIT,
    kb_names,
    readable_kb_scope,
    user_refs,
)
from app.services.curation.compiler import KnowledgeCompiler, KoDraft, Material
from app.services.curation.conflicts import ConflictDetector
from app.services.curation.lifecycle import KoLifecycle, ko_link, ko_snapshot
from app.services.curation.notifications import NotificationKind, notify
from app.services.knowledge.access import RESOURCE_KB, RESOURCE_KO, KnowledgeAccess
from app.services.knowledge.directory import PrincipalDirectory
from app.services.outbox_service import ACL_CHANGED, OutboxService
from app.services.search.search_service import SearchParams, SearchService

REVIEW_PERMISSION = "review:approve"
MAX_SIMILAR_QUESTIONS = 8
NOTE_TITLE = "审核人补充资料"
UNAVAILABLE_TITLE = "（文档已删除或无权访问）"


class CompilerUnavailableError(AppError):
    status_code = 503
    code = "COMPILER_UNAVAILABLE"
    message = "AI 生成失败，请稍后重试"


def _entry_strings(rows: Sequence[tuple[str, str, str]]) -> list[str]:
    return sorted(f"{t}:{i}:{p}" for t, i, p in rows)


class KnowledgeObjectService(BaseService):
    def __init__(
        self,
        session: AsyncSession,
        ctx: RequestContext,
        authz_cache: AuthzCache,
        *,
        pipeline: RetrievalPipeline,
        gateway: LLMGateway,
        settings: Settings,
    ) -> None:
        super().__init__(session, ctx, authz_cache)
        self.settings = settings
        self.repo = KnowledgeObjectRepository(session)
        self.tasks = ReviewTaskRepository(session)
        self.gaps = GapRepository(session)
        self.access = KnowledgeAccess(session)
        self.search = SearchService(session, ctx, authz_cache, pipeline=pipeline, settings=settings)
        self.compiler = KnowledgeCompiler(gateway, settings)
        self.lifecycle = KoLifecycle(session, ctx.audit)

    # ---- access ------------------------------------------------------------------------

    async def _kb(self, kb_id: str, required: AclPermission) -> KnowledgeBase:
        kb = await KnowledgeBaseRepository(self.session).get(self.org_id, kb_id)
        if kb is None:
            raise NotFoundError("Knowledge base not found")
        await self.access.require_kb(self.ctx.user, kb, required)
        return kb

    async def _permission(self, ko: KnowledgeObject, kb: KnowledgeBase) -> AclPermission | None:
        kb_perm = await self.access.kb_permission(self.ctx.user, kb)
        perms = await self.access.resource_permissions(self.ctx.user, [ko], kb_perm, RESOURCE_KO)
        return perms.get(ko.id)

    async def _ko(
        self, ko_id: str, required: AclPermission = AclPermission.EDIT
    ) -> tuple[KnowledgeObject, KnowledgeBase]:
        ko = await self.repo.get(self.org_id, ko_id)
        kb = await KnowledgeBaseRepository(self.session).get(self.org_id, ko.kb_id) if ko else None
        if ko is None or kb is None:
            raise NotFoundError("Knowledge object not found")
        perm = await self._permission(ko, kb)
        if perm is None:
            raise NotFoundError("Knowledge object not found")
        if perm.level < required.level:
            raise PermissionDeniedError(detail={"required_acl": required.value})
        return ko, kb

    def _can_review(self) -> bool:
        return self.ctx.user.has_permission(REVIEW_PERMISSION)

    # ---- sources -----------------------------------------------------------------------

    async def _sources(self, items: Sequence[KoSourceIn]) -> list[dict[str, Any]]:
        """Validate cited documents / chunks (must be readable now) into stored sources."""
        readable = await self.access.readable_documents(
            self.ctx.user, [s.document_id for s in items]
        )
        missing = sorted({s.document_id for s in items} - set(readable))
        if missing:
            raise ValidationAppError("引用的文档不存在或无权访问", detail={"document_ids": missing})
        chunks = await AnswerChunkRepository(self.session).by_ids(
            self.org_id, [s.chunk_id for s in items if s.chunk_id]
        )
        result: list[dict[str, Any]] = []
        seen: set[tuple[str, str | None]] = set()
        for s in items:
            doc = readable[s.document_id][0]
            chunk = chunks.get(s.chunk_id) if s.chunk_id else None
            if chunk is not None and chunk.document_id != doc.id:
                chunk = None
            key = (doc.id, chunk.id if chunk else None)
            if key in seen:
                continue
            seen.add(key)
            quote = (s.quote or (chunk.content if chunk else "") or "").strip()
            result.append(
                {
                    "document_id": doc.id,
                    "chunk_id": chunk.id if chunk else None,
                    "title": doc.title,
                    "heading_path": list(chunk.heading_path or []) if chunk else [],
                    "quote": quote[:300] or None,
                    "doc_version": chunk.document_version if chunk else doc.version,
                }
            )
        return result

    async def _sources_out(self, sources: Sequence[dict[str, Any]]) -> list[KoSourceOut]:
        readable = await self.access.readable_documents(
            self.ctx.user, [s.get("document_id", "") for s in sources]
        )
        out = []
        for s in sources:
            doc_id = s.get("document_id", "")
            available = doc_id in readable
            out.append(
                KoSourceOut(
                    document_id=doc_id,
                    chunk_id=s.get("chunk_id") if available else None,
                    title=readable[doc_id][0].title if available else UNAVAILABLE_TITLE,
                    heading_path=list(s.get("heading_path") or []) if available else [],
                    quote=s.get("quote") if available else None,
                    doc_version=s.get("doc_version"),
                    available=available,
                )
            )
        return out

    # ---- views -------------------------------------------------------------------------

    async def _outs(self, kos: Sequence[KnowledgeObject]) -> list[KoOut]:
        users = await user_refs(self.session, self.org_id, [k.owner_id for k in kos])
        names = await kb_names(self.session, self.org_id, [k.kb_id for k in kos])
        return [
            KoOut(
                id=k.id,
                kb_id=k.kb_id,
                kb_name=names.get(k.kb_id),
                ko_type=k.ko_type,
                title=k.title,
                question=k.question,
                variants=list(k.variants or []),
                status=k.status,
                version=k.version,
                published_version=k.published_version,
                origin=k.origin,
                owner=users.get(k.owner_id or ""),
                effective_from=k.effective_from,
                effective_to=k.effective_to,
                conflict_count=sum(1 for c in k.conflicts or [] if c.get("verdict") == "conflict"),
                published_at=k.published_at,
                created_at=k.created_at,
                updated_at=k.updated_at,
            )
            for k in kos
        ]

    async def task_outs(self, tasks: Sequence[ReviewTask]) -> list[ReviewTaskOut]:
        users = await user_refs(
            self.session,
            self.org_id,
            [t.submitted_by for t in tasks] + [t.reviewer_id for t in tasks],
        )
        kos = {
            k.id: k
            for k, _ in await self.repo.objects_with_kbs(
                self.org_id, sorted({t.ko_id for t in tasks})
            )
        }
        return [
            ReviewTaskOut(
                id=t.id,
                ko_id=t.ko_id,
                ko_title=kos[t.ko_id].title if t.ko_id in kos else None,
                kb_id=kos[t.ko_id].kb_id if t.ko_id in kos else None,
                ko_version=t.ko_version,
                status=t.status,
                submitted_by=users.get(t.submitted_by or ""),
                note=t.note,
                reviewer=users.get(t.reviewer_id or ""),
                comment=t.comment,
                decided_at=t.decided_at,
                conflicts=list(t.conflicts or []),
                created_at=t.created_at,
            )
            for t in tasks
        ]

    async def _detail(self, ko: KnowledgeObject) -> KoDetailOut:
        (base,) = await self._outs([ko])
        tasks = await self.tasks.for_ko(ko.id)
        task_outs = await self.task_outs(tasks)
        pending = next((t for t in task_outs if t.status == ReviewStatus.PENDING.value), None)
        return KoDetailOut(
            **base.model_dump(),
            answer=ko.answer,
            sources=await self._sources_out(ko.sources or []),
            acl_inherit=ko.acl_inherit,
            gap_ids=list(ko.gap_ids or []),
            ai_draft=dict(ko.ai_draft or {}),
            conflicts=list(ko.conflicts or []),
            conflicts_checked_at=ko.conflicts_checked_at,
            pending_review=pending,
            reviews=task_outs,
            can_edit=ko.status != KoStatus.PENDING_REVIEW.value,
            can_review=pending is not None and self._can_review(),
        )

    async def list_page(
        self,
        *,
        kb_id: str | None,
        status: str | None,
        ko_type: str | None,
        owner_id: str | None,
        keyword: str | None,
        page: int,
        size: int,
    ) -> Page[KoOut]:
        stmt = self.repo.list_stmt(
            self.org_id,
            kb_scope=readable_kb_scope(self.access, self.ctx.user, KnowledgeObject.kb_id),
            kb_id=kb_id,
            status=status,
            ko_type=ko_type,
            owner_id=owner_id,
            keyword=keyword,
        )
        rows, total = await paginate(self.session, stmt, page, size)
        return Page(items=await self._outs(rows), total=total, page=page, size=size)

    async def get(self, ko_id: str) -> KoDetailOut:
        ko, _ = await self._ko(ko_id)
        return await self._detail(ko)

    async def review_tasks(
        self, *, status: str | None, page: int, size: int
    ) -> Page[ReviewTaskOut]:
        stmt = self.tasks.list_stmt(
            self.org_id,
            readable_kb_scope(self.access, self.ctx.user, KnowledgeObject.kb_id),
            status,
        )
        rows, total = await paginate(self.session, stmt, page, size)
        return Page(items=await self.task_outs(rows), total=total, page=page, size=size)

    # ---- editing -----------------------------------------------------------------------

    async def _owner(self, owner_id: str | None) -> str | None:
        if owner_id is None:
            return None
        user = await self.session.get(User, owner_id)
        if user is None or user.org_id != self.org_id:
            raise ValidationAppError("负责人不存在", detail={"owner_id": owner_id})
        return owner_id

    async def _link_gaps(self, gap_ids: Sequence[str], ko: KnowledgeObject) -> list[str]:
        gaps = await self.gaps.many(self.org_id, list(dict.fromkeys(gap_ids)))
        linked = []
        for gap in gaps:
            if gap.status not in ACTIVE_GAP_STATUSES:
                continue
            gap.status = GapStatus.IN_REVIEW.value
            gap.assignee_id = gap.assignee_id or self.ctx.user.id
            gap.resolution = {**(gap.resolution or {}), "ko_id": ko.id}
            if gap.kb_id is None:
                gap.kb_id = ko.kb_id
            linked.append(gap.id)
        for cluster_id in sorted({g.cluster_id for g in gaps if g.cluster_id}):
            await refresh_cluster_stats(self.session, cluster_id)
        return linked

    async def _create(
        self,
        kb: KnowledgeBase,
        *,
        ko_type: str,
        title: str | None,
        question: str,
        variants: list[str],
        answer: str,
        sources: list[dict[str, Any]],
        origin: KoOrigin,
        gap_ids: Sequence[str] = (),
        ai_draft: dict[str, Any] | None = None,
        owner_id: str | None = None,
        effective_from: Any = None,
        effective_to: Any = None,
    ) -> KnowledgeObject:
        user_id = self.ctx.user.id
        ko = KnowledgeObject(
            org_id=self.org_id,
            kb_id=kb.id,
            ko_type=ko_type,
            title=(title or question)[:512],
            question=question,
            variants=[v for v in variants if v != question],
            answer=answer,
            sources=sources,
            status=KoStatus.DRAFT.value,
            version=0,
            acl_inherit=True,
            effective_from=effective_from,
            effective_to=effective_to,
            owner_id=owner_id or user_id,
            origin=origin.value,
            gap_ids=[],
            ai_draft=ai_draft or {},
            conflicts=[],
            created_by=user_id,
            updated_by=user_id,
        )
        self.session.add(ko)
        await self.session.flush()
        if gap_ids:
            ko.gap_ids = await self._link_gaps(gap_ids, ko)
        await self.audit.record(
            self.audit_ctx,
            "ko.create",
            RESOURCE_KO_AUDIT,
            ko.id,
            None,
            {**ko_snapshot(ko), "origin": ko.origin, "gap_ids": ko.gap_ids},
        )
        return ko

    async def create(self, data: KoCreate) -> KoDetailOut:
        kb = await self._kb(data.kb_id, AclPermission.EDIT)
        ko = await self._create(
            kb,
            ko_type=data.ko_type.value,
            title=data.title,
            question=data.question,
            variants=data.variants,
            answer=data.answer.strip(),
            sources=await self._sources(data.sources),
            origin=KoOrigin.GAP if data.gap_ids else KoOrigin.MANUAL,
            gap_ids=data.gap_ids,
            owner_id=await self._owner(data.owner_id),
            effective_from=data.effective_from,
            effective_to=data.effective_to,
        )
        return await self._detail(ko)

    async def update(self, ko_id: str, data: KoUpdate) -> KoDetailOut:
        ko, _ = await self._ko(ko_id)
        if ko.status == KoStatus.PENDING_REVIEW.value:
            raise ConflictError("知识条目正在审核中，请先撤回再修改")
        before = ko_snapshot(ko)
        sources = await self._sources(data.sources)
        content_changed = (
            ko.question != data.question
            or list(ko.variants or []) != data.variants
            or ko.answer != data.answer.strip()
        )
        ko.ko_type = data.ko_type.value
        ko.title = (data.title or data.question)[:512]
        ko.question = data.question
        ko.variants = [v for v in data.variants if v != data.question]
        ko.answer = data.answer.strip()
        ko.sources = sources
        ko.effective_from = data.effective_from
        ko.effective_to = data.effective_to
        if "owner_id" in data.model_fields_set:
            ko.owner_id = await self._owner(data.owner_id) or ko.owner_id
        ko.status = KoStatus.DRAFT.value
        ko.updated_by = self.ctx.user.id
        if content_changed:
            ko.conflicts = []
            ko.conflicts_checked_at = None
        await self.session.flush()
        await self.audit.record(
            self.audit_ctx, "ko.update", RESOURCE_KO_AUDIT, ko.id, before, ko_snapshot(ko)
        )
        return await self._detail(ko)

    # ---- review workflow ---------------------------------------------------------------

    async def _detect(self, ko: KnowledgeObject) -> None:
        detector = ConflictDetector(self.search, self.compiler, self.settings)
        ko.conflicts = await detector.detect(ko)
        ko.conflicts_checked_at = utcnow()

    async def check_conflicts(self, ko_id: str) -> KoDetailOut:
        ko, _ = await self._ko(ko_id)
        await self._detect(ko)
        await self.session.flush()
        return await self._detail(ko)

    async def submit(self, ko_id: str, note: str | None) -> KoDetailOut:
        ko, _ = await self._ko(ko_id)
        if ko.status == KoStatus.PENDING_REVIEW.value:
            raise ConflictError("知识条目已在审核中")
        if ko.status == KoStatus.PUBLISHED.value:
            raise ConflictError("当前内容已发布，修改后再提交审核")
        if not ko.answer.strip():
            raise ValidationAppError("答案不能为空")
        if ko.conflicts_checked_at is None:
            await self._detect(ko)
        before = ko_snapshot(ko)
        ko.version += 1
        user_id = self.ctx.user.id
        self.session.add(
            KoVersion(
                org_id=self.org_id,
                ko_id=ko.id,
                version=ko.version,
                ko_type=ko.ko_type,
                title=ko.title,
                question=ko.question,
                variants=list(ko.variants or []),
                answer=ko.answer,
                sources=list(ko.sources or []),
                effective_from=ko.effective_from,
                effective_to=ko.effective_to,
                status=KoVersionStatus.PENDING_REVIEW.value,
                note=note,
                created_by=user_id,
            )
        )
        self.session.add(
            ReviewTask(
                org_id=self.org_id,
                ko_id=ko.id,
                ko_version=ko.version,
                status=ReviewStatus.PENDING.value,
                submitted_by=user_id,
                note=note,
                conflicts=list(ko.conflicts or []),
            )
        )
        ko.status = KoStatus.PENDING_REVIEW.value
        ko.updated_by = user_id
        await self.session.flush()
        await self.audit.record(
            self.audit_ctx, "ko.submit", RESOURCE_KO_AUDIT, ko.id, before, ko_snapshot(ko)
        )
        return await self._detail(ko)

    async def _settle(self, ko: KnowledgeObject, version_status: KoVersionStatus) -> None:
        """Close the pending version; its content stays as the draft working copy (a live
        published version, if any, is unaffected)."""
        await self.repo.mark_versions(
            ko.id, KoVersionStatus.PENDING_REVIEW.value, version_status.value
        )
        ko.status = KoStatus.DRAFT.value

    async def withdraw(self, ko_id: str) -> KoDetailOut:
        ko, _ = await self._ko(ko_id)
        task = await self.tasks.pending_for(ko.id)
        if task is None or ko.status != KoStatus.PENDING_REVIEW.value:
            raise ConflictError("没有待审核的版本")
        before = ko_snapshot(ko)
        task.status = ReviewStatus.CANCELLED.value
        task.decided_at = utcnow()
        await self._settle(ko, KoVersionStatus.WITHDRAWN)
        await self.session.flush()
        await self.audit.record(
            self.audit_ctx, "ko.withdraw", RESOURCE_KO_AUDIT, ko.id, before, ko_snapshot(ko)
        )
        return await self._detail(ko)

    async def review(self, ko_id: str, approve: bool, comment: str | None) -> KoDetailOut:
        if not self._can_review():
            raise PermissionDeniedError(detail={"required": REVIEW_PERMISSION})
        ko, _ = await self._ko(ko_id)
        task = await self.tasks.pending_for(ko.id)
        if task is None or ko.status != KoStatus.PENDING_REVIEW.value:
            raise ConflictError("没有待审核的版本")
        user = self.ctx.user
        if task.submitted_by == user.id and not user.is_superuser:
            raise PermissionDeniedError("不能审核自己提交的版本")
        snapshot = await self.repo.version(ko.id, task.ko_version)
        if snapshot is None:
            raise NotFoundError("Knowledge object version not found")
        now = utcnow()
        task.reviewer_id = user.id
        task.comment = comment
        task.decided_at = now
        if approve:
            task.status = ReviewStatus.APPROVED.value
            await self.lifecycle.publish(ko, snapshot, user.id)
            kind, title = NotificationKind.KO_PUBLISHED, f"知识条目已发布：{ko.title[:80]}"
        else:
            before = ko_snapshot(ko)
            task.status = ReviewStatus.REJECTED.value
            await self._settle(ko, KoVersionStatus.REJECTED)
            await self.audit.record(
                self.audit_ctx,
                "ko.reject",
                RESOURCE_KO_AUDIT,
                ko.id,
                before,
                {**ko_snapshot(ko), "comment": comment},
            )
            kind, title = NotificationKind.KO_REJECTED, f"知识条目审核未通过：{ko.title[:80]}"
        await notify(
            self.session,
            self.org_id,
            [task.submitted_by, ko.owner_id],
            kind=kind,
            title=title,
            body=comment,
            resource_type=RESOURCE_KO,
            resource_id=ko.id,
            link=ko_link(ko.id),
        )
        await self.session.flush()
        return await self._detail(ko)

    async def deprecate(self, ko_id: str, reason: str | None) -> KoDetailOut:
        ko, _ = await self._ko(ko_id)
        if ko.status == KoStatus.DEPRECATED.value:
            raise ConflictError("知识条目已下线")
        await self.lifecycle.deprecate(ko, self.ctx.user.id, reason)
        await self.session.flush()
        return await self._detail(ko)

    # ---- versions ----------------------------------------------------------------------

    async def _version_outs(self, versions: Sequence[KoVersion]) -> list[KoVersionOut]:
        users = await user_refs(
            self.session,
            self.org_id,
            [v.created_by for v in versions] + [v.published_by for v in versions],
        )
        return [
            KoVersionOut(
                id=v.id,
                ko_id=v.ko_id,
                version=v.version,
                ko_type=v.ko_type,
                title=v.title,
                question=v.question,
                variants=list(v.variants or []),
                answer=v.answer,
                sources=list(v.sources or []),
                effective_from=v.effective_from,
                effective_to=v.effective_to,
                status=v.status,
                note=v.note,
                created_by=users.get(v.created_by or ""),
                created_at=v.created_at,
                published_at=v.published_at,
                published_by=users.get(v.published_by or ""),
            )
            for v in versions
        ]

    async def versions(self, ko_id: str) -> list[KoVersionOut]:
        ko, _ = await self._ko(ko_id)
        return await self._version_outs(await self.repo.versions(ko.id))

    async def version(self, ko_id: str, version: int) -> KoVersionOut:
        ko, _ = await self._ko(ko_id)
        found = await self.repo.version(ko.id, version)
        if found is None:
            raise NotFoundError("Knowledge object version not found")
        (out,) = await self._version_outs([found])
        return out

    # ---- ACL ---------------------------------------------------------------------------

    async def get_acl(self, ko_id: str) -> DocumentAclOut:
        ko, kb = await self._ko(ko_id, AclPermission.MANAGE)
        directory = PrincipalDirectory(self.session, self.org_id)
        kb_rows = await self.access.entries(self.org_id, RESOURCE_KB, kb.id)
        rows = await self.access.entries(self.org_id, RESOURCE_KO, ko.id)
        return DocumentAclOut(
            inherit=ko.acl_inherit,
            kb_visibility=kb.visibility,
            kb_entries=await directory.describe(
                (r.principal_type, r.principal_id, r.permission) for r in kb_rows
            ),
            entries=await directory.describe(
                (r.principal_type, r.principal_id, r.permission) for r in rows
            ),
        )

    async def set_acl(self, ko_id: str, data: DocumentAclUpdate) -> DocumentAclOut:
        ko, kb = await self._ko(ko_id, AclPermission.MANAGE)
        entries = await PrincipalDirectory(self.session, self.org_id).validate(data.entries)
        new_rows = (
            []
            if data.inherit
            else [(e.principal_type, e.principal_id, e.permission) for e in entries]
        )
        old_rows = [
            (r.principal_type, r.principal_id, r.permission)
            for r in await self.access.entries(self.org_id, RESOURCE_KO, ko.id)
        ]
        before = {"inherit": ko.acl_inherit, "entries": _entry_strings(old_rows)}
        ko.acl_inherit = data.inherit
        await self.access.replace_entries(
            self.org_id, RESOURCE_KO, ko.id, new_rows, self.ctx.user.id
        )
        after = {"inherit": ko.acl_inherit, "entries": _entry_strings(new_rows)}
        if before != after:
            await OutboxService(self.session).publish(
                self.org_id,
                RESOURCE_KO,
                ko.id,
                ACL_CHANGED,
                {"resource_type": RESOURCE_KO, "resource_id": ko.id, "kb_id": kb.id},
            )
        await self.audit.record(
            self.audit_ctx, "ko.set_acl", RESOURCE_KO_AUDIT, ko.id, before, after
        )
        return await self.get_acl(ko.id)

    # ---- AI drafts ---------------------------------------------------------------------

    async def _gap(self, gap_id: str) -> KnowledgeGap:
        gap = await self.gaps.get(self.org_id, gap_id)
        if gap is None:
            raise NotFoundError("Knowledge gap not found")
        return gap

    async def _document_materials(self, docs: Sequence[Document], per_doc: int) -> list[Material]:
        repo = IndexingRepository(self.session)
        materials: list[Material] = []
        for doc in docs:
            for chunk in (await repo.index_chunks(doc.id, doc.version))[:per_doc]:
                materials.append(
                    Material(
                        title=doc.title,
                        content=chunk.content,
                        document_id=doc.id,
                        chunk_id=chunk.id,
                        heading_path=tuple(chunk.heading_path or []),
                        doc_version=chunk.document_version,
                    )
                )
        return materials

    async def _search_materials(
        self, question: str, kb_id: str, document_ids: Sequence[str]
    ) -> list[Material]:
        limit = self.settings.ko_compiler_max_materials
        try:
            run = await self.search.execute(
                SearchParams(q=question[:500], kb_ids=(kb_id,), top_k=max(limit * 2, 10))
            )
        except ValidationAppError:
            return []
        results = run.outcome.results if run.outcome else []
        materials = []
        for r in results:
            p = r.passage
            if p.is_ko or (document_ids and p.document.id not in document_ids):
                continue
            materials.append(
                Material(
                    title=p.document.title,
                    content=p.content,
                    document_id=p.document.id,
                    chunk_id=p.chunk_id,
                    heading_path=tuple(p.heading_path),
                    doc_version=p.document.version,
                )
            )
        return materials[:limit]

    async def draft_from_gap(self, gap_id: str, data: GapDraftIn) -> KoDetailOut:
        gap = await self._gap(gap_id)
        kb_id = data.kb_id or gap.kb_id
        if kb_id is None:
            raise ValidationAppError("请先为该缺口指定知识库")
        kb = await self._kb(kb_id, AclPermission.EDIT)
        question = gap_text(gap)

        related: list[KnowledgeGap] = [gap]
        if gap.cluster_id:
            related += [
                g
                for g in await self.gaps.cluster_members(self.org_id, gap.cluster_id)
                if g.id != gap.id and g.status in ACTIVE_GAP_STATUSES
            ]
        candidates = [gap.query.strip(), *(gap_text(g) for g in related[1:])]
        similar = list(dict.fromkeys(t for t in candidates if t and t != question))
        similar = similar[:MAX_SIMILAR_QUESTIONS]

        materials: list[Material] = []
        if data.notes and data.notes.strip():
            materials.append(Material(title=NOTE_TITLE, content=data.notes.strip(), is_note=True))
        if data.document_ids:
            readable = await self.access.readable_documents(self.ctx.user, data.document_ids)
            missing = sorted(set(data.document_ids) - set(readable))
            if missing:
                raise ValidationAppError(
                    "指定的文档不存在或无权访问", detail={"document_ids": missing}
                )
            found = await self._search_materials(question, kb.id, data.document_ids)
            covered = {m.document_id for m in found}
            materials += found
            materials += await self._document_materials(
                [readable[d][0] for d in data.document_ids if d not in covered], per_doc=3
            )
        else:
            materials += await self._search_materials(question, kb.id, ())

        draft = await self.compiler.draft(question, similar, materials)
        ko = await self._create(
            kb,
            ko_type=data.ko_type.value,
            title=draft.title,
            question=draft.question,
            variants=draft.variants,
            answer=draft.answer,
            sources=draft.sources,
            origin=KoOrigin.GAP,
            gap_ids=[g.id for g in related],
            ai_draft={
                **draft.describe(),
                "materials": [
                    {**(m.source() or {"title": m.title, "quote": m.content[:300]}), "n": n}
                    for n, m in enumerate(materials, start=1)
                ],
                "gap_id": gap.id,
                "similar": similar,
            },
        )
        return await self._detail(ko)

    async def faq_from_document(self, document_id: str, data: FaqGenerateIn) -> list[KoOut]:
        doc = await DocumentRepository(self.session).get(self.org_id, document_id)
        kb = (
            await KnowledgeBaseRepository(self.session).get(self.org_id, doc.kb_id) if doc else None
        )
        if doc is None or kb is None:
            raise NotFoundError("Document not found")
        await self.access.require_document(self.ctx.user, doc, kb, AclPermission.READ)
        await self.access.require_kb(self.ctx.user, kb, AclPermission.EDIT)
        materials = await self._document_materials(
            [doc], per_doc=self.settings.ko_compiler_max_materials
        )
        if not materials:
            raise ValidationAppError("文档尚未解析完成，无法生成 FAQ")
        try:
            drafts: list[KoDraft] = await self.compiler.faqs(materials, data.max_items)
        except (LLMError, ValueError) as exc:
            raise CompilerUnavailableError(detail={"error": str(exc)[:300]}) from exc
        created = []
        for draft in drafts:
            created.append(
                await self._create(
                    kb,
                    ko_type=data.ko_type.value,
                    title=draft.title,
                    question=draft.question,
                    variants=draft.variants,
                    answer=draft.answer,
                    sources=draft.sources,
                    origin=KoOrigin.DOCUMENT,
                    ai_draft={**draft.describe(), "document_id": doc.id},
                )
            )
        return await self._outs(created)
