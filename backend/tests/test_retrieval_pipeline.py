import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from app.core.cache import MemoryCache
from app.llm import LLMError, LLMGateway
from app.llm.base import RerankResult
from app.llm.mock import MockEmbeddingClient
from app.retrieval.backends import SearchBackends
from app.retrieval.cache import ResultCache, principals_hash
from app.retrieval.config import RetrievalConfig, Route
from app.retrieval.filters import SearchFilter
from app.retrieval.memory import MemoryTextIndex, MemoryVectorIndex
from app.retrieval.pipeline import (
    DocumentInfo,
    HydrationResult,
    Passage,
    RetrievalPipeline,
    RetrievalRequest,
    RetrievalUnavailableError,
)
from app.retrieval.query import QueryPreprocessor
from app.retrieval.rerank import Reranker
from app.retrieval.retrievers import (
    DenseRetriever,
    RouteHit,
    RouteResult,
    SearchTarget,
    SparseRetriever,
)
from app.services.authz.acl import AclFilter


class FakeDense(DenseRetriever):
    def __init__(self, ids: Sequence[str], *, fail: bool = False, delay: float = 0) -> None:
        self.ids, self.fail, self.delay, self.calls = list(ids), fail, delay, 0

    async def retrieve(self, *args: object, **kwargs: object) -> RouteResult:
        self.calls += 1
        await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("qdrant down")
        hits = [RouteHit(c, 1 - i / 100) for i, c in enumerate(self.ids)]
        return RouteResult(Route.DENSE, hits, took_ms=1.0)


class FakeSparse(SparseRetriever):
    def __init__(self, ids: Sequence[str], *, fail: bool = False, delay: float = 0) -> None:
        self.ids, self.fail, self.delay, self.calls = list(ids), fail, delay, 0

    async def retrieve(self, *args: object, **kwargs: object) -> RouteResult:
        self.calls += 1
        await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("opensearch down")
        hits = [
            RouteHit(c, 20.0 - i, highlight={"content": [f"<em>{c}</em>"]})
            for i, c in enumerate(self.ids)
        ]
        return RouteResult(Route.SPARSE, hits, took_ms=1.0)


class ScriptedReranker:
    """RerankClient scoring passages by a fixed table (content -> score)."""

    def __init__(self, table: dict[str, float], *, delay: float = 0, fail: bool = False) -> None:
        self.table, self.delay, self.fail = table, delay, fail
        self.seen: list[str] = []

    @property
    def model(self) -> str:
        return "scripted-reranker"

    async def rerank(
        self, query: str, documents: Sequence[str], top_n: int | None = None
    ) -> list[RerankResult]:
        self.seen.extend(documents)
        await asyncio.sleep(self.delay)
        if self.fail:
            raise LLMError("reranker 500")
        return [RerankResult(i, self.table.get(d, 0.0)) for i, d in enumerate(documents)]


DOC = DocumentInfo(
    id="doc-1",
    title="制度",
    filename="制度.md",
    kb_id="kb-1",
    kb_name="KB",
    version=1,
    doc_type="markdown",
    tags=[],
    updated_at=datetime(2026, 1, 1, tzinfo=UTC),
)


class Hydrator:
    """PG stand-in: passages for readable chunks only; `revoked` simulates lost access."""

    def __init__(self) -> None:
        self.revoked: set[str] = set()
        self.calls: list[list[str]] = []

    async def __call__(self, chunk_ids: Sequence[str]) -> HydrationResult:
        self.calls.append(list(chunk_ids))
        kept = {
            c: Passage(chunk_id=c, document=DOC, content=c, heading_path=[], chunk_type="text")
            for c in chunk_ids
            if c not in self.revoked
        }
        dropped = len(chunk_ids) - len(kept)
        return HydrationResult(kept, {"no_access": dropped} if dropped else {})


def config(**overrides: object) -> RetrievalConfig:
    base: dict[str, object] = {
        "dense": {"timeout_seconds": 0.2},
        "sparse": {"timeout_seconds": 0.2},
        "rerank": {"timeout_seconds": 0.2, "batch_size": 2},
        "top_k": 3,
    }
    base.update(overrides)
    return RetrievalConfig.model_validate(base)


