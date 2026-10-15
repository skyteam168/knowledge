"""Hybrid retrieval pipeline.

  query ─┬─ DenseRetriever (Qdrant) ──┐
         └─ SparseRetriever (BM25) ───┴─ RRF fusion ─ hydrate (PG re-check) ─ rerank ─ top K

Both routes run concurrently; a failing / slow route is dropped (degraded) as long as the
other one answers. Hydration loads the authoritative chunk text from PG and removes every
chunk the caller can no longer read, *before* any text reaches the reranker model.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from app.core.cache import KeyValueCache
from app.core.metrics import cache_lookup
from app.llm import LLMGateway
from app.retrieval.backends import SearchBackends
from app.retrieval.cache import EmbeddingCache, ResultCache
from app.retrieval.config import RetrievalConfig, Route
from app.retrieval.filters import SearchFilter
from app.retrieval.fusion import FusedCandidate, boost_ko, rrf_fuse
from app.retrieval.query import ParsedQuery
from app.retrieval.rerank import Reranker, RerankUnavailableError
from app.retrieval.retrievers import (
    DenseRetriever,
    RouteResult,
    SearchTarget,
    SparseRetriever,
)

logger = logging.getLogger(__name__)

CACHE_VERSION = 2
MAX_CACHED_CANDIDATES = 200

# Hydrated passages of knowledge objects carry this document type.
KO_DOC_TYPE = "ko"


@dataclass(frozen=True)
class DocumentInfo:
    id: str
    title: str
    filename: str
    kb_id: str
    kb_name: str
    version: int
    doc_type: str
    tags: list[str]
    updated_at: datetime


@dataclass(frozen=True)
class Passage:
    """Authoritative chunk data from PG, only for chunks the caller may read.

    For a knowledge object entry, `document` describes the KO (id = ko_id, version =
    published version) and `content` is the matched question followed by the answer.
    """

    chunk_id: str
    document: DocumentInfo
    content: str
    heading_path: list[str]
    chunk_type: str
    page_start: int | None = None
    page_end: int | None = None
    sheet_name: str | None = None
    slide_number: int | None = None
    is_ko: bool = False

    def rerank_text(self) -> str:
        heading = " / ".join(self.heading_path)
        return f"{heading}\n{self.content}" if heading else self.content


@dataclass
class HydrationResult:
    passages: dict[str, Passage]
    # reason -> number of candidates removed (not_found / stale_version / no_access ...)
    dropped: dict[str, int] = field(default_factory=dict)


class Hydrator(Protocol):
    def __call__(self, chunk_ids: Sequence[str]) -> Awaitable[HydrationResult]: ...


@dataclass(frozen=True)
class RetrievalRequest:
    query: ParsedQuery
    filter: SearchFilter
    config: RetrievalConfig
    target: SearchTarget
    # principals_hash() of the caller: part of the result cache key.
    scope_hash: str
    top_k: int | None = None


@dataclass
class RankedResult:
    rank: int
    passage: Passage
    candidate: FusedCandidate
    rerank_score: float | None = None
    rerank_rank: int | None = None
    highlight: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class RetrievalOutcome:
    results: list[RankedResult]
    stages: dict[str, Any]
    timings: dict[str, float]
    degraded: list[str]
    cache_hit: bool


class RetrievalUnavailableError(Exception):
    def __init__(self, reasons: list[str]) -> None:
        super().__init__(", ".join(reasons))
        self.reasons = reasons


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 2)


def _failure(exc: BaseException) -> str:
    return "timeout" if isinstance(exc, TimeoutError) else f"error: {type(exc).__name__}"


def _one_entry_per_ko(
    ordered: Sequence[FusedCandidate], passages: dict[str, Passage]
) -> list[FusedCandidate]:
    """A KO is indexed once per question variant; keep its best-ranked entry only."""
    seen: set[str] = set()
    result: list[FusedCandidate] = []
    for cand in ordered:
        passage = passages[cand.chunk_id]
        if passage.is_ko:
            if passage.document.id in seen:
                continue
            seen.add(passage.document.id)
        result.append(cand)
    return result


class RetrievalPipeline:
    def __init__(
        self,
        dense: DenseRetriever,
        sparse: SparseRetriever,
        reranker: Reranker,
        result_cache: ResultCache,
    ) -> None:
        self.dense = dense
        self.sparse = sparse
        self.reranker = reranker
        self.result_cache = result_cache

    @classmethod
    def build(
        cls, backends: SearchBackends, gateway: LLMGateway, store: KeyValueCache
    ) -> "RetrievalPipeline":
        return cls(
            dense=DenseRetriever(backends.vector, gateway, EmbeddingCache(store)),
            sparse=SparseRetriever(backends.text),
            reranker=Reranker(gateway),
            result_cache=ResultCache(store),
        )

    # ---- stage 1: concurrent routes -------------------------------------------------

    async def _retrieve(
        self, req: RetrievalRequest, degraded: list[str]
    ) -> tuple[dict[Route, RouteResult], dict[str, Any]]:
        cfg = req.config
        calls: dict[Route, Awaitable[RouteResult]] = {}
        if cfg.dense.enabled:
            calls[Route.DENSE] = asyncio.wait_for(
                self.dense.retrieve(
                    req.query,
                    req.filter,
                    req.target,
                    cfg.dense,
                    embedding_ttl_seconds=cfg.cache.embedding_ttl_seconds,
                ),
                cfg.dense.timeout_seconds,
            )
        if cfg.sparse.enabled:
            calls[Route.SPARSE] = asyncio.wait_for(
                self.sparse.retrieve(req.query, req.filter, req.target, cfg.sparse),
                cfg.sparse.timeout_seconds,
            )
        outcomes = await asyncio.gather(*calls.values(), return_exceptions=True)

        results: dict[Route, RouteResult] = {}
        stage: dict[str, Any] = {}
        for route, outcome in zip(calls, outcomes, strict=True):
            if isinstance(outcome, asyncio.CancelledError):
                raise outcome
            if isinstance(outcome, BaseException):
                reason = _failure(outcome)
                degraded.append(f"{route.value}:{reason}")
                stage[route.value] = {"status": reason, "error": str(outcome)[:500], "hits": []}
                logger.warning(
                    "retrieval_route_failed",
                    extra={"route": route.value, "reason": reason, "error": str(outcome)[:500]},
                )
                continue
            results[route] = outcome
            stage[route.value] = {
                "status": "ok",
                "took_ms": outcome.took_ms,
                **outcome.info,
                "hits": [
                    {"chunk_id": h.chunk_id, "rank": i, "score": round(h.score, 6)}
                    for i, h in enumerate(outcome.hits, start=1)
                ],
            }
        for route in Route:
            if route not in calls:
                stage[route.value] = {"status": "disabled", "hits": []}
        if not results:
            raise RetrievalUnavailableError(degraded)
        return results, stage

    # ---- run --------------------------------------------------------------------------

    async def _cache_key(self, req: RetrievalRequest) -> str | None:
        if req.config.cache.result_ttl_seconds <= 0:
            return None
        generation = await self.result_cache.generation(req.filter.acl.org_id)
        if generation is None:
            return None
        q = req.query
        return ResultCache.key(
            req.filter.acl.org_id,
            req.scope_hash,
            {
                "v": CACHE_VERSION,
                "text": q.text,
                "exact": list(q.exact_terms),
                "filter": req.filter.describe(),
                "config": req.config.fingerprint(),
                "generation": req.target.generation,
                "embedding": [req.target.embedding.model, req.target.embedding.dim],
            },
            generation,
        )

    async def run(self, req: RetrievalRequest, hydrate: Hydrator) -> RetrievalOutcome:
        started = time.perf_counter()
        cfg = req.config
        top_k = req.top_k or cfg.top_k
        degraded: list[str] = []
        timings: dict[str, float] = {}

        key = await self._cache_key(req)
        cached = await self.result_cache.get(key) if key else None
        cache_hit = bool(cached and cached.get("v") == CACHE_VERSION)
        if key:
            cache_lookup("retrieval_result", cache_hit)
        rerank_memo: dict[str, float] = {}
        if cached and cache_hit:
            fused = [
                FusedCandidate(
                    chunk_id=c["chunk_id"],
                    rrf_score=c["rrf"],
                    ranks={Route(r): v for r, v in c["ranks"].items()},
                    scores={Route(r): v for r, v in c["scores"].items()},
                    rrf_rank=c["rrf_rank"],
                    is_ko=bool(c.get("ko")),
                )
                for c in cached["candidates"]
            ]
            highlights: dict[str, dict[str, list[str]]] = cached["highlights"]
            routes_stage: dict[str, Any] = cached["routes"]
            rerank_memo = cached.get("rerank", {})
            timings["retrieve_ms"] = _ms(started)
        else:
            t = time.perf_counter()
            route_results, routes_stage = await self._retrieve(req, degraded)
            timings["retrieve_ms"] = _ms(t)
            for route, rr in route_results.items():
                timings[f"{route.value}_ms"] = rr.took_ms
            t = time.perf_counter()
            fused = rrf_fuse(
                {r: [(h.chunk_id, h.score) for h in rr.hits] for r, rr in route_results.items()},
                k=cfg.fusion.k,
                weights=cfg.fusion.weights,
                ko_ids={
                    h.chunk_id
                    for rr in route_results.values()
                    for h in rr.hits
                    if h.payload.get("is_ko")
                },
            )
            if cfg.ko.enabled:
                fused = boost_ko(fused, cfg.ko.rrf_weight)
            highlights = {
                h.chunk_id: h.highlight
                for rr in route_results.values()
                for h in rr.hits
                if h.highlight
            }
            timings["fusion_ms"] = _ms(t)

        # ---- PG re-check + authoritative text ----
        pool_size = max(cfg.rerank.top_n if cfg.rerank.enabled else 0, top_k)
        pool = fused[:pool_size]
        t = time.perf_counter()
        hydration = await hydrate([c.chunk_id for c in pool])
        timings["hydrate_ms"] = _ms(t)
        kept = [c for c in pool if c.chunk_id in hydration.passages]

        # ---- rerank ----
        rerank_scores: dict[str, float] | None = None
        rerank_status = "disabled"
        t = time.perf_counter()
        if cfg.rerank.enabled and kept:
            if all(c.chunk_id in rerank_memo for c in kept):
                rerank_scores = {c.chunk_id: rerank_memo[c.chunk_id] for c in kept}
                rerank_status = "cached"
            else:
                try:
                    scores = await self.reranker.score(
                        req.query.text,
                        [hydration.passages[c.chunk_id].rerank_text() for c in kept],
                        cfg.rerank,
                    )
                    rerank_scores = {c.chunk_id: s for c, s in zip(kept, scores, strict=True)}
                    rerank_status = "ok"
                except RerankUnavailableError as exc:
                    degraded.append(f"rerank:{exc}")
                    rerank_status = f"degraded: {exc}"
                    logger.warning("rerank_degraded", extra={"error": str(exc)})
        timings["rerank_ms"] = _ms(t)

        raw_scores = rerank_scores
        if rerank_scores is not None and cfg.ko.enabled and cfg.ko.rerank_bonus:
            rerank_scores = {
                cid: s + (cfg.ko.rerank_bonus if hydration.passages[cid].is_ko else 0.0)
                for cid, s in rerank_scores.items()
            }
        if rerank_scores is not None:
            scores_now = rerank_scores
            ordered = sorted(kept, key=lambda c: (-scores_now[c.chunk_id], c.rrf_rank))
        else:
            ordered = kept
        ordered = _one_entry_per_ko(ordered, hydration.passages)
        rerank_ranks = (
            {c.chunk_id: i for i, c in enumerate(ordered, start=1)} if rerank_scores else {}
        )
        results = [
            RankedResult(
                rank=i,
                passage=hydration.passages[c.chunk_id],
                candidate=c,
                rerank_score=rerank_scores.get(c.chunk_id) if rerank_scores else None,
                rerank_rank=rerank_ranks.get(c.chunk_id),
                highlight=highlights.get(c.chunk_id, {}),
            )
            for i, c in enumerate(ordered[:top_k], start=1)
        ]

        if key and not degraded and (not cache_hit or rerank_status == "ok"):
            await self.result_cache.set(
                key,
                {
                    "v": CACHE_VERSION,
                    "candidates": [
                        {
                            "chunk_id": c.chunk_id,
                            "rrf": c.rrf_score,
                            "rrf_rank": c.rrf_rank,
                            "ranks": {r.value: v for r, v in c.ranks.items()},
                            "scores": {r.value: v for r, v in c.scores.items()},
                            "ko": c.is_ko,
                        }
                        for c in fused[:MAX_CACHED_CANDIDATES]
                    ],
                    "highlights": {
                        cid: hl
                        for cid, hl in highlights.items()
                        if cid in {c.chunk_id for c in fused[:MAX_CACHED_CANDIDATES]}
                    },
                    "routes": routes_stage,
                    "rerank": {**rerank_memo, **(raw_scores or {})},
                },
                cfg.cache.result_ttl_seconds,
            )

        timings["total_ms"] = _ms(started)
        stages: dict[str, Any] = {
            "query": {
                "raw": req.query.raw,
                "text": req.query.text,
                "exact_terms": list(req.query.exact_terms),
                "ignored": list(req.query.ignored),
            },
            "filter": req.filter.describe(),
            "target": {
                "generation": req.target.generation,
                "collection": req.target.collection,
                "index": req.target.index,
                "embedding_model": req.target.embedding.model,
            },
            "cache_hit": cache_hit,
            "routes": routes_stage,
            "fusion": {
                "k": cfg.fusion.k,
                "weights": {r.value: w for r, w in cfg.fusion.weights.items()},
                "ko": cfg.ko.model_dump(),
                "total": len(fused),
                "candidates": [
                    {
                        "chunk_id": c.chunk_id,
                        "rrf": round(c.rrf_score, 6),
                        "rrf_rank": c.rrf_rank,
                        "ranks": {r.value: v for r, v in c.ranks.items()},
                        **({"is_ko": True} if c.is_ko else {}),
                    }
                    for c in fused
                ],
            },
            "hydration": {
                "requested": len(pool),
                "kept": len(kept),
                "dropped": hydration.dropped,
            },
            "rerank": {
                "status": rerank_status,
                "model": self.reranker.gateway.reranker.model if cfg.rerank.enabled else None,
                "scores": [
                    {
                        "chunk_id": cid,
                        "score": round(s, 6),
                        "raw": round((raw_scores or {}).get(cid, s), 6),
                        "rank": rerank_ranks.get(cid),
                    }
                    for cid, s in sorted(
                        (rerank_scores or {}).items(), key=lambda kv: rerank_ranks.get(kv[0], 0)
                    )
                ],
            },
            "results": [
                {
                    "rank": r.rank,
                    "chunk_id": r.passage.chunk_id,
                    "document_id": r.passage.document.id,
                    "rrf_rank": r.candidate.rrf_rank,
                    "rerank_score": r.rerank_score,
                    "is_ko": r.passage.is_ko,
                }
                for r in results
            ],
        }
        return RetrievalOutcome(
            results=results,
            stages=stages,
            timings=timings,
            degraded=degraded,
            cache_hit=cache_hit,
        )
