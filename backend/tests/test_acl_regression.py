"""ACL regression suite (run in CI with `pytest -m acl`): every way to reach document content
must respect document/KB permissions and organization boundaries, and must be audited."""

from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.core.db import create_session_factory
from app.models import AuditLog
from tests.conftest import auth
from tests.test_chat_api import answerable, ask, corpus, new_conversation
from tests.test_indexing import pipeline

__all__ = ["answerable", "corpus", "pipeline"]

pytestmark = pytest.mark.acl

ALICE, BOB, CAROL = auth("alice-token"), auth("bob-token"), auth("carol-token")
DAVE = auth("other-org-token")


async def audit_actions(engine: AsyncEngine, resource_id: str) -> list[tuple[str, Any]]:
    async with create_session_factory(engine)() as session:
        rows = (
            await session.execute(
                select(AuditLog.action, AuditLog.after)
                .where(AuditLog.resource_id == resource_id)
                .order_by(AuditLog.created_at)
            )
        ).all()
    return [(a, after) for a, after in rows]


async def test_preview_and_download_respect_acl_and_are_audited(
    api: httpx.AsyncClient, corpus: dict[str, Any], engine: AsyncEngine
) -> None:
    secret = corpus["secret"]["id"]
    for path in ("preview-url", "download-url"):
        url = f"/api/v1/documents/{secret}/{path}"
        assert (await api.get(url, headers=CAROL)).status_code in (403, 404)
        assert (await api.get(url, headers=DAVE)).status_code in (403, 404)
        ok = await api.get(url, headers=ALICE)
        assert ok.status_code == 200, ok.text
    download = (await api.get(f"/api/v1/documents/{secret}/download-url", headers=ALICE)).json()
    assert "op=download" in download["url"]

    actions = [a for a, _ in await audit_actions(engine, secret)]
    assert "document.preview" in actions and "document.download" in actions


async def test_chat_audit_lists_question_and_documents_used(
    api: httpx.AsyncClient, corpus: dict[str, Any], answerable: Settings, engine: AsyncEngine
) -> None:
    conv = await new_conversation(api, CAROL)
    done = (await ask(api, CAROL, conv["id"], "飞织鞋面机密配方 FX-9001 的工艺参数"))["done"]
    ((action, after),) = await audit_actions(engine, done["message_id"])
    assert action == "chat.ask"
    assert after["question"] == "飞织鞋面机密配方 FX-9001 的工艺参数"
    # Carol cannot read the secret knowledge base: it was never part of the context.
    assert corpus["secret"]["id"] not in after["context_document_ids"]
    assert set(after["cited_document_ids"]) <= set(after["context_document_ids"])


async def test_analytics_is_scoped_to_the_callers_org(
    api: httpx.AsyncClient, corpus: dict[str, Any]
) -> None:
    demo_org = (await api.get("/api/v1/analytics/filters", headers=ALICE)).json()["org_id"]
    resp = await api.get("/api/v1/analytics/overview", params={"org_id": demo_org}, headers=DAVE)
    assert resp.status_code in (403, 404)
    own = await api.get("/api/v1/analytics/content", headers=DAVE)
    if own.status_code == 200:
        assert own.json()["documents"] == 0


async def test_evaluation_data_is_scoped_to_the_org(
    api: httpx.AsyncClient, corpus: dict[str, Any]
) -> None:
    ds = await api.post("/api/v1/evaluation/datasets", json={"name": "私有集"}, headers=ALICE)
    assert ds.status_code == 201
    other = await api.get(f"/api/v1/evaluation/datasets/{ds.json()['id']}", headers=DAVE)
    assert other.status_code in (403, 404)
    listing = await api.get("/api/v1/evaluation/datasets", headers=DAVE)
    if listing.status_code == 200:
        assert listing.json()["total"] == 0
    candidates = await api.get(
        "/api/v1/evaluation/candidates", params={"source": "feedback"}, headers=DAVE
    )
    if candidates.status_code == 200:
        assert candidates.json()["total"] == 0
