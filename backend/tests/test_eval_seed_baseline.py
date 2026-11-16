"""Title-keyed eval dataset seeding."""

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, EvalCase, KnowledgeBase
from app.services.authz.acl import AclPermission
from app.services.evaluation.seed_baseline import _norm_title, seed_dataset_from_jsonl
from tests.factories import make_org


def test_norm_title_collapses_nbsp() -> None:
    assert _norm_title("a\u00a0b  c") == "a b c"


@pytest.mark.asyncio
async def test_seed_dataset_resolves_titles(session: AsyncSession, tmp_path: Path) -> None:
    org = await make_org(session)
    kb = KnowledgeBase(
        org_id=org.id,
        name="eval-seed-kb",
        description=None,
        visibility="org",
        watermark=False,
        copy_protect=False,
        download_permission=AclPermission.READ.value,
    )
    session.add(kb)
    await session.flush()
    doc = Document(
        org_id=org.id,
        kb_id=kb.id,
        title="机房设备巡检制度",
        filename="room.pdf",
        mime_type="application/pdf",
        size_bytes=1,
        sha256="b" * 64,
        minio_key="k/room.pdf",
        tags=[],
        meta={},
    )
    session.add(doc)
    await session.flush()

    path = tmp_path / "cases.jsonl"
    path.write_text(
        (
            '{"id":"a1","kind":"answerable","question":"机房几点巡检？",'
            '"reference_answer":"上午九点",'
            '"expected_document_titles":["机房设备巡检制度"],"tags":["t"]}\n'
            '{"id":"o1","kind":"ood","question":"食堂几点开饭？",'
            '"reference_answer":"应拒答",'
            '"expected_document_titles":[],"tags":["n"]}\n'
        ),
        encoding="utf-8",
    )
    result = await seed_dataset_from_jsonl(
        session,
        org_id=org.id,
        name="seed-test-ds",
        cases_path=path,
        description="unit",
    )
    assert result["created_cases"] == 2
    cases = (
        await session.execute(select(EvalCase).where(EvalCase.dataset_id == result["dataset_id"]))
    ).scalars().all()
    by_q = {c.question: c for c in cases}
    assert by_q["机房几点巡检？"].expected_document_ids == [doc.id]
    assert by_q["食堂几点开饭？"].expected_document_ids == []
