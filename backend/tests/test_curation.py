"""Stage 6: the knowledge loop — gap → review → knowledge object → re-index → answered."""

from datetime import timedelta
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.core.db import create_session_factory
from app.models import KnowledgeObject
from app.models.base import utcnow
from app.services.curation.expiry import ExpiryMonitor
from app.services.indexing.runtime import IndexingRuntime
from tests.conftest import auth
from tests.test_chat_api import ScriptedChat, ask, chat, corpus, gaps, new_conversation
from tests.test_indexing import drain, me, pipeline

__all__ = ["chat", "corpus", "pipeline"]

ALICE, BOB, CAROL = auth("alice-token"), auth("bob-token"), auth("carol-token")
CURATION = "/api/v1/curation"
QUESTION = "公司食堂周五供应什么菜？"
ANSWER = "每周五公司食堂供应红烧肉和清蒸鲈鱼。"


async def _ok(resp: httpx.Response, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json()


async def publish_ko(
    api: httpx.AsyncClient, indexing: IndexingRuntime, ko_id: str
) -> dict[str, Any]:
    submitted = await _ok(await api.post(f"{CURATION}/kos/{ko_id}/submit", json={}, headers=BOB))
    assert submitted["status"] == "pending_review" and submitted["pending_review"]
    approved = await _ok(
        await api.post(
            f"{CURATION}/kos/{ko_id}/review",
            json={"decision": "approve", "comment": "内容准确"},
            headers=ALICE,
        )
    )
    assert approved["status"] == "published"
    assert set(await drain(indexing)) == {"done"}
    return dict(approved)


async def test_closed_loop_unanswered_question_becomes_published_ko(
    api: httpx.AsyncClient,
    corpus: dict[str, Any],
    chat: ScriptedChat,
    indexing: IndexingRuntime,
    engine: AsyncEngine,
) -> None:
    kb_id = corpus["public_kb"]["id"]

    # 1. Nobody can answer: two users ask the same thing, each produces a gap.
    conv = await new_conversation(api, CAROL, kb_ids=[kb_id])
    first = (await ask(api, CAROL, conv["id"], QUESTION))["done"]
    assert first["grounding"] == "no_evidence" and first["gap_id"]
    other = await new_conversation(api, ALICE, kb_ids=[kb_id])
    second = (await ask(api, ALICE, other["id"], "公司食堂周五供应什么菜"))["done"]
    assert second["gap_id"] and second["gap_id"] != first["gap_id"]
    assert chat.streams == []

    # 2. Clustering folds the identical question into the first gap.
    assert (await api.get(f"{CURATION}/gaps", headers=CAROL)).status_code == 403
    run = await _ok(await api.post(f"{CURATION}/gap-clusters/run", headers=BOB))
    assert run == {"processed": 2, "clustered": 2, "new_clusters": 1, "folded": 1}
    listing = await _ok(
        await api.get(f"{CURATION}/gaps", params={"status": ["open", "in_review"]}, headers=BOB)
    )
    (gap,) = listing["items"]
    assert gap["id"] == first["gap_id"] and gap["status"] == "open"
    assert gap["occurrences"] == 2 and gap["kb_id"] == kb_id and gap["cluster_occurrences"] == 2
    stats = await _ok(await api.get(f"{CURATION}/gaps/stats", headers=BOB))
    assert stats["by_status"]["open"] == 1 and stats["by_status"]["duplicate"] == 1

    detail = await _ok(await api.get(f"{CURATION}/gaps/{gap['id']}", headers=BOB))
    assert [m["role"] for m in detail["conversation"]] == ["user", "assistant"]
    assert detail["qa_trace"] and detail["qa_trace"]["steps"]["evidence"]["verdict"] == "refuse"

    # 3. The reviewer asks the compiler for a draft from their own material, then edits it.
    draft = await _ok(
        await api.post(f"{CURATION}/gaps/{gap['id']}/draft", json={"notes": ANSWER}, headers=BOB),
        201,
    )
    assert draft["status"] == "draft" and draft["gap_ids"] == [gap["id"]]
    assert draft["ai_draft"]["method"] == "llm" and "红烧肉" in draft["answer"]
    assert draft["question"] == QUESTION
    ko_id = draft["id"]
    edited = await _ok(
        await api.put(
            f"{CURATION}/kos/{ko_id}",
            json={
                "title": "周五食堂菜单",
                "question": QUESTION,
                "variants": ["周五食堂吃什么"],
                "answer": ANSWER,
            },
            headers=BOB,
        )
    )
    assert edited["answer"] == ANSWER and edited["variants"] == ["周五食堂吃什么"]

    # 4. Review: the author cannot approve; an approver publishes.
    await _ok(await api.post(f"{CURATION}/kos/{ko_id}/submit", json={}, headers=BOB))
    denied = await api.post(
        f"{CURATION}/kos/{ko_id}/review", json={"decision": "approve"}, headers=BOB
    )
    assert denied.status_code == 403
    published = await _ok(
        await api.post(
            f"{CURATION}/kos/{ko_id}/review", json={"decision": "approve"}, headers=ALICE
        )
    )
    assert published["status"] == "published" and published["published_version"] == 1
    assert set(await drain(indexing)) == {"done"}

    resolved = await _ok(await api.get(f"{CURATION}/gaps/{gap['id']}", headers=BOB))
    assert resolved["status"] == "resolved" and resolved["resolution"]["ko_id"] == ko_id
    all_gaps = {g.id: g for g in await gaps(engine)}
    folded = all_gaps[second["gap_id"]]
    assert folded.status == "duplicate" and folded.resolution["ko_id"] == ko_id

    # 5. A similar question now hits the knowledge object and cites it.
    chat.answer = "每周五食堂供应红烧肉和清蒸鲈鱼[1]。"
    again = await new_conversation(api, CAROL)
    result = await ask(api, CAROL, again["id"], "周五公司食堂供应什么菜？")
    done = result["done"]
    assert done["grounding"] == "grounded" and done["gap_id"] is None
    (citation,) = result["citations"]["citations"]
    assert citation["is_ko"] is True and citation["document_id"] == ko_id
    assert citation["ko_type"] == "faq" and citation["doc_version"] == 1
    assert ANSWER in "\n".join(m.content for m in chat.streams[-1])

    source = await _ok(
        await api.get(f"/api/v1/chat/messages/{done['message_id']}/citations/1", headers=CAROL)
    )
    assert source["is_ko"] is True and source["ko"]["question"] == QUESTION

    for asker in (CAROL, ALICE):
        notes = await _ok(await api.get("/api/v1/notifications", headers=asker))
        assert any(n["resource_id"] == ko_id for n in notes["items"])
    versions = await _ok(await api.get(f"{CURATION}/kos/{ko_id}/versions", headers=BOB))
    assert [(v["version"], v["status"]) for v in versions] == [(1, "published")]


async def test_deprecated_ko_is_removed_from_retrieval(
    api: httpx.AsyncClient,
    corpus: dict[str, Any],
    chat: ScriptedChat,
    indexing: IndexingRuntime,
) -> None:
    created = await _ok(
        await api.post(
            f"{CURATION}/kos",
            json={"kb_id": corpus["public_kb"]["id"], "question": QUESTION, "answer": ANSWER},
            headers=BOB,
        ),
        201,
    )
    await publish_ko(api, indexing, created["id"])
    chat.answer = "周五供应红烧肉[1]。"
    conv = await new_conversation(api, CAROL)
    hit = (await ask(api, CAROL, conv["id"], QUESTION))["citations"]["citations"]
    assert hit and hit[0]["is_ko"] and hit[0]["document_id"] == created["id"]

    deprecated = await _ok(
        await api.post(
            f"{CURATION}/kos/{created['id']}/deprecate", json={"reason": "菜单已调整"}, headers=BOB
        )
    )
    assert deprecated["status"] == "deprecated" and deprecated["published_version"] is None
    assert set(await drain(indexing)) == {"done"}
    miss = (await ask(api, CAROL, conv["id"], QUESTION))["done"]
    assert miss["grounding"] == "no_evidence"


async def test_gap_triage_and_conflict_warnings(
    api: httpx.AsyncClient,
    corpus: dict[str, Any],
    chat: ScriptedChat,
    indexing: IndexingRuntime,
) -> None:
    kb_id = corpus["public_kb"]["id"]
    conv = await new_conversation(api, CAROL, kb_ids=[kb_id])
    ids = [
        (await ask(api, CAROL, conv["id"], q))["done"]["gap_id"]
        for q in (QUESTION, "停车场晚上几点关门？", "公司班车几点发车？")
    ]
    assert all(ids)
    bob = await me(api, BOB)

    assigned = await _ok(
        await api.patch(f"{CURATION}/gaps/{ids[0]}", json={"assignee_id": bob["id"]}, headers=ALICE)
    )
    assert assigned["status"] == "in_review" and assigned["assignee"]["id"] == bob["id"]
    notes = await _ok(await api.get("/api/v1/notifications", headers=BOB))
    assert any(n["kind"] == "gap_assigned" for n in notes["items"])

    rejected = await _ok(
        await api.post(f"{CURATION}/gaps/{ids[1]}/reject", json={"note": "超出范围"}, headers=BOB)
    )
    assert rejected["status"] == "rejected"
    reopened = await _ok(await api.post(f"{CURATION}/gaps/{ids[1]}/reopen", headers=BOB))
    assert reopened["status"] == "open"
    linked = await _ok(
        await api.post(
            f"{CURATION}/gaps/{ids[2]}/link-documents",
            json={"document_ids": [corpus["leave"]["id"]], "note": "检索未命中"},
            headers=BOB,
        )
    )
    assert linked["status"] == "resolved"
    assert linked["resolution"]["action"] == "retrieval_issue"
    hidden = await api.post(
        f"{CURATION}/gaps/{ids[1]}/link-documents",
        json={"document_ids": ["0" * 32]},
        headers=BOB,
    )
    assert hidden.status_code in (404, 422)

    original = await _ok(
        await api.post(
            f"{CURATION}/kos",
            json={"kb_id": kb_id, "question": QUESTION, "answer": ANSWER},
            headers=BOB,
        ),
        201,
    )
    await publish_ko(api, indexing, original["id"])
    copy = await _ok(
        await api.post(
            f"{CURATION}/kos",
            json={"kb_id": kb_id, "question": QUESTION, "answer": ANSWER},
            headers=BOB,
        ),
        201,
    )
    checked = await _ok(await api.post(f"{CURATION}/kos/{copy['id']}/check-conflicts", headers=BOB))
    assert checked["conflicts_checked_at"]
    top = checked["conflicts"][0]
    assert top["kind"] == "ko" and top["id"] == original["id"] and top["verdict"] == "duplicate"


async def test_faq_generation_and_expiry(
    api: httpx.AsyncClient,
    corpus: dict[str, Any],
    chat: ScriptedChat,
    indexing: IndexingRuntime,
    engine: AsyncEngine,
    settings: Settings,
) -> None:
    faqs = await _ok(
        await api.post(
            f"{CURATION}/documents/{corpus['leave']['id']}/faq",
            json={"max_items": 2},
            headers=BOB,
        ),
        201,
    )
    assert 1 <= len(faqs) <= 2 and all(k["status"] == "draft" for k in faqs)
    assert all(k["origin"] == "document" for k in faqs)
    detail = await _ok(await api.get(f"{CURATION}/kos/{faqs[0]['id']}", headers=BOB))
    assert detail["sources"] and detail["sources"][0]["document_id"] == corpus["leave"]["id"]
    carol = await api.post(f"{CURATION}/documents/{corpus['leave']['id']}/faq", headers=CAROL)
    assert carol.status_code == 403

    now = utcnow()
    soon = await _ok(
        await api.post(
            f"{CURATION}/kos",
            json={
                "kb_id": corpus["public_kb"]["id"],
                "question": QUESTION,
                "answer": ANSWER,
                "effective_to": (now + timedelta(days=2)).isoformat(),
            },
            headers=BOB,
        ),
        201,
    )
    await publish_ko(api, indexing, soon["id"])
    monitor = ExpiryMonitor(create_session_factory(engine), settings)
    reminded = await monitor.run_once(now)
    assert reminded.ko_reminders == 1 and reminded.deprecated == 0
    assert (await monitor.run_once(now)).ko_reminders == 0
    notes = await _ok(await api.get("/api/v1/notifications", headers=BOB))
    assert any(n["kind"] == "ko_expiring" for n in notes["items"])

    expired = await monitor.run_once(now + timedelta(days=3))
    assert expired.deprecated == 1
    async with create_session_factory(engine)() as session:
        ko = await session.get(KnowledgeObject, soon["id"])
        assert ko is not None and ko.status == "deprecated"
    assert set(await drain(indexing)) == {"done"}
