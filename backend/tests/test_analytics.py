"""Analytics: summary aggregation from traces/feedback/gaps and the dashboard API."""

from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.core.db import create_session_factory
from app.models import AnalyticsDaily, GapStatus, GapType, KnowledgeGap, User
from app.models.base import utcnow
from app.services.analytics.aggregator import AnalyticsAggregator
from app.services.analytics.latency import hist_percentile, merge, percentile, summarize
from tests.conftest import auth
from tests.test_chat_api import answerable, ask, corpus, new_conversation
from tests.test_indexing import pipeline

__all__ = ["answerable", "corpus", "pipeline"]

ALICE, BOB, CAROL = auth("alice-token"), auth("bob-token"), auth("carol-token")
BASE = "/api/v1/analytics"


def test_latency_percentiles_and_merge() -> None:
    assert percentile([], 0.5) is None
    assert percentile([10, 20, 30, 40], 0.5) == 25
    day1 = summarize([100.0] * 9 + [1000.0])
    assert day1["count"] == 10 and day1["p50"] == 100.0
    # A single non-empty day keeps its exact percentiles.
    assert merge([day1, summarize([])])["p95"] == day1["p95"]
    both = merge([day1, summarize([200.0] * 10)])
    assert both["count"] == 20 and both["avg"] == pytest.approx(195.0)
    assert both["p50"] is not None and 100 <= both["p50"] <= 250
    assert hist_percentile([], 0.5) is None


async def test_dashboard_aggregates_usage_quality_latency_and_content(
    api: httpx.AsyncClient,
    corpus: dict[str, Any],
    answerable: Settings,
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public_kb = corpus["public_kb"]["id"]
    conv = await new_conversation(api, CAROL, kb_ids=[public_kb])
    first = await ask(api, CAROL, conv["id"], "年假有几天？")
    await ask(api, CAROL, conv["id"], "年假有几天？")
    other = await new_conversation(api, BOB)
    await ask(api, BOB, other["id"], "差旅住宿标准是多少？")
    up = await api.post(
        f"/api/v1/chat/messages/{first['done']['message_id']}/feedback",
        json={"rating": "up"},
        headers=CAROL,
    )
    assert up.status_code == 200
    async with create_session_factory(engine)() as session:
        alice = (await session.execute(select(User).where(User.username == "alice"))).scalar_one()
        session.add(
            KnowledgeGap(
                org_id=alice.org_id,
                gap_type=GapType.USER_REQUEST.value,
                status=GapStatus.RESOLVED.value,
                query="病假怎么请",
                kb_id=public_kb,
                resolved_at=utcnow(),
            )
        )
        await session.commit()

    settings = answerable
    aggregator = AnalyticsAggregator(create_session_factory(engine), settings)
    result = await aggregator.run_once(days=1)
    assert result.rows > 0
    # Idempotent per org-day.
    await aggregator.run_once(days=1)
    async with create_session_factory(engine)() as session:
        rows = await session.scalar(
            select(func.count()).where(AnalyticsDaily.kb_id == "*").select_from(AnalyticsDaily)
        )
        assert rows == 1

    resp = await api.get(f"{BASE}/overview", headers=ALICE)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["usage"]["questions"] == 3 and body["usage"]["active_users_peak"] == 2
    quality = body["quality"]
    assert quality["feedback_up"] == 1 and quality["like_rate"] == 1.0
    assert quality["gaps_new"] == 1 and quality["gaps_resolved"] == 1
    assert quality["avg_citations"] and quality["avg_citations"] > 0
    stages = {s["stage"]: s for s in body["latency"]}
    assert set(stages) == {"retrieval", "rerank", "first_token", "total"}
    assert stages["total"]["count"] == 3 and stages["total"]["p95"] >= stages["total"]["p50"]
    assert body["daily"][-1]["questions"] == 3
    top = body["top_questions"][0]
    assert top["query"] == "年假有几天？" and top["count"] == 2
    heat = {k["kb_id"]: k for k in body["kb_heat"]}
    assert heat[public_kb]["questions"] >= 2 and heat[public_kb]["kb_name"] == "人事制度"

    scoped = (await api.get(f"{BASE}/overview", params={"kb_id": public_kb}, headers=ALICE)).json()
    assert scoped["kb_heat"] == [] and 2 <= scoped["usage"]["questions"] <= 3

    filters = (await api.get(f"{BASE}/filters", headers=ALICE)).json()
    assert public_kb in {k["id"] for k in filters["kbs"]}

    monkeypatch.setattr(settings, "analytics_zombie_days", 0)
    content = (await api.get(f"{BASE}/content", headers=ALICE)).json()
    assert content["documents"] == 3 and content["chunks"] > 0
    assert {s["status"]: s["count"] for s in content["document_status"]} == {"indexed": 3}
    cited = {c["document_id"] for c in first["citations"]["citations"]}
    zombies = {d["id"] for d in content["zombie_documents"]}
    assert cited and not cited & zombies
    assert content["index"]["outbox_dead"] == 0


async def test_analytics_requires_permission(api: httpx.AsyncClient) -> None:
    assert (await api.get(f"{BASE}/overview", headers=CAROL)).status_code == 403
