"""Offline evaluation: datasets, one-click imports, runs with metrics + judge, comparison."""

from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.cache import MemoryCache
from app.core.config import Settings
from app.core.db import create_session_factory
from app.llm import LLMGateway
from app.models import (
    EvalCase,
    EvalDataset,
    EvalRun,
    GapStatus,
    GapType,
    KnowledgeGap,
    User,
)
from app.models.base import utcnow
from app.retrieval.backends import SearchBackends
from app.retrieval.pipeline import RetrievalPipeline
from app.services.authz import AuthzCache
from app.services.evaluation.judge import parse_verdict
from app.services.evaluation.metrics import (
    RetrievedItem,
    citation_precision,
    mean_metrics,
    ranking_metrics,
    retrieval_metrics,
)
from app.services.evaluation.runner import EvalRunner
from app.services.ingest.queue import RecordingTaskQueue
from tests.conftest import auth
from tests.test_chat_api import answerable, ask, corpus, new_conversation
from tests.test_indexing import pipeline

__all__ = ["answerable", "corpus", "pipeline"]

ALICE, CAROL = auth("alice-token"), auth("carol-token")
BASE = "/api/v1/evaluation"


# ---- metrics ------------------------------------------------------------------------------


def test_ranking_metrics() -> None:
    m = ranking_metrics(["x", "a", "y", "b", "a"], {"a", "b"}, "")
    assert m["recall@5"] == 1.0 and m["recall@10"] == 1.0
    assert m["mrr"] == 0.5
    # DCG = 1/log2(3) + 1/log2(5); IDCG = 1 + 1/log2(3)
    assert m["ndcg@10"] == pytest.approx((0.63093 + 0.43068) / 1.63093, abs=1e-4)

    miss = ranking_metrics(["x"] * 5 + ["a"], {"a", "b"}, "")
    assert miss["recall@5"] == 0.0 and miss["recall@10"] == 0.5
    assert miss["mrr"] == pytest.approx(1 / 6, abs=1e-4)


def test_retrieval_metrics_document_and_chunk_level() -> None:
    items = [RetrievedItem(1, "c1", "d1"), RetrievedItem(2, "c2", "d2")]
    m = retrieval_metrics(items, {"d2"}, {"c1"})
    assert m["mrr"] == 0.5 and m["chunk_mrr"] == 1.0
    assert "chunk_recall@5" not in retrieval_metrics(items, {"d2"}, set())
    assert retrieval_metrics(items, set(), set()) == {}
    assert citation_precision([{"document_id": "d1"}, {"document_id": "d2"}], {"d1"}) == 0.5
    assert citation_precision([], {"d1"}) is None
    assert mean_metrics([{"mrr": 1.0}, {"mrr": 0.0, "x": 1.0}]) == {"mrr": 0.5, "x": 1.0}


def test_parse_verdict_clamps_and_tolerates_noise() -> None:
    v = parse_verdict(
        '说明：{"faithfulness": 1.4, "answer_relevance": "0.5", "citation_accuracy": null}'
    )
    assert v.scores == {"faithfulness": 1.0, "answer_relevance": 0.5, "citation_accuracy": None}
    assert parse_verdict("not json").error


# ---- API + runner -------------------------------------------------------------------------


@pytest.fixture
def runner(
    engine: AsyncEngine,
    memory_cache: MemoryCache,
    search_backends: SearchBackends,
    llm_gateway: LLMGateway,
    settings: Settings,
) -> EvalRunner:
    return EvalRunner(
        session_factory=create_session_factory(engine),
        authz_cache=AuthzCache(memory_cache, settings.authz_cache_ttl_seconds),
        pipeline=RetrievalPipeline.build(search_backends, llm_gateway, memory_cache),
        gateway=llm_gateway,
        # One shared SQLite connection in tests: no concurrent sessions.
        settings=settings.model_copy(update={"eval_concurrency": 1}),
    )


