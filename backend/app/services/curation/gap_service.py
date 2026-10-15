"""Knowledge gap review: board, detail (original conversation + QA trace), triage actions.

The reviewer sees the asker's conversation and trace only as far as their own permissions
allow: answers citing material they cannot read are withheld, and so is trace content.
"""

import copy
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select

from app.core.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.models import (
    ACTIVE_GAP_STATUSES,
    GapCluster,
    GapStatus,
    KnowledgeGap,
    KnowledgeObject,
    Message,
    MessageRole,
    User,
)
from app.models.base import utcnow
from app.repositories.base import paginate
from app.repositories.chat_repo import ConversationRepository
from app.repositories.curation_repo import GapClusterRepository, GapRepository
from app.repositories.knowledge_repo import KnowledgeBaseRepository
from app.schemas.common import Page
from app.schemas.curation import (
    ConversationMessageOut,
    GapClusterOut,
    GapDetailOut,
    GapDuplicateIn,
    GapKoRef,
    GapLinkDocumentsIn,
    GapOut,
    GapPatch,
    GapSort,
    GapStatsOut,
)
from app.services.authz import AclPermission
from app.services.context import BaseService
from app.services.curation.clustering import refresh_cluster_stats
from app.services.curation.common import RESOURCE_GAP, kb_names, readable_kb_scope, user_refs
from app.services.curation.notifications import NotificationKind, notify
from app.services.knowledge.access import KnowledgeAccess
from app.services.knowledge.ko_access import KoAccess

CONVERSATION_CONTEXT_MESSAGES = 10
REDACTED_ANSWER = "（该回答引用了你无权访问的资料，内容已隐藏）"


def _gap_snapshot(gap: KnowledgeGap) -> dict[str, Any]:
    return {
        "status": gap.status,
        "kb_id": gap.kb_id,
        "assignee_id": gap.assignee_id,
        "duplicate_of_id": gap.duplicate_of_id,
        "resolution": gap.resolution,
    }