def request(
    llm_gateway: LLMGateway,
    cfg: RetrievalConfig,
    *,
    principals: tuple[str, ...] = ("user:u1",),
    org_id: str = "org-1",
) -> RetrievalRequest:
    return RetrievalRequest(
        query=QueryPreprocessor().parse("报销 制度"),
        filter=SearchFilter(acl=AclFilter(org_id=org_id, principals=principals)),
        config=cfg,
        target=SearchTarget(1, "kb_chunks_v1", "kb_chunks_v1", llm_gateway.default_embedding),
        scope_hash=principals_hash(principals),
    )


def make_pipeline(
    llm_gateway: LLMGateway, dense: FakeDense, sparse: FakeSparse, cache: MemoryCache | None = None
) -> RetrievalPipeline:
    return RetrievalPipeline(
        dense, sparse, Reranker(llm_gateway), ResultCache(cache or MemoryCache())
    )


async def test_full_chain_records_every_stage(llm_gateway: LLMGateway) -> None:
    llm_gateway.reranker = ScriptedReranker({"c": 0.9, "a": 0.5, "b": 0.1, "d": 0.2})
    pipe = make_pipeline(llm_gateway, FakeDense(["a", "b", "c"]), FakeSparse(["c", "d"]))
    out = await pipe.run(request(llm_gateway, config()), Hydrator())

    assert [r.passage.chunk_id for r in out.results] == ["c", "a", "d"]
    assert out.degraded == [] and out.cache_hit is False
    c = out.results[0]
    assert c.candidate.ranks == {Route.DENSE: 3, Route.SPARSE: 1}
    assert c.candidate.rrf_rank == 1 and c.rerank_rank == 1 and c.rerank_score == 0.9
    assert c.highlight == {"content": ["<em>c</em>"]}
    assert set(out.stages) >= {"query", "filter", "routes", "fusion", "hydration", "rerank"}
    assert out.stages["routes"]["dense"]["status"] == "ok"
    assert len(out.stages["fusion"]["candidates"]) == 4
    assert out.stages["rerank"]["status"] == "ok"
    assert {"retrieve_ms", "fusion_ms", "hydrate_ms", "rerank_ms", "total_ms"} <= set(out.timings)


@pytest.mark.parametrize(
    ("dense", "reason"),
    [
        (FakeDense(["a"], fail=True), "dense:error: RuntimeError"),
        (FakeDense(["a"], delay=1.0), "dense:timeout"),
    ],
)
async def test_failing_route_degrades_to_the_other(
    llm_gateway: LLMGateway, dense: FakeDense, reason: str
) -> None:
    cache = MemoryCache()
    pipe = make_pipeline(llm_gateway, dense, FakeSparse(["x", "y"]), cache)
    out = await pipe.run(request(llm_gateway, config()), Hydrator())

    assert out.degraded == [reason]
    assert {r.passage.chunk_id for r in out.results} == {"x", "y"}
    assert all(r.candidate.ranks.keys() == {Route.SPARSE} for r in out.results)
    assert out.stages["routes"]["dense"]["status"] != "ok"
    # Degraded rankings are not cached.
    assert not [k for k in cache._data if k.startswith("retrieval:res:")]


async def test_both_routes_failing_is_unavailable(llm_gateway: LLMGateway) -> None:
    pipe = make_pipeline(llm_gateway, FakeDense(["a"], fail=True), FakeSparse(["b"], delay=1.0))
    with pytest.raises(RetrievalUnavailableError) as err:
        await pipe.run(request(llm_gateway, config()), Hydrator())
    assert sorted(err.value.reasons) == ["dense:error: RuntimeError", "sparse:timeout"]


async def test_disabled_route_is_not_called(llm_gateway: LLMGateway) -> None:
    dense = FakeDense(["a"])
    pipe = make_pipeline(llm_gateway, dense, FakeSparse(["b"]))
    out = await pipe.run(request(llm_gateway, config(dense={"enabled": False})), Hydrator())
    assert dense.calls == 0 and out.degraded == []
    assert out.stages["routes"]["dense"]["status"] == "disabled"