async def _user(engine: AsyncEngine, username: str) -> User:
    async with create_session_factory(engine)() as session:
        return (await session.execute(select(User).where(User.username == username))).scalar_one()


async def _resolved_gap(engine: AsyncEngine, query: str, doc_id: str) -> str:
    org_id = (await _user(engine, "alice")).org_id
    async with create_session_factory(engine)() as session:
        gap = KnowledgeGap(
            org_id=org_id,
            gap_type=GapType.NO_EVIDENCE.value,
            status=GapStatus.RESOLVED.value,
            query=query,
            resolution={"action": "retrieval_issue", "document_ids": [doc_id]},
            resolved_at=utcnow(),
        )
        session.add(gap)
        await session.commit()
        return gap.id


async def test_dataset_import_run_and_compare(
    api: httpx.AsyncClient,
    corpus: dict[str, Any],
    answerable: Settings,
    engine: AsyncEngine,
    task_queue: RecordingTaskQueue,
    runner: EvalRunner,
) -> None:
    leave = corpus["leave"]
    # An upvoted answer and a resolved gap feed the dataset.
    conv = await new_conversation(api, CAROL)
    done = (await ask(api, CAROL, conv["id"], "年假有几天？"))["done"]
    up = await api.post(
        f"/api/v1/chat/messages/{done['message_id']}/feedback", json={"rating": "up"}, headers=CAROL
    )
    assert up.status_code == 200, up.text
    gap_id = await _resolved_gap(engine, "年假怎么申请", leave["id"])

    ds = await api.post(f"{BASE}/datasets", json={"name": "回归集"}, headers=ALICE)
    assert ds.status_code == 201, ds.text
    ds_id = ds.json()["id"]
    dup = await api.post(f"{BASE}/datasets", json={"name": "回归集"}, headers=ALICE)
    assert dup.status_code == 409

    fb = await api.get(
        f"{BASE}/candidates", params={"source": "feedback", "dataset_id": ds_id}, headers=ALICE
    )
    assert fb.status_code == 200, fb.text
    (candidate,) = fb.json()["items"]
    assert candidate["question"] == "年假有几天？" and not candidate["imported"]
    assert candidate["expected_document_ids"] and candidate["reference_answer"]
    imported = await api.post(
        f"{BASE}/datasets/{ds_id}/import",
        json={"source": "feedback", "source_ids": [candidate["source_id"]]},
        headers=ALICE,
    )
    assert imported.json() == {"created": 1, "skipped": 0}
    again = await api.post(
        f"{BASE}/datasets/{ds_id}/import",
        json={"source": "feedback", "source_ids": [candidate["source_id"]]},
        headers=ALICE,
    )
    assert again.json() == {"created": 0, "skipped": 1}
    gaps = await api.get(
        f"{BASE}/candidates", params={"source": "gap", "dataset_id": ds_id}, headers=ALICE
    )
    assert [g["source_id"] for g in gaps.json()["items"]] == [gap_id]
    assert gaps.json()["items"][0]["expected_document_ids"] == [leave["id"]]
    await api.post(
        f"{BASE}/datasets/{ds_id}/import",
        json={"source": "gap", "source_ids": [gap_id]},
        headers=ALICE,
    )
    manual = await api.post(
        f"{BASE}/datasets/{ds_id}/cases",
        json={"question": "机密配方的工艺参数", "expected_document_ids": [corpus["secret"]["id"]]},
        headers=ALICE,
    )
    assert manual.status_code == 201, manual.text
    cases = (await api.get(f"{BASE}/datasets/{ds_id}/cases", headers=ALICE)).json()
    assert cases["total"] == 3
    assert (await api.get(f"{BASE}/datasets/{ds_id}", headers=ALICE)).json()["case_count"] == 3

    # Two strategies over the same dataset.
    runs = []
    for body in ({"judge_enabled": True}, {"judge_enabled": False, "name": "retrieval only"}):
        resp = await api.post(f"{BASE}/runs", json={"dataset_id": ds_id, **body}, headers=ALICE)
        assert resp.status_code == 201, resp.text
        assert resp.json()["status"] == "pending" and resp.json()["dataset_name"] == "回归集"
        runs.append(resp.json()["id"])
    assert task_queue.eval_runs == runs
    for run_id in runs:
        await runner.run(run_id)

    judged = (await api.get(f"{BASE}/runs/{runs[0]}", headers=ALICE)).json()
    assert judged["status"] == "done" and judged["done_count"] == 3, judged["error"]
    metrics = judged["metrics"]
    assert metrics["cases"] == 3 and metrics["errors"] == 0
    assert {"recall@5", "recall@10", "mrr", "ndcg@10"} <= set(metrics)
    assert {"faithfulness", "answer_relevance"} <= set(metrics)
    assert judged["environment"]["chat_model"] and judged["config"]

    results = (await api.get(f"{BASE}/runs/{runs[0]}/results", headers=ALICE)).json()
    by_q = {r["question"]: r for r in results["items"]}
    # The creator (Alice, kb_admin) can read the public knowledge base.
    assert by_q["年假怎么申请"]["metrics"]["recall@10"] == 1.0
    assert by_q["年假怎么申请"]["answer"] and by_q["年假怎么申请"]["judge"]

    plain = (await api.get(f"{BASE}/runs/{runs[1]}", headers=ALICE)).json()
    assert plain["status"] == "done" and "faithfulness" not in plain["metrics"]

    cmp = await api.get(f"{BASE}/runs/compare", params={"run_ids": runs}, headers=ALICE)
    assert cmp.status_code == 200, cmp.text
    body = cmp.json()
    assert [r["id"] for r in body["runs"]] == runs and len(body["cases"]) == 3
    assert set(body["cases"][0]["metrics"]) == set(runs)
    diff = {d["key"]: d["values"] for d in body["config_diff"]}
    assert diff["environment.judge_model"][runs[1]] is None
    one = await api.get(f"{BASE}/runs/compare", params={"run_ids": runs[:1]}, headers=ALICE)
    assert one.status_code == 422

    assert (await api.delete(f"{BASE}/runs/{runs[1]}", headers=ALICE)).status_code == 204
    assert (await api.delete(f"{BASE}/datasets/{ds_id}", headers=ALICE)).status_code == 204
    assert (await api.get(f"{BASE}/runs/{runs[0]}", headers=ALICE)).status_code == 404


