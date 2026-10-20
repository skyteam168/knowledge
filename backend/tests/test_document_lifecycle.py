"""Document business lifecycle, effective window filtering, and classification export."""

import hashlib
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.db import create_session_factory
from app.models import Chunk, Document, DocumentLifecycle, KnowledgeBase
from app.models.base import new_id, utcnow
from app.repositories.indexing_repo import INDEXED_CHUNK_LEVEL
from app.services.authz.context import CurrentUser
from app.services.authz.principals import Principals
from app.services.knowledge.document_effect import in_effect, lifecycle_retrievable
from app.services.search.hydrator import PassageHydrator
from tests.conftest import auth
from tests.test_indexing import BOB, create_kb

CAROL = auth("carol-token")
DOCS = "/api/v1/documents"
KBS = "/api/v1/knowledge-bases"


def test_in_effect_respects_lifecycle_and_window() -> None:
    now = datetime(2026, 6, 1, tzinfo=UTC)
    doc = Document(
        lifecycle_status=DocumentLifecycle.PUBLISHED.value,
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
        effective_to=datetime(2026, 12, 31, tzinfo=UTC),
    )
    assert lifecycle_retrievable(doc) and in_effect(doc, now)
    doc.lifecycle_status = DocumentLifecycle.DRAFT.value
    assert not lifecycle_retrievable(doc) and not in_effect(doc, now)
    doc.lifecycle_status = DocumentLifecycle.PUBLISHED.value
    doc.effective_to = datetime(2026, 5, 1, tzinfo=UTC)
    assert not in_effect(doc, now)
    doc.effective_to = None
    doc.effective_from = datetime(2026, 7, 1, tzinfo=UTC)
    assert not in_effect(doc, now)


@pytest.mark.asyncio
async def test_lifecycle_transitions_and_permissions(
    api: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    kb = await create_kb(api, name="Lifecycle KB")
    created = await api.post(
        f"{KBS}/{kb['id']}/documents/markdown",
        headers=BOB,
        json={"title": "SOP draft", "content": "# Hello\n\nbody"},
    )
    assert created.status_code == 200, created.text
    doc_id = created.json()["document"]["id"]

    async with create_session_factory(engine)() as session:
        doc = await session.get(Document, doc_id)
        assert doc is not None
        doc.lifecycle_status = DocumentLifecycle.DRAFT.value
        await session.commit()

    bad = await api.post(f"{DOCS}/{doc_id}/lifecycle", headers=CAROL, json={"action": "submit"})
    assert bad.status_code in {403, 404}

    submit = await api.post(
        f"{DOCS}/{doc_id}/lifecycle", headers=BOB, json={"action": "submit"}
    )
    assert submit.status_code == 200, submit.text
    assert submit.json()["lifecycle_status"] == "in_review"

    deny = await api.post(f"{DOCS}/{doc_id}/lifecycle", headers=CAROL, json={"action": "approve"})
    assert deny.status_code in {403, 404}

    approve = await api.post(
        f"{DOCS}/{doc_id}/lifecycle", headers=BOB, json={"action": "approve"}
    )
    assert approve.status_code == 200, approve.text
    assert approve.json()["lifecycle_status"] == "published"

    retire = await api.post(
        f"{DOCS}/{doc_id}/lifecycle",
        headers=BOB,
        json={"action": "retire", "reason": "superseded"},
    )
    assert retire.status_code == 200
    assert retire.json()["lifecycle_status"] == "retired"


def _chunk(org_id: str, kb_id: str, doc_id: str, text: str) -> Chunk:
    return Chunk(
        id=new_id(),
        org_id=org_id,
        kb_id=kb_id,
        document_id=doc_id,
        document_version=1,
        seq=0,
        level=INDEXED_CHUNK_LEVEL,
        content=text,
        chunk_type="text",
        heading_path=[],
        token_count=2,
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
    )


@pytest.mark.asyncio
async def test_hydrator_drops_expired_and_draft(
    api: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    from tests.test_indexing import me

    org_id = (await me(api, BOB))["org_id"]
    async with create_session_factory(engine)() as session:
        kb = KnowledgeBase(
            id=new_id(),
            org_id=org_id,
            name=f"hyd-{new_id()[:8]}",
            visibility="org",
        )
        session.add(kb)
        await session.flush()
        expired = Document(
            id=new_id(),
            org_id=org_id,
            kb_id=kb.id,
            title="expired",
            filename="e.md",
            mime_type="text/markdown",
            size_bytes=1,
            sha256="a" * 64,
            minio_key="k/e",
            version=1,
            status="indexed",
            lifecycle_status=DocumentLifecycle.PUBLISHED.value,
            effective_to=utcnow() - timedelta(days=1),
            acl_inherit=True,
            tags=[],
            meta={},
        )
        draft = Document(
            id=new_id(),
            org_id=org_id,
            kb_id=kb.id,
            title="draft",
            filename="d.md",
            mime_type="text/markdown",
            size_bytes=1,
            sha256="b" * 64,
            minio_key="k/d",
            version=1,
            status="indexed",
            lifecycle_status=DocumentLifecycle.DRAFT.value,
            acl_inherit=True,
            tags=[],
            meta={},
        )
        live = Document(
            id=new_id(),
            org_id=org_id,
            kb_id=kb.id,
            title="live",
            filename="l.md",
            mime_type="text/markdown",
            size_bytes=1,
            sha256="c" * 64,
            minio_key="k/l",
            version=1,
            status="indexed",
            lifecycle_status=DocumentLifecycle.PUBLISHED.value,
            acl_inherit=True,
            tags=[],
            meta={},
        )
        session.add_all([expired, draft, live])
        await session.flush()
        chunks = [
            _chunk(org_id, kb.id, expired.id, "expired text"),
            _chunk(org_id, kb.id, draft.id, "draft text"),
            _chunk(org_id, kb.id, live.id, "live text"),
        ]
        session.add_all(chunks)
        await session.commit()
        chunk_ids = [c.id for c in chunks]

    user = CurrentUser(
        id="alice",
        org_id=org_id,
        username="alice",
        display_name="Alice",
        principals=Principals(org_id=org_id, user_id="alice"),
        permissions=frozenset({"*"}),
    )
    async with create_session_factory(engine)() as session:
        result = await PassageHydrator(session, user)(chunk_ids)
    assert len(result.passages) == 1
    assert list(result.passages.values())[0].content == "live text"
    assert result.dropped.get("not_in_effect", 0) == 1
    assert result.dropped.get("not_published", 0) == 1
