"""Offline retrieval gold-set gate: load JSONL cases and enforce Recall@k / MRR floors.

Also supports a graph multi-hop lift gate: compare rankings with graph on vs off and
require a minimum relative (or absolute when baseline is zero) improvement.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.evaluation.metrics import ranking_metrics

DEFAULT_GRAPH_LIFT = 0.15


@dataclass(frozen=True)
class GoldCase:
    id: str
    lang: str
    query: str
    expected_document_ids: frozenset[str]
    min_recall_at_5: float
    min_mrr: float
    # Multi-hop metadata (optional; used by the graph lift gate / docs).
    tags: tuple[str, ...] = ()
    hops: int = 0
    seed_document_ids: frozenset[str] = frozenset()


@dataclass(frozen=True)
class GoldCaseResult:
    case_id: str
    metrics: dict[str, float]
    passed: bool
    failures: tuple[str, ...]


def _string_list(value: Any, *, field: str, line: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise ValueError(f"{line}: {field} must be a list of strings")
    return [x for x in value if x]


def load_gold_cases(path: Path) -> list[GoldCase]:
    cases: list[GoldCase] = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        loc = f"{path}:{line_no}"
        try:
            row: dict[str, Any] = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{loc}: invalid JSON") from exc
        missing = {"id", "query", "expected_document_ids"} - set(row)
        if missing:
            raise ValueError(f"{loc}: missing {sorted(missing)}")
        expected = _string_list(row["expected_document_ids"], field="expected_document_ids", line=loc)
        if not expected:
            raise ValueError(f"{loc}: expected_document_ids must be a non-empty string list")
        seeds = _string_list(
            row.get("seed_document_ids") or [], field="seed_document_ids", line=loc
        )
        tags = _string_list(row.get("tags") or [], field="tags", line=loc)
        hops = int(row.get("hops") or 0)
        if hops < 0:
            raise ValueError(f"{loc}: hops must be >= 0")
        cases.append(
            GoldCase(
                id=str(row["id"]),
                lang=str(row.get("lang") or "zh"),
                query=str(row["query"]),
                expected_document_ids=frozenset(expected),
                min_recall_at_5=float(row.get("min_recall_at_5", 1.0)),
                min_mrr=float(row.get("min_mrr", 0.5)),
                tags=tuple(tags),
                hops=hops,
                seed_document_ids=frozenset(seeds),
            )
        )
    if not cases:
        raise ValueError(f"{path}: no gold cases")
    return cases


def evaluate_gold_case(case: GoldCase, ranked_document_ids: Sequence[str]) -> GoldCaseResult:
    metrics = ranking_metrics(list(ranked_document_ids), set(case.expected_document_ids))
    failures: list[str] = []
    recall = metrics.get("recall@5", 0.0)
    mrr = metrics.get("mrr", 0.0)
    if recall < case.min_recall_at_5:
        failures.append(f"recall@5={recall} < {case.min_recall_at_5}")
    if mrr < case.min_mrr:
        failures.append(f"mrr={mrr} < {case.min_mrr}")
    return GoldCaseResult(
        case_id=case.id, metrics=metrics, passed=not failures, failures=tuple(failures)
    )


def run_gold_gate(
    cases: Sequence[GoldCase], rankings: Mapping[str, Sequence[str]]
) -> list[GoldCaseResult]:
    results: list[GoldCaseResult] = []
    for case in cases:
        ranked = rankings.get(case.id)
        if ranked is None:
            results.append(
                GoldCaseResult(
                    case_id=case.id,
                    metrics={},
                    passed=False,
                    failures=("missing ranking",),
                )
            )
            continue
        results.append(evaluate_gold_case(case, ranked))
    return results


@dataclass(frozen=True)
class MetricRegression:
    metric: str
    baseline: float
    candidate: float
    delta: float
    regress: bool


def compare_run_metrics(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    metrics: Sequence[str] = ("recall@10", "mrr"),
) -> list[MetricRegression]:
    """Flag regressions when a candidate run's aggregate metric drops below the baseline."""
    out: list[MetricRegression] = []
    for key in metrics:
        b = float(baseline.get(key) or 0.0)
        c = float(candidate.get(key) or 0.0)
        out.append(
            MetricRegression(
                metric=key, baseline=b, candidate=c, delta=c - b, regress=c + 1e-12 < b
            )
        )
    return out