async def test_run_respects_creator_acl(
    api: httpx.AsyncClient,
    corpus: dict[str, Any],
    engine: AsyncEngine,
    runner: EvalRunner,
    task_queue: RecordingTaskQueue,
) -> None:
    secret = corpus["secret"]
    carol = await _user(engine, "carol")
    async with create_session_factory(engine)() as session:
        ds = EvalDataset(org_id=carol.org_id, name="acl", created_by=carol.id)
        session.add(ds)
        await session.flush()
        session.add(
            EvalCase(
                org_id=carol.org_id,
                dataset_id=ds.id,
                question="飞织鞋面机密配方 FX-9001 的工艺参数",
                expected_document_ids=[secret["id"]],
            )
        )
        run = EvalRun(
            org_id=carol.org_id,
            dataset_id=ds.id,
            profile_name="builtin",
            config={},
            judge_enabled=False,
            created_by=carol.id,
        )
        session.add(run)
        await session.commit()
        run_id = run.id

    await runner.run(run_id)
    async with create_session_factory(engine)() as session:
        done = await session.get(EvalRun, run_id)
        assert done is not None and done.status == "done"
        assert done.metrics["recall@10"] == 0.0


async def test_evaluation_requires_admin_retrieval(api: httpx.AsyncClient) -> None:
    resp = await api.get(f"{BASE}/datasets", headers=CAROL)
    assert resp.status_code == 403
