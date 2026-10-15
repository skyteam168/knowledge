"""Retrieval metrics with binary relevance.

Document level (always, when expected documents exist): a retrieved chunk is relevant if its
document (or knowledge object) is expected; each expected document counts once, at its best
rank. Chunk level (when expected chunks exist): the same over chunk ids. Chunk ids are
per document version, so chunk-level judgements go stale when a document is re-uploaded.
"""

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

KS = (5, 10)
NDCG_K = 10


@dataclass(frozen=True)
class RetrievedItem:
    rank: int
    chunk_id: str
    document_id: str


def _first_ranks(keys: Sequence[str], targets: set[str]) -> dict[str, int]:
    first: dict[str, int] = {}
    for rank, key in enumerate(keys, start=1):
        if key in targets and key not in first:
            first[key] = rank
    return first


def ranking_metrics(keys: Sequence[str], targets: set[str], prefix: str = "") -> dict[str, float]:
    """Recall@k, MRR and nDCG@10 of a ranked list of keys against a set of relevant keys."""
    if not targets:
        return {}
    first = _first_ranks(keys, targets)
    out: dict[str, float] = {}
    for k in KS:
        out[f"{prefix}recall@{k}"] = sum(1 for r in first.values() if r <= k) / len(targets)
    out[f"{prefix}mrr"] = 1.0 / min(first.values()) if first else 0.0
    dcg = sum(1.0 / math.log2(r + 1) for r in first.values() if r <= NDCG_K)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(targets), NDCG_K) + 1))
    out[f"{prefix}ndcg@{NDCG_K}"] = dcg / idcg if idcg else 0.0
    return {k: round(v, 6) for k, v in out.items()}


def retrieval_metrics(
    retrieved: Sequence[RetrievedItem],
    expected_document_ids: Iterable[str],
    expected_chunk_ids: Iterable[str] = (),
) -> dict[str, float]:
    ordered = sorted(retrieved, key=lambda r: r.rank)
    metrics = ranking_metrics([r.document_id for r in ordered], set(expected_document_ids))
    metrics.update(
        ranking_metrics([r.chunk_id for r in ordered], set(expected_chunk_ids), prefix="chunk_")
    )
    return metrics


def citation_precision(
    citations: Sequence[Mapping[str, Any]], expected_document_ids: Iterable[str]
) -> float | None:
    """Share of the answer's citations that point at an expected document (None: undefined)."""
    expected = set(expected_document_ids)
    if not citations or not expected:
        return None
    hits = sum(1 for c in citations if c.get("document_id") in expected)
    return round(hits / len(citations), 6)


def mean_metrics(rows: Iterable[Mapping[str, Any]]) -> dict[str, float]:
    """Per metric mean over the rows where it is defined (numbers only)."""
    sums: dict[str, float] = {}
    counts: dict[str, int] = {}
    for row in rows:
        for key, value in row.items():
            if isinstance(value, bool) or not isinstance(value, int | float):
                continue
            sums[key] = sums.get(key, 0.0) + float(value)
            counts[key] = counts.get(key, 0) + 1
    return {k: round(sums[k] / counts[k], 6) for k in sorted(sums)}