class GapService(BaseService):
    @property
    def repo(self) -> GapRepository:
        return GapRepository(self.session)

    @property
    def access(self) -> KnowledgeAccess:
        return KnowledgeAccess(self.session)

    def _scope(self) -> Any:
        return readable_kb_scope(
            self.access, self.ctx.user, KnowledgeGap.kb_id, include_unscoped=True
        )

    async def _gap(self, gap_id: str, required: AclPermission = AclPermission.EDIT) -> KnowledgeGap:
        gap = await self.repo.get(self.org_id, gap_id)
        if gap is None:
            raise NotFoundError("Knowledge gap not found")
        if gap.kb_id is not None:
            kb = await KnowledgeBaseRepository(self.session).get(self.org_id, gap.kb_id)
            if kb is None:
                raise NotFoundError("Knowledge gap not found")
            await self.access.require_kb(self.ctx.user, kb, required)
        return gap

    # ---- views -------------------------------------------------------------------------

    async def _outs(self, gaps: Sequence[KnowledgeGap]) -> list[GapOut]:
        users = await user_refs(self.session, self.org_id, [g.assignee_id for g in gaps])
        names = await kb_names(self.session, self.org_id, [g.kb_id for g in gaps])
        cluster_ids = sorted({g.cluster_id for g in gaps if g.cluster_id})
        clusters: dict[str, GapCluster] = {}
        if cluster_ids:
            stmt = select(GapCluster).where(GapCluster.id.in_(cluster_ids))
            clusters = {c.id: c for c in (await self.session.execute(stmt)).scalars()}
        out = []
        for g in gaps:
            cluster = clusters.get(g.cluster_id or "")
            out.append(
                GapOut(
                    id=g.id,
                    gap_type=g.gap_type,
                    status=g.status,
                    query=g.query,
                    rewritten_query=g.rewritten_query,
                    description=g.description,
                    kb_id=g.kb_id,
                    kb_name=names.get(g.kb_id or ""),
                    cluster_id=g.cluster_id,
                    occurrences=g.occurrences,
                    cluster_occurrences=cluster.occurrences if cluster else None,
                    cluster_size=cluster.gap_count if cluster else None,
                    top_score=g.top_score,
                    assignee=users.get(g.assignee_id or ""),
                    user_id=g.user_id,
                    conversation_id=g.conversation_id,
                    message_id=g.message_id,
                    trace_id=g.trace_id,
                    duplicate_of_id=g.duplicate_of_id,
                    resolution=dict(g.resolution or {}),
                    resolved_at=g.resolved_at,
                    created_at=g.created_at,
                    last_seen_at=g.last_seen_at,
                )
            )
        return out

    async def list_page(
        self,
        *,
        statuses: Sequence[str],
        gap_type: str | None,
        kb_id: str | None,
        cluster_id: str | None,
        assignee_id: str | None,
        keyword: str | None,
        sort: GapSort,
        page: int,
        size: int,
    ) -> Page[GapOut]:
        stmt = self.repo.list_stmt(
            self.org_id,
            kb_scope=self._scope(),
            statuses=statuses,
            gap_type=gap_type,
            kb_id=kb_id,
            cluster_id=cluster_id,
            assignee_id=assignee_id,
            keyword=keyword,
            sort=sort,
        )
        rows, total = await paginate(self.session, stmt, page, size)
        return Page(items=await self._outs(rows), total=total, page=page, size=size)

    async def stats(self) -> GapStatsOut:
        scope = self._scope()
        clusters_scope = readable_kb_scope(
            self.access, self.ctx.user, GapCluster.kb_id, include_unscoped=True
        )
        stmt = select(GapCluster.id).where(
            GapCluster.org_id == self.org_id, GapCluster.open_count > 0, clusters_scope
        )
        return GapStatsOut(
            by_status=await self.repo.status_counts(self.org_id, scope),
            by_source=await self.repo.source_counts(self.org_id, scope),
            clusters_open=len((await self.session.execute(stmt)).all()),
        )

    async def clusters(
        self, *, kb_id: str | None, open_only: bool, page: int, size: int
    ) -> Page[GapClusterOut]:
        stmt = GapClusterRepository(self.session).list_stmt(self.org_id, kb_id, open_only)
        stmt = stmt.where(
            readable_kb_scope(self.access, self.ctx.user, GapCluster.kb_id, include_unscoped=True)
        )
        rows, total = await paginate(self.session, stmt, page, size)
        return Page(
            items=[GapClusterOut.model_validate(r) for r in rows],
            total=total,
            page=page,
            size=size,
        )

    async def _readable_citations(self, messages: Sequence[Message]) -> set[str]:
        doc_ids: set[str] = set()
        ko_ids: set[str] = set()
        for m in messages:
            for c in m.citations or []:
                (ko_ids if c.get("is_ko") else doc_ids).add(str(c.get("document_id")))
        readable = set(await self.access.readable_documents(self.ctx.user, sorted(doc_ids)))
        if ko_ids:
            live = await KoAccess(self.session).live_objects(self.ctx.user, sorted(ko_ids))
            readable |= set(live.objects)
        return readable

    async def _conversation(self, gap: KnowledgeGap) -> list[ConversationMessageOut]:
        if not gap.conversation_id:
            return []
        messages = await ConversationRepository(self.session).messages(gap.conversation_id)
        messages = [m for m in messages if m.org_id == self.org_id]
        anchor = next((i for i, m in enumerate(messages) if m.id == gap.message_id), None)
        if anchor is not None:
            messages = messages[max(0, anchor + 1 - CONVERSATION_CONTEXT_MESSAGES) : anchor + 1]
        else:
            messages = messages[-CONVERSATION_CONTEXT_MESSAGES:]
        readable = await self._readable_citations(messages)
        out = []
        for m in messages:
            cited = {str(c.get("document_id")) for c in m.citations or []}
            redacted = m.role == MessageRole.ASSISTANT.value and not cited <= readable
            out.append(
                ConversationMessageOut(
                    id=m.id,
                    role=m.role,
                    content=REDACTED_ANSWER if redacted else m.content,
                    grounding=m.grounding,
                    citations=[] if redacted else list(m.citations or []),
                    created_at=m.created_at,
                    redacted=redacted,
                    is_gap_message=m.id == gap.message_id,
                )
            )
        return out

    async def _trace(self, gap: KnowledgeGap) -> dict[str, Any] | None:
        if not gap.trace_id:
            return None
        trace = await ConversationRepository(self.session).qa_trace(self.org_id, gap.trace_id)
        if trace is None:
            return None
        steps = copy.deepcopy(trace.steps or {})
        materials = (steps.get("prompt") or {}).get("materials") or []
        doc_ids = {str(m.get("document_id")) for m in materials}
        readable = set(await self.access.readable_documents(self.ctx.user, sorted(doc_ids)))
        ko_ids = doc_ids - readable
        if ko_ids:
            live = await KoAccess(self.session).live_objects(self.ctx.user, sorted(ko_ids))
            readable |= set(live.objects)
        for m in materials:
            if str(m.get("document_id")) not in readable:
                m["content"] = None
                m["title"] = None
                m["redacted"] = True
        return {
            "id": trace.id,
            "query": trace.query,
            "rewritten_query": trace.rewritten_query,
            "intent": trace.intent,
            "grounding": trace.grounding,
            "status": trace.status,
            "retrieval_trace_ids": list(trace.retrieval_trace_ids or []),
            "steps": steps,
            "timings": dict(trace.timings or {}),
            "total_ms": trace.total_ms,
            "created_at": trace.created_at,
        }

    async def detail(self, gap_id: str) -> GapDetailOut:
        gap = await self._gap(gap_id, AclPermission.READ)
        (base,) = await self._outs([gap])
        cluster = None
        similar: list[GapOut] = []
        if gap.cluster_id:
            found = await GapClusterRepository(self.session).get(self.org_id, gap.cluster_id)
            cluster = GapClusterOut.model_validate(found) if found else None
            members = [
                g
                for g in await self.repo.cluster_members(self.org_id, gap.cluster_id)
                if g.id != gap.id
            ]
            similar = await self._outs(members[:50])
        ko_ids = [str(i) for i in [(gap.resolution or {}).get("ko_id")] if i]
        stmt = select(KnowledgeObject).where(
            KnowledgeObject.org_id == self.org_id,
            KnowledgeObject.id.in_(ko_ids) if ko_ids else KnowledgeObject.id.is_(None),
        )
        kos = list((await self.session.execute(stmt)).scalars())
        return GapDetailOut(
            **base.model_dump(),
            conversation=await self._conversation(gap),
            qa_trace=await self._trace(gap),
            cluster=cluster,
            similar=similar,
            knowledge_objects=[
                GapKoRef(
                    id=k.id, title=k.title, status=k.status, published_version=k.published_version
                )
                for k in kos
            ],
        )

    # ---- actions -----------------------------------------------------------------------

    async def _record(self, action: str, gap: KnowledgeGap, before: dict[str, Any]) -> None:
        await self.audit.record(
            self.audit_ctx, action, RESOURCE_GAP, gap.id, before, _gap_snapshot(gap)
        )

    async def _close(
        self, gap: KnowledgeGap, status: GapStatus, resolution: dict[str, Any]
    ) -> list[KnowledgeGap]:
        """Close a gap and the duplicates folded into it."""
        now = utcnow()
        closed = [gap, *await self.repo.duplicates_of(self.org_id, [gap.id])]
        for g in closed:
            if g is gap:
                g.status = status.value
            g.resolution = resolution
            g.resolved_by = self.ctx.user.id
            g.resolved_at = now
        await refresh_cluster_stats(self.session, gap.cluster_id)
        return closed

    def _require_active(self, gap: KnowledgeGap) -> None:
        if gap.status not in ACTIVE_GAP_STATUSES:
            raise ConflictError("该缺口已处理")

    async def patch(self, gap_id: str, data: GapPatch) -> GapOut:
        gap = await self._gap(gap_id)
        before = _gap_snapshot(gap)
        fields = data.model_fields_set
        if "kb_id" in fields and data.kb_id != gap.kb_id:
            if data.kb_id is not None:
                kb = await KnowledgeBaseRepository(self.session).get(self.org_id, data.kb_id)
                if kb is None:
                    raise NotFoundError("Knowledge base not found")
                await self.access.require_kb(self.ctx.user, kb, AclPermission.EDIT)
            old_cluster = gap.cluster_id
            gap.kb_id = data.kb_id
            # Clusters are per knowledge base: cluster again on the next run.
            gap.cluster_id = None
            gap.query_hash = None
            await refresh_cluster_stats(self.session, old_cluster)
        if "assignee_id" in fields and data.assignee_id != gap.assignee_id:
            if data.assignee_id is not None:
                user = await self.session.get(User, data.assignee_id)
                if user is None or user.org_id != self.org_id:
                    raise ValidationAppError(
                        "负责人不存在", detail={"assignee_id": data.assignee_id}
                    )
            gap.assignee_id = data.assignee_id
            if data.assignee_id and gap.status == GapStatus.OPEN.value:
                gap.status = GapStatus.IN_REVIEW.value
            if data.assignee_id and data.assignee_id != self.ctx.user.id:
                await notify(
                    self.session,
                    self.org_id,
                    [data.assignee_id],
                    kind=NotificationKind.GAP_ASSIGNED,
                    title=f"你被指派处理知识缺口：{gap.query[:80]}",
                    resource_type=RESOURCE_GAP,
                    resource_id=gap.id,
                    link=f"/curation/gaps/{gap.id}",
                )
            await refresh_cluster_stats(self.session, gap.cluster_id)
        await self.session.flush()
        await self._record("gap.update", gap, before)
        (out,) = await self._outs([gap])
        return out

    async def link_documents(self, gap_id: str, data: GapLinkDocumentsIn) -> GapOut:
        """The answer exists in documents: a retrieval issue, kept for retrieval tuning."""
        gap = await self._gap(gap_id)
        self._require_active(gap)
        readable = await self.access.readable_documents(self.ctx.user, data.document_ids)
        missing = sorted(set(data.document_ids) - set(readable))
        if missing:
            raise ValidationAppError("指定的文档不存在或无权访问", detail={"document_ids": missing})
        before = _gap_snapshot(gap)
        await self._close(
            gap,
            GapStatus.RESOLVED,
            {
                "action": "retrieval_issue",
                "document_ids": data.document_ids,
                "documents": [{"id": d, "title": readable[d][0].title} for d in data.document_ids],
                "note": data.note,
                "query": gap.rewritten_query or gap.query,
                "trace_id": gap.trace_id,
            },
        )
        await self.session.flush()
        await self._record("gap.retrieval_issue", gap, before)
        (out,) = await self._outs([gap])
        return out

    async def reject(self, gap_id: str, note: str | None) -> GapOut:
        gap = await self._gap(gap_id)
        self._require_active(gap)
        before = _gap_snapshot(gap)
        await self._close(gap, GapStatus.REJECTED, {"action": "rejected", "note": note})
        await self.session.flush()
        await self._record("gap.reject", gap, before)
        (out,) = await self._outs([gap])
        return out

    async def mark_duplicate(self, gap_id: str, data: GapDuplicateIn) -> GapOut:
        gap = await self._gap(gap_id)
        self._require_active(gap)
        target = await self._gap(data.duplicate_of_id, AclPermission.READ)
        seen = {gap.id}
        while target.status == GapStatus.DUPLICATE.value and target.duplicate_of_id:
            if target.id in seen:
                break
            seen.add(target.id)
            target = await self._gap(target.duplicate_of_id, AclPermission.READ)
        if target.id == gap.id:
            raise ValidationAppError("不能标记为自身的重复")
        before = _gap_snapshot(gap)
        for dup in await self.repo.duplicates_of(self.org_id, [gap.id]):
            dup.duplicate_of_id = target.id
        gap.status = GapStatus.DUPLICATE.value
        gap.duplicate_of_id = target.id
        gap.resolution = {"action": "duplicate", "duplicate_of_id": target.id, "note": data.note}
        gap.resolved_by = self.ctx.user.id
        gap.resolved_at = utcnow()
        target.occurrences += gap.occurrences
        await refresh_cluster_stats(self.session, gap.cluster_id)
        await refresh_cluster_stats(self.session, target.cluster_id)
        await self.session.flush()
        await self._record("gap.duplicate", gap, before)
        (out,) = await self._outs([gap])
        return out

    async def reopen(self, gap_id: str) -> GapOut:
        gap = await self._gap(gap_id)
        if gap.status in ACTIVE_GAP_STATUSES:
            raise ConflictError("该缺口未关闭")
        before = _gap_snapshot(gap)
        if gap.status == GapStatus.DUPLICATE.value and gap.duplicate_of_id:
            target = await self.repo.get(self.org_id, gap.duplicate_of_id)
            if target is not None:
                target.occurrences = max(1, target.occurrences - gap.occurrences)
                await refresh_cluster_stats(self.session, target.cluster_id)
        gap.status = GapStatus.OPEN.value
        gap.duplicate_of_id = None
        gap.resolution = {}
        gap.resolved_by = None
        gap.resolved_at = None
        await refresh_cluster_stats(self.session, gap.cluster_id)
        await self.session.flush()
        await self._record("gap.reopen", gap, before)
        (out,) = await self._outs([gap])
        return out
