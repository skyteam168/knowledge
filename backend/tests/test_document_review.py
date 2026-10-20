"""Document owner and periodic review: due dates, reminders, filters and confirmation."""

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.core.db import create_session_factory
from app.models import Document, KnowledgeBase
from app.models.base import utcnow
from app.services.curation.expiry import ExpiryMonitor
from app.services.knowledge.review import refresh_due, review_interval, review_state
from tests.conftest import auth
from tests.test_indexing import BOB, create_kb, me

ALICE, CAROL = auth("alice-token"), auth("carol-token")
DOCS = "/api/v1/documents"
NOW = datetime(2026, 10, 20, tzinfo=UTC)


def test_document_interval_overrides_the_knowledge_base() -> None:
    kb = KnowledgeBase(review_interval_days=90)
    doc = Document(review_interval_days=None, reviewed_at=NOW, review_reminder=2)
    assert review_interval(kb, doc) == 90
    refresh_due(kb, doc)
    assert doc.review_due_at == NOW + timedelta(days=90) and doc.review_reminder == 0
    assert review_state(doc, NOW, 7) == "ok"
    assert review_state(doc, NOW + timedelta(days=85), 7) == "due_soon"
    assert review_state(doc, NOW + timedelta(days=90), 7) == "overdue"
    doc.review_interval_days = 0
    refresh_due(kb, doc)
    assert doc.review_due_at is None and review_state(doc, NOW, 7) == "none"
    doc.review_interval_days = 30
    refresh_due(KnowledgeBase(review_interval_days=None), doc)
    assert doc.review_due_at == NOW + timedelta(days=30)


async def _reviewed_doc(api: httpx.AsyncClient) -> tuple[dict[str, Any], dict[str, Any]]:
    carol = await me(api, CAROL)
    kb = await create_kb(api, "复核库")
    acl = {
        "visibility": "restricted",
        "entries": [
            {
                "principal_type": "user",
                "principal_id": (await me(api, BOB))["id"],
                "permission": "manage",
            },
            {"principal_type": "user", "principal_id": carol["id"], "permission": "read"},
        ],
    }
    assert (
        await api.put(f"/api/v1/knowledge-bases/{kb['id']}/acl", json=acl, headers=BOB)
    ).status_code == 200
    resp = await api.put(
        f"/api/v1/knowledge-bases/{kb['id']}", json={"review_interval_days": 90}, headers=BOB
    )
    assert resp.status_code == 200 and resp.json()["review_interval_days"] == 90
    resp = await api.post(
        f"/api/v1/knowledge-bases/{kb['id']}/documents",
        files={"file": ("规程.md", b"# rules\n\nkeep it clean", "text/markdown")},
        headers=BOB,
    )
    return dict(resp.json()["document"]), kb


async def _set_due(engine: AsyncEngine, doc_id: str, due: datetime) -> None:
    async with create_session_factory(engine)() as session:
        doc = await session.get(Document, doc_id)
        assert doc is not None
        doc.review_due_at, doc.review_reminder = due, 0
        await session.commit()


async def test_upload_starts_the_review_clock_and_owner_needs_edit(
    api: httpx.AsyncClient,
) -> None:
    doc, kb = await _reviewed_doc(api)
    assert doc["review_interval"] == 90 and doc["review_state"] == "ok"
    assert doc["reviewed_at"] and doc["review_due_at"]

    carol = await me(api, CAROL)
    denied = await api.put(f"{DOCS}/{doc['id']}", json={"owner_id": carol["id"]}, headers=BOB)
    assert denied.status_code == 422 and denied.json()["code"] == "OWNER_NO_EDIT"
    alice = await me(api, ALICE)
    resp = await api.put(f"{DOCS}/{doc['id']}", json={"owner_id": alice["id"]}, headers=BOB)
    assert resp.status_code == 200, resp.text
    assert resp.json()["owner_id"] == alice["id"] and resp.json()["owner_name"]

    off = await api.put(f"{DOCS}/{doc['id']}", json={"review_interval_days": 0}, headers=BOB)
    assert off.json()["review_state"] == "none" and off.json()["review_due_at"] is None
    back = await api.put(f"{DOCS}/{doc['id']}", json={"review_interval_days": None}, headers=BOB)
    assert back.json()["review_interval"] == 90

    resp = await api.put(
        f"/api/v1/knowledge-bases/{kb['id']}", json={"review_interval_days": None}, headers=BOB
    )
    assert resp.status_code == 200
    detail = (await api.get(f"{DOCS}/{doc['id']}", headers=BOB)).json()
    assert detail["review_due_at"] is None and detail["owner_name"]


async def test_owners_are_reminded_once_per_stage_and_review_resets(
    api: httpx.AsyncClient, engine: AsyncEngine, settings: Settings
) -> None:
    doc, kb = await _reviewed_doc(api)
    alice = await me(api, ALICE)
    await api.put(f"{DOCS}/{doc['id']}", json={"owner_id": alice["id"]}, headers=BOB)
    now = utcnow()
    await _set_due(engine, doc["id"], now + timedelta(days=3))
    monitor = ExpiryMonitor(create_session_factory(engine), settings)

    assert (await monitor.run_once(now)).review_reminders == 1
    assert (await monitor.run_once(now)).review_reminders == 0
    assert (await monitor.run_once(now + timedelta(days=4))).review_reminders == 1
    assert (await monitor.run_once(now + timedelta(days=5))).review_reminders == 0
    notes = (await api.get("/api/v1/notifications", headers=ALICE)).json()["items"]
    review_notes = [n for n in notes if n["kind"] == "document_review"]
    assert len(review_notes) == 2 and "逾期" in review_notes[0]["title"]
    assert review_notes[0]["link"] == f"/knowledge/{kb['id']}/documents/{doc['id']}"
    bob_notes = (await api.get("/api/v1/notifications", headers=BOB)).json()["items"]
    assert not [n for n in bob_notes if n["kind"] == "document_review"]

    await _set_due(engine, doc["id"], now - timedelta(days=1))
    url = f"/api/v1/knowledge-bases/{kb['id']}/documents"
    overdue = (await api.get(url, params={"review": "overdue"}, headers=BOB)).json()
    assert [d["id"] for d in overdue["items"]] == [doc["id"]]
    assert overdue["items"][0]["review_state"] == "overdue"
    assert (await api.get(url, params={"review": "due_soon"}, headers=BOB)).json()["total"] == 0
    mine = (await api.get(url, params={"mine": True}, headers=ALICE)).json()
    assert mine["total"] == 1
    assert (await api.get(url, params={"mine": True}, headers=BOB)).json()["total"] == 0

    assert (await api.post(f"{DOCS}/{doc['id']}/review", json={}, headers=CAROL)).status_code == 403
    resp = await api.post(f"{DOCS}/{doc['id']}/review", json={"note": "已核对"}, headers=ALICE)
    assert resp.status_code == 200, resp.text
    assert resp.json()["review_state"] == "ok"
    due = datetime.fromisoformat(resp.json()["review_due_at"])
    assert due.replace(tzinfo=due.tzinfo or UTC) > now + timedelta(days=89)
    assert (await api.get(url, params={"review": "attention"}, headers=BOB)).json()["total"] == 0