@pytest.mark.parametrize(
    ("client", "reason"),
    [
        (ScriptedReranker({"b": 1.0}, delay=1.0), "rerank:timeout"),
        (ScriptedReranker({"b": 1.0}, fail=True), "rerank:error: reranker 500"),
    ],
)
async def test_rerank_failure_falls_back_to_rrf_order(
    llm_gateway: LLMGateway, client: ScriptedReranker, reason: str
) -> None:
    llm_gateway.reranker = client
    pipe = make_pipeline(llm_gateway, FakeDense(["a", "b", "c"]), FakeSparse(["a", "b"]))
    out = await pipe.run(request(llm_gateway, config()), Hydrator())
    assert out.degraded == [reason]
    assert [r.passage.chunk_id for r in out.results] == ["a", "b", "c"]
    assert all(r.rerank_score is None for r in out.results)


async def test_rerank_is_batched_over_top_n_and_cuts_to_top_k(llm_gateway: LLMGateway) -> None:
    ids = [f"c{i:02d}" for i in range(12)]
    client = ScriptedReranker({c: i / 100 for i, c in enumerate(ids)})
    llm_gateway.reranker = client
    pipe = make_pipeline(llm_gateway, FakeDense(ids), FakeSparse([]))
    cfg = config(rerank={"top_n": 8, "batch_size": 3}, top_k=4)
    out = await pipe.run(request(llm_gateway, cfg), Hydrator())
    assert len(client.seen) == 8
    # Highest reranker scores among the top-8 RRF candidates, best first.
    assert [r.passage.chunk_id for r in out.results] == ["c07", "c06", "c05", "c04"]


async def test_unreadable_chunks_never_reach_the_reranker(llm_gateway: LLMGateway) -> None:
    client = ScriptedReranker({})
    llm_gateway.reranker = client
    hydrator = Hydrator()
    hydrator.revoked = {"secret"}
    pipe = make_pipeline(llm_gateway, FakeDense(["secret", "a"]), FakeSparse(["secret"]))
    out = await pipe.run(request(llm_gateway, config()), hydrator)
    assert "secret" not in client.seen
    assert [r.passage.chunk_id for r in out.results] == ["a"]
    assert out.stages["hydration"]["dropped"] == {"no_access": 1}


async def test_result_cache_is_scoped_and_rechecked(llm_gateway: LLMGateway) -> None:
    llm_gateway.reranker = ScriptedReranker({"a": 0.2, "b": 0.8})
    cache = MemoryCache()
    dense, sparse = FakeDense(["a", "b"]), FakeSparse(["b"])
    pipe = make_pipeline(llm_gateway, dense, sparse, cache)
    hydrator = Hydrator()
    first = await pipe.run(request(llm_gateway, config()), hydrator)
    assert not first.cache_hit

    second = await pipe.run(request(llm_gateway, config()), hydrator)
    assert second.cache_hit and dense.calls == sparse.calls == 1
    assert [r.passage.chunk_id for r in second.results] == ["b", "a"]
    assert second.stages["rerank"]["status"] == "cached"

    # Access revoked after caching: PG re-check still removes the chunk.
    hydrator.revoked = {"b"}
    third = await pipe.run(request(llm_gateway, config()), hydrator)
    assert third.cache_hit and [r.passage.chunk_id for r in third.results] == ["a"]
    assert len(hydrator.calls) == 3

    # Another permission scope or org never shares the entry.
    other_scope = await pipe.run(
        request(llm_gateway, config(), principals=("user:u2",)), Hydrator()
    )
    other_org = await pipe.run(request(llm_gateway, config(), org_id="org-2"), Hydrator())
    assert not other_scope.cache_hit and not other_org.cache_hit
    assert dense.calls == 3


async def test_query_embedding_is_cached(llm_gateway: LLMGateway) -> None:
    backends = SearchBackends(vector=MemoryVectorIndex(), text=MemoryTextIndex())
    spec = llm_gateway.default_embedding
    await backends.vector.ensure_collection("kb_chunks_v1", spec.dim)
    pipe = RetrievalPipeline.build(backends, llm_gateway, MemoryCache())
    embedder = llm_gateway.embedding(spec).inner
    assert isinstance(embedder, MockEmbeddingClient)
    cfg = config(sparse={"enabled": False}, cache={"result_ttl_seconds": 0})
    for _ in range(2):
        await pipe.run(request(llm_gateway, cfg), Hydrator())
    assert len(embedder.calls) == 1
    assert embedder.calls[0][0].startswith(cfg.dense.query_instruction)
