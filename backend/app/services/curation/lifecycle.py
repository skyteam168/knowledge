"""State transitions of knowledge objects that touch the indexes (publish / deprecate).

Both run inside the caller's transaction and write the outbox event in it, so the derived
indexes follow PG exactly once the transaction commits.
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ACTIVE_GAP_STATUSES,
    GapStatus,
    KnowledgeGap,
    KnowledgeObject,
    KoEntry,
    KoSourceRef,
    KoStatus,
    KoVersion,
    KoVersionStatus,
    ReviewStatus,
)
from app.models.base import utcnow
from app.repositories.curation_repo import (
    GapRepository,
    KnowledgeObjectRepository,
    ReviewTaskRepository,
)
from app.services.audit_service import AuditContext, AuditService
from app.services.curation.clustering import refresh_cluster_stats
from app.services.curation.common import RESOURCE_GAP, RESOURCE_KO_AUDIT
from app.services.curation.notifications import NotificationKind, notify
from app.services.indexing.ko_indexer import ko_entry_id
from app.services.knowledge.access import RESOURCE_KO
from app.services.outbox_service import KO_DEPRECATED, KO_PUBLISHED, OutboxService


def ko_link(ko_id: str) -> str:
    return f"/curation/kos/{ko_id}"


def ko_snapshot(ko: KnowledgeObject) -> dict[str, Any]:
    return {
        "status": ko.status,
        "version": ko.version,
        "published_version": ko.published_version,
        "title": ko.title,
        "question": ko.question,
        "variants": list(ko.variants or []),
        "answer_chars": len(ko.answer or ""),
        "sources": [s.get("document_id") for s in ko.sources or []],
        "effective_from": ko.effective_from.isoformat() if ko.effective_from else None,
        "effective_to": ko.effective_to.isoformat() if ko.effective_to else None,
    }


class KoLifecycle:
    def __init__(self, session: AsyncSession, audit_ctx: AuditContext) -> None:
        self.session = session
        self.audit_ctx = audit_ctx
        self.audit = AuditService(session)
        self.repo = KnowledgeObjectRepository(session)

    async def publish(
        self, ko: KnowledgeObject, snapshot: KoVersion, actor_id: str | None
    ) -> list[KnowledgeGap]:
        """Make `snapshot` the live version; returns the gaps resolved by it."""
        before = ko_snapshot(ko)
        now = utcnow()
        await self.repo.mark_versions(
            ko.id, KoVersionStatus.PUBLISHED.value, KoVersionStatus.SUPERSEDED.value
        )
        snapshot.status = KoVersionStatus.PUBLISHED.value
        snapshot.published_at = now
        snapshot.published_by = actor_id
        ko.published_version = snapshot.version
        ko.status = KoStatus.PUBLISHED.value
        ko.published_at = now
        ko.published_by = actor_id
        ko.expiry_notified_at = None

        questions = [snapshot.question, *[v for v in snapshot.variants or [] if v]]
        await self.repo.replace_entries(
            ko,
            [
                KoEntry(
                    id=ko_entry_id(ko.id, snapshot.version, seq),
                    org_id=ko.org_id,
                    ko_id=ko.id,
                    ko_version=snapshot.version,
                    seq=seq,
                    question=q,
                )
                for seq, q in enumerate(dict.fromkeys(questions))
            ],
        )
        doc_refs = {
            (s["document_id"], s.get("chunk_id"))
            for s in snapshot.sources or []
            if s.get("document_id")
        }
        await self.repo.replace_source_refs(
            ko,
            [
                KoSourceRef(org_id=ko.org_id, ko_id=ko.id, document_id=d, chunk_id=c)
                for d, c in sorted(doc_refs, key=lambda r: (r[0], r[1] or ""))
            ],
        )
        await self.session.flush()
        await OutboxService(self.session).publish(
            ko.org_id,
            RESOURCE_KO,
            ko.id,
            KO_PUBLISHED,
            {"ko_id": ko.id, "version": snapshot.version, "kb_id": ko.kb_id},
        )
        resolved = await self._resolve_gaps(ko, snapshot.version, actor_id)
        await self.audit.record(
            self.audit_ctx, "ko.publish", RESOURCE_KO_AUDIT, ko.id, before, ko_snapshot(ko)
        )
        return resolved

    async def _resolve_gaps(
        self, ko: KnowledgeObject, version: int, actor_id: str | None
    ) -> list[KnowledgeGap]:
        repo = GapRepository(self.session)
        gaps = await repo.many(ko.org_id, list(ko.gap_ids or []))
        gaps += await repo.duplicates_of(ko.org_id, [g.id for g in gaps])
        now = utcnow()
        resolved: list[KnowledgeGap] = []
        askers: set[str] = set()
        for gap in gaps:
            if gap.status not in (*ACTIVE_GAP_STATUSES, GapStatus.DUPLICATE.value):
                continue
            if gap.user_id:
                askers.add(gap.user_id)
            if gap.status != GapStatus.DUPLICATE.value:
                resolved.append(gap)
                gap.status = GapStatus.RESOLVED.value
            gap.resolution = {
                **(gap.resolution or {}),
                "action": "ko",
                "ko_id": ko.id,
                "version": version,
            }
            gap.resolved_by = actor_id
            gap.resolved_at = now
            await self.audit.record(
                self.audit_ctx,
                "gap.resolve",
                RESOURCE_GAP,
                gap.id,
                None,
                {"status": gap.status, "ko_id": ko.id, "version": version},
            )
        for cluster_id in sorted({g.cluster_id for g in gaps if g.cluster_id}):
            await refresh_cluster_stats(self.session, cluster_id)
        for user_id in sorted(askers):
            await notify(
                self.session,
                ko.org_id,
                [user_id],
                kind=NotificationKind.GAP_RESOLVED,
                title=f"你提出的问题已补充答案：{ko.question[:80]}",
                body="知识库已发布相关知识条目，再次提问即可获得回答。",
                resource_type=RESOURCE_KO,
                resource_id=ko.id,
                dedupe_key=f"gap-resolved:{ko.id}:{version}",
            )
        return resolved

    async def deprecate(
        self, ko: KnowledgeObject, actor_id: str | None, reason: str | None
    ) -> None:
        if ko.status == KoStatus.DEPRECATED.value:
            return
        before = ko_snapshot(ko)
        was_live = ko.published_version is not None
        await self.repo.mark_versions(
            ko.id, KoVersionStatus.PUBLISHED.value, KoVersionStatus.DEPRECATED.value
        )
        await self.repo.mark_versions(
            ko.id, KoVersionStatus.PENDING_REVIEW.value, KoVersionStatus.WITHDRAWN.value
        )
        task = await ReviewTaskRepository(self.session).pending_for(ko.id)
        if task is not None:
            task.status = ReviewStatus.CANCELLED.value
            task.decided_at = utcnow()
            task.comment = reason
        ko.status = KoStatus.DEPRECATED.value
        ko.published_version = None
        ko.updated_by = actor_id
        await self.repo.clear_index_rows(ko.id)
        if was_live:
            await OutboxService(self.session).publish(
                ko.org_id, RESOURCE_KO, ko.id, KO_DEPRECATED, {"ko_id": ko.id, "kb_id": ko.kb_id}
            )
        await self.audit.record(
            self.audit_ctx,
            "ko.deprecate",
            RESOURCE_KO_AUDIT,
            ko.id,
            before,
            {**ko_snapshot(ko), "reason": reason},
        )
        await notify(
            self.session,
            ko.org_id,
            [ko.owner_id or ko.created_by],
            kind=NotificationKind.KO_DEPRECATED,
            title=f"知识条目已下线：{ko.title[:80]}",
            body=reason,
            resource_type=RESOURCE_KO,
            resource_id=ko.id,
            link=ko_link(ko.id),
        )