def mean_case_metric(results: Sequence[GoldCaseResult], metric: str) -> float:
    values = [float(r.metrics[metric]) for r in results if metric in r.metrics]
    if not values:
        return 0.0
    return round(sum(values) / len(values), 6)


def relative_lift(baseline: float, candidate: float) -> float:
    """(candidate - baseline) / baseline; when baseline is 0, return absolute delta."""
    if baseline <= 0:
        return candidate - baseline
    return (candidate - baseline) / baseline


@dataclass(frozen=True)
class GraphLiftReport:
    metric: str
    without: float
    with_graph: float
    lift: float
    min_lift: float
    passed: bool
    without_results: tuple[GoldCaseResult, ...]
    with_results: tuple[GoldCaseResult, ...]
    failures: tuple[str, ...]


def run_graph_lift_gate(
    cases: Sequence[GoldCase],
    rankings_without: Mapping[str, Sequence[str]],
    rankings_with: Mapping[str, Sequence[str]],
    *,
    metric: str = "recall@5",
    min_lift: float = DEFAULT_GRAPH_LIFT,
) -> GraphLiftReport:
    """Require graph-on rankings to beat graph-off by `min_lift` (≥15% by default).

    Lift is relative when the without-graph mean is > 0; otherwise absolute (points).
    Per-case floors are also enforced on the with-graph rankings.
    """
    without = run_gold_gate(cases, rankings_without)
    with_graph = run_gold_gate(cases, rankings_with)
    # Per-case floors for the off path are not required (many will fail by design).
    without_mean = mean_case_metric(without, metric)
    with_mean = mean_case_metric(with_graph, metric)
    lift = relative_lift(without_mean, with_mean)
    failures: list[str] = []
    failed_cases = [r for r in with_graph if not r.passed]
    if failed_cases:
        failures.append(
            "with_graph cases failed: "
            + "; ".join(f"{r.case_id}: {', '.join(r.failures)}" for r in failed_cases)
        )
    if lift + 1e-12 < min_lift:
        kind = "absolute" if without_mean <= 0 else "relative"
        failures.append(
            f"{metric} {kind} lift={lift:.4f} < {min_lift} "
            f"(without={without_mean}, with={with_mean})"
        )
    return GraphLiftReport(
        metric=metric,
        without=without_mean,
        with_graph=with_mean,
        lift=round(lift, 6),
        min_lift=min_lift,
        passed=not failures,
        without_results=tuple(without),
        with_results=tuple(with_graph),
        failures=tuple(failures),
    )


def load_graph_rankings(path: Path) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Load `{without_graph: {id: [...]}, with_graph: {id: [...]}}` fixture."""
    raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    missing = {"without_graph", "with_graph"} - set(raw)
    if missing:
        raise ValueError(f"{path}: missing {sorted(missing)}")

    def _map(key: str) -> dict[str, list[str]]:
        block = raw[key]
        if not isinstance(block, dict):
            raise ValueError(f"{path}: {key} must be an object")
        out: dict[str, list[str]] = {}
        for case_id, ranked in block.items():
            if not isinstance(ranked, list) or not all(isinstance(x, str) for x in ranked):
                raise ValueError(f"{path}: {key}.{case_id} must be a string list")
            out[str(case_id)] = list(ranked)
        return out

    return _map("without_graph"), _map("with_graph")


async def run_live_gold(
    cases: Sequence[GoldCase],
    search: Any,
) -> list[GoldCaseResult]:
    """`search` is an async callable(query: str) -> Sequence[str] of ranked document ids."""
    rankings: dict[str, Sequence[str]] = {}
    for case in cases:
        rankings[case.id] = list(await search(case.query))
    return run_gold_gate(cases, rankings)
