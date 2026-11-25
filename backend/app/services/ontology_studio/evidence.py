"""Semantic evidence helpers (title resolution + ACL-safe summaries)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chunk, Document, KnowledgeBase, KnowledgeObject
from app.models.semantic import SemanticEvidence
from app.services.authz import CurrentUser
from app.services.knowledge.access import KnowledgeAccess
from app.services.knowledge.ko_access import KoAccess


async def list_evidence_rows(
    session: AsyncSession, org_id: str, version_id: str
) -> list[SemanticEvidence]:
    rows = await session.scalars(
        select(SemanticEvidence)
        .where(
            SemanticEvidence.org_id == org_id,
            SemanticEvidence.version_id == version_id,
        )
        .order_by(SemanticEvidence.created_at)
    )
    return list(rows)


async def summarize_evidences_for_agent(
    session: AsyncSession,
    user: CurrentUser,
    org_id: str,
    evidences: list[SemanticEvidence],
    *,
    allowed_kb_ids: frozenset[str] | None = None,
) -> list[dict[str, Any]]:
    """Return id/title/kind only; drop targets the caller cannot read.

    Orphan references (target missing) are kept with title=None so published
    steward links remain discoverable without leaking document bodies.
    """
    kos = KoAccess(session)
    access = KnowledgeAccess(session)
    out: list[dict[str, Any]] = []
    for ev in evidences:
        resolved = await _resolve(
            session,
            kos,
            access,
            user,
            org_id,
            ev.evidence_kind,
            ev.evidence_id,
            allowed_kb_ids=allowed_kb_ids,
        )
        if resolved is False:
            continue
        title = resolved if isinstance(resolved, str) else None
        out.append(
            {
                "id": ev.id,
                "target_kind": ev.target_kind,
                "target_id": ev.target_id,
                "kind": ev.evidence_kind,
                "evidence_id": ev.evidence_id,
                "title": title,
                "note": (ev.note or "")[:200] or None,
            }
        )
    return out


async def _resolve(
    session: AsyncSession,
    kos: KoAccess,
    access: KnowledgeAccess,
    user: CurrentUser,
    org_id: str,
    kind: str,
    evidence_id: str,
    *,
    allowed_kb_ids: frozenset[str] | None,
) -> str | None | bool:
    """str title | None orphan | False denied."""
    if kind == "ko":
        row = await session.scalar(
            select(KnowledgeObject).where(
                KnowledgeObject.org_id == org_id,
                KnowledgeObject.id == evidence_id,
            )
        )
        if row is None:
            return None
        live = await kos.live_objects(user, [evidence_id])
        if evidence_id not in live.objects:
            return False
        if allowed_kb_ids is not None and live.objects[evidence_id].kb.id not in allowed_kb_ids:
            return False
        return (row.title or evidence_id)[:200]

    if kind == "document":
        doc = await session.scalar(
            select(Document).where(
                Document.org_id == org_id,
                Document.id == evidence_id,
            )
        )
        if doc is None:
            return None
        if allowed_kb_ids is not None and doc.kb_id not in allowed_kb_ids:
            return False
        kb = await session.scalar(
            select(KnowledgeBase).where(
                KnowledgeBase.org_id == org_id,
                KnowledgeBase.id == doc.kb_id,
            )
        )
        if kb is None:
            return False
        perm = await access.document_permission(user, doc, kb)
        if perm is None:
            return False
        return (doc.title or doc.filename or evidence_id)[:200]

    if kind == "chunk":
        chunk = await session.scalar(
            select(Chunk).where(
                Chunk.org_id == org_id,
                Chunk.id == evidence_id,
            )
        )
        if chunk is None:
            return None
        doc = await session.scalar(
            select(Document).where(
                Document.org_id == org_id,
                Document.id == chunk.document_id,
            )
        )
        if doc is None:
            return None
        if allowed_kb_ids is not None and doc.kb_id not in allowed_kb_ids:
            return False
        kb = await session.scalar(
            select(KnowledgeBase).where(
                KnowledgeBase.org_id == org_id,
                KnowledgeBase.id == doc.kb_id,
            )
        )
        if kb is None:
            return False
        perm = await access.document_permission(user, doc, kb)
        if perm is None:
            return False
        return f"chunk:{evidence_id[:8]} @ {(doc.title or doc.filename or doc.id)[:80]}"

    return False
