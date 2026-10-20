"""Retrieval gold-set gate (CI marker: pytest -m gold)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.retrieval.config import SPARSE_FIELDS, SparseConfig, default_sparse_boosts
from app.retrieval.filters import SearchFilter
from app.retrieval.query import ParsedQuery
from app.retrieval.retrievers import SparseRetriever
from app.services.authz.acl import AclFilter
from app.services.evaluation.gold_gate import (
    compare_run_metrics,
    load_gold_cases,
    run_gold_gate,
    run_live_gold,
)

FIXTURES = Path(__file__).parent / "fixtures"
GOLD_PATH = FIXTURES / "retrieval_gold.jsonl"
RANKINGS_PATH = FIXTURES / "retrieval_gold_rankings.json"


@pytest.mark.gold
def test_gold_fixture_schema_and_gate() -> None:
    cases = load_gold_cases(GOLD_PATH)
    assert len(cases) >= 5
    langs = {c.lang for c in cases}
    assert {"zh", "en", "vi"} <= langs

    rankings = json.loads(RANKINGS_PATH.read_text(encoding="utf-8"))
    results = run_gold_gate(cases, rankings)
    failed = [r for r in results if not r.passed]
    assert not failed, "; ".join(f"{r.case_id}: {', '.join(r.failures)}" for r in failed)


@pytest.mark.gold
def test_gold_gate_detects_regression() -> None:
    cases = load_gold_cases(GOLD_PATH)
    rankings = {c.id: ["doc-unrelated"] for c in cases}
    results = run_gold_gate(cases, rankings)
    assert all(not r.passed for r in results)


@pytest.mark.gold
def test_compare_run_metrics_flags_regression() -> None:
    gates = compare_run_metrics(
        {"recall@10": 1.0, "mrr": 0.9},
        {"recall@10": 0.8, "mrr": 0.95},
    )
    by_metric = {g.metric: g for g in gates}
    assert by_metric["recall@10"].regress is True
    assert by_metric["mrr"].regress is False


@pytest.mark.gold
@pytest.mark.asyncio
async def test_live_gold_uses_search_callable() -> None:
    cases = load_gold_cases(GOLD_PATH)[:1]
    case = cases[0]

    async def search(query: str) -> list[str]:
        assert query == case.query
        return list(case.expected_document_ids)

    results = await run_live_gold(cases, search)
    assert results and results[0].passed


@pytest.mark.gold_live
@pytest.mark.skipif(
    __import__("os").environ.get("EKB_GOLD_LIVE") != "1",
    reason="set EKB_GOLD_LIVE=1 with a running search stack",
)
def test_live_gold_placeholder_requires_stack() -> None:
    pytest.fail("wire SearchService here when running against a live stack")


@pytest.mark.gold
def test_sparse_defaults_cover_multilingual_fields() -> None:
    boosts = default_sparse_boosts()
    assert "content.en" in boosts and "content.vi" in boosts
    cfg = SparseConfig()
    assert set(cfg.field_boosts) <= set(SPARSE_FIELDS)
    body = SparseRetriever.build_body(
        ParsedQuery(raw="annual leave", text="annual leave", exact_terms=()),
        SearchFilter(acl=AclFilter(org_id="o1", principals=("org:o1",))),
        cfg,
    )
    fields = body["query"]["bool"]["must"][0]["multi_match"]["fields"]
    joined = " ".join(fields)
    assert "title.en^" in joined and "content.vi^" in joined
