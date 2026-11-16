"""Multi-hop graph retrieval gold gate (CI marker: pytest -m gold)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.evaluation.gold_gate import (
    DEFAULT_GRAPH_LIFT,
    load_gold_cases,
    load_graph_rankings,
    relative_lift,
    run_graph_lift_gate,
)

FIXTURES = Path(__file__).parent / "fixtures"
CASES = FIXTURES / "retrieval_graph_gold.jsonl"
RANKINGS = FIXTURES / "retrieval_graph_gold_rankings.json"


@pytest.mark.gold
def test_graph_gold_has_15_to_20_multi_hop_cases() -> None:
    cases = load_gold_cases(CASES)
    assert 15 <= len(cases) <= 20
    assert all("multi_hop" in c.tags and "graph" in c.tags for c in cases)
    assert all(c.hops >= 1 and c.seed_document_ids for c in cases)
    assert {c.lang for c in cases} >= {"zh", "en"}
    domains = {t for c in cases for t in c.tags}
    assert {"it_ops", "equipment"} <= domains


@pytest.mark.gold
def test_graph_lift_gate_passes_fixture() -> None:
    cases = load_gold_cases(CASES)
    without, with_graph = load_graph_rankings(RANKINGS)
    report = run_graph_lift_gate(cases, without, with_graph, min_lift=DEFAULT_GRAPH_LIFT)
    assert report.passed, "; ".join(report.failures)
    assert report.without == 0.0
    assert report.with_graph == 1.0
    assert report.lift >= DEFAULT_GRAPH_LIFT


@pytest.mark.gold
def test_graph_lift_gate_rejects_insufficient_lift() -> None:
    cases = load_gold_cases(CASES)[:4]
    without, with_graph = load_graph_rankings(RANKINGS)
    # Same rankings on both sides → no lift.
    report = run_graph_lift_gate(
        cases,
        {c.id: with_graph[c.id] for c in cases},
        {c.id: with_graph[c.id] for c in cases},
        min_lift=DEFAULT_GRAPH_LIFT,
    )
    assert not report.passed
    assert any("lift=" in f for f in report.failures)


@pytest.mark.gold
def test_relative_lift_uses_absolute_when_baseline_zero() -> None:
    assert relative_lift(0.0, 0.2) == pytest.approx(0.2)
    assert relative_lift(0.4, 0.46) == pytest.approx(0.15)
