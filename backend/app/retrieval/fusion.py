"""Reciprocal Rank Fusion: score(d) = Σ_i w_i / (k + rank_i(d)), ranks are 1-based."""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field

from app.retrieval.config import Route


@dataclass
class FusedCandidate:
    chunk_id: str
    rrf_score: float
    # Original 1-based rank / raw score in every route that returned the chunk.
    ranks: dict[Route, int] = field(default_factory=dict)
    scores: dict[Route, float] = field(default_factory=dict)
    rrf_rank: int = 0
    # Entry of a curated knowledge object (index payload is_ko).
    is_ko: bool = False


def _order(cands: Sequence[FusedCandidate]) -> list[FusedCandidate]:
    ordered = sorted(cands, key=lambda c: (-c.rrf_score, min(c.ranks.values()), c.chunk_id))
    for rank, cand in enumerate(ordered, start=1):
        cand.rrf_rank = rank
    return ordered


def rrf_fuse(
    rankings: Mapping[Route, Sequence[tuple[str, float]]],
    *,
    k: int = 60,
    weights: Mapping[Route, float] | None = None,
    ko_ids: Collection[str] = (),
) -> list[FusedCandidate]:
    """Fuse per-route rankings of (chunk_id, raw_score), best first.

    A chunk listed twice by one route keeps its best rank there. Ties are broken by the
    best single-route rank, then chunk_id, so the order is deterministic.
    """
    if k < 1:
        raise ValueError("k must be >= 1")
    fused: dict[str, FusedCandidate] = {}
    for route, ranking in rankings.items():
        weight = 1.0 if weights is None else weights.get(route, 1.0)
        for position, (chunk_id, score) in enumerate(ranking, start=1):
            cand = fused.setdefault(
                chunk_id,
                FusedCandidate(chunk_id=chunk_id, rrf_score=0.0, is_ko=chunk_id in ko_ids),
            )
            if route in cand.ranks:
                continue
            cand.ranks[route] = position
            cand.scores[route] = score
            cand.rrf_score += weight / (k + position)
    return _order(list(fused.values()))


def boost_ko(fused: Sequence[FusedCandidate], weight: float) -> list[FusedCandidate]:
    """Multiply the RRF score of knowledge object entries by `weight` and re-rank."""
    if weight == 1.0 or not any(c.is_ko for c in fused):
        return list(fused)
    for cand in fused:
        if cand.is_ko:
            cand.rrf_score *= weight
    return _order(fused)
