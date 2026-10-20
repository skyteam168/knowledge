"""Offline retrieval gold-set gate: load JSONL cases and enforce Recall@k / MRR floors."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.evaluation.metrics import ranking_metrics


@dataclass(frozen=True)
class GoldCase:
    id: str
    lang: str
    query: str
    expected_document_ids: frozenset[str]
    min_recall_at_5: float
    min_mrr: float


@dataclass(frozen=True)
class GoldCaseResult:
    case_id: str
    metrics: dict[str, float]
    passed: bool
    failures: tuple[str, ...]


def load_gold_cases(path: Path) -> list[GoldCase]:
    cases: list[GoldCase] = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            row: dict[str, Any] = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_no}: invalid JSON") from exc
        missing = {"id", "query", "expected_document_ids"} - set(row)
        if missing:
            raise ValueError(f"{path}:{line_no}: missing {sorted(missing)}")
        expected = row["expected_document_ids"]
        ok_list = isinstance(expected, list) and bool(expected)
        if not ok_list or not all(isinstance(x, str) for x in expected):
            raise ValueError(
                f"{path}:{line_no}: expected_document_ids must be a non-empty string list"
            )
        cases.append(
            GoldCase(
                id=str(row["id"]),
                lang=str(row.get("lang") or "zh"),
                query=str(row["query"]),
                expected_document_ids=frozenset(expected),
                min_recall_at_5=float(row.get("min_recall_at_5", 1.0)),
                min_mrr=float(row.get("min_mrr", 0.5)),
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
