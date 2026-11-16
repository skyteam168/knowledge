"""Seed an eval dataset from JSONL cases keyed by document titles."""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, EvalCase, EvalCaseSource, EvalDataset, EvalRun


def _norm_title(value: str) -> str:
    """Collapse whitespace / NBSP so fixture titles match live document titles."""
    text = unicodedata.normalize("NFKC", value or "")
    text = text.replace("\u00a0", " ").replace("\u3000", " ")
    return re.sub(r"\s+", " ", text).strip()


def load_title_cases(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rows.append(json.loads(line))
    if not rows:
        raise ValueError(f"{path}: empty")
    return rows


async def resolve_title_map(session: AsyncSession, org_id: str) -> dict[str, str]:
    """normalized title -> document id (first match wins)."""
    rows = (
        await session.execute(
            select(Document.id, Document.title).where(
                Document.org_id == org_id, Document.deleted_at.is_(None)
            )
        )
    ).all()
    out: dict[str, str] = {}
    for doc_id, title in rows:
        key = _norm_title(str(title))
        if key and key not in out:
            out[key] = str(doc_id)
    return out


async def seed_dataset_from_jsonl(
    session: AsyncSession,
    *,
    org_id: str,
    name: str,
    cases_path: Path,
    description: str | None = None,
    replace: bool = False,
    created_by: str | None = None,
) -> dict[str, object]:
    cases = load_title_cases(cases_path)
    titles = await resolve_title_map(session, org_id)

    missing: set[str] = set()
    prepared: list[tuple[dict[str, object], list[str]]] = []
    for row in cases:
        wanted = [str(t) for t in (row.get("expected_document_titles") or [])]
        resolved: list[str] = []
        for title in wanted:
            doc_id = titles.get(_norm_title(title))
            if doc_id is None:
                missing.add(title)
            else:
                resolved.append(doc_id)
        prepared.append((row, resolved))
    if missing:
        raise ValueError(
            "unresolved document titles:\n- " + "\n- ".join(sorted(missing))
        )

    existing = await session.scalar(
        select(EvalDataset).where(EvalDataset.org_id == org_id, EvalDataset.name == name)
    )
    if existing is not None:
        if not replace:
            raise ValueError(f"dataset already exists: {name} ({existing.id})")
        running = await session.scalar(
            select(func.count()).where(
                EvalRun.dataset_id == existing.id,
                EvalRun.status.in_(("pending", "running")),
            )
        )
        if running:
            raise ValueError("dataset has runs in progress; wait or cancel them first")
        await session.execute(delete(EvalCase).where(EvalCase.dataset_id == existing.id))
        ds = existing
        ds.description = description
    else:
        ds = EvalDataset(
            org_id=org_id,
            name=name,
            description=description,
            created_by=created_by,
        )
        session.add(ds)
        await session.flush()

    created = 0
    for row, doc_ids in prepared:
        question = str(row.get("question") or "").strip()
        if not question:
            continue
        tags = [str(t) for t in (row.get("tags") or [])]
        case_id = str(row.get("id") or "")
        if case_id and case_id not in tags:
            tags = [*tags, case_id]
        session.add(
            EvalCase(
                org_id=org_id,
                dataset_id=ds.id,
                question=question[:2000],
                reference_answer=(
                    None
                    if row.get("reference_answer") is None
                    else str(row.get("reference_answer"))[:20000]
                ),
                expected_document_ids=doc_ids,
                expected_chunk_ids=[],
                kb_ids=[],
                tags=tags[:20],
                source=EvalCaseSource.MANUAL.value,
                created_by=created_by,
            )
        )
        created += 1
    await session.flush()
    return {
        "dataset_id": ds.id,
        "name": ds.name,
        "created_cases": created,
        "replaced": bool(existing is not None and replace),
    }
