"""KO relation multi-hop (graph) route: CTE walk + RRF wiring."""

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    KnowledgeBase,
    KnowledgeObject,
    KoEntry,
    KoRelation,
    KoRelationType,
    KoStatus,
    KoVersion,
    KoVersionStatus,
)
from app.models.base import new_id
from app.retrieval.config import RetrievalConfig, Route
from app.retrieval.fusion import rrf_fuse
from app.retrieval.graph import seed_ko_ids_from_hits, traverse_ko_relations
from app.retrieval.retrievers import RouteHit, RouteResult
from app.llm import LLMGateway
from tests.test_retrieval_pipeline import FakeDense, FakeSparse, Hydrator, config, make_pipeline, request

D, S, G = Route.DENSE, Route.SPARSE, Route.GRAPH


def test_seed_ko_ids_from_hits_dedupes_and_skips_chunks() -> None:
    hits = [
        RouteHit("e1", 0.9, {"is_ko": True, "document_id": "ko-a"}),
        RouteHit("c1", 0.8, {"is_ko": False, "document_id": "doc-1"}),
        RouteHit("e2", 0.7, {"is_ko": True, "document_id": "ko-a"}),
        RouteHit("e3", 0.6, {"is_ko": True, "document_id": "ko-b"}),
        RouteHit("e4", 0.5, {}),
    ]
    assert seed_ko_ids_from_hits(hits) == ["ko-a", "ko-b"]


def test_rrf_accepts_graph_as_third_route() -> None:
    fused = rrf_fuse(
        {
            D: [("seed-entry", 0.9)],
            S: [("seed-entry", 10.0)],
            G: [("neighbor-entry", 1.0), ("seed-entry", 0.5)],
        },
        k=60,
        weights={D: 1.0, S: 1.0, G: 1.0},
        ko_ids={"seed-entry", "neighbor-entry"},
    )
    by_id = {c.chunk_id: c for c in fused}
    assert G in by_id["neighbor-entry"].ranks
    assert by_id["neighbor-entry"].ranks[G] == 1
    assert by_id["seed-entry"].ranks[G] == 2
    assert by_id["seed-entry"].is_ko and by_id["neighbor-entry"].is_ko


def test_graph_config_defaults_and_fingerprint() -> None:
    cfg = RetrievalConfig()
    assert cfg.graph.enabled is True and cfg.graph.max_hops == 2
    assert cfg.fusion.weights.get(Route.GRAPH) == 1.0
    off = RetrievalConfig.model_validate({"graph": {"enabled": False, "max_hops": 1}})
    assert off.fingerprint() != cfg.fingerprint()


async def _published_ko(
    session: AsyncSession,
    *,
    org_id: str,
    kb_id: str,
    title: str,
    entry_id: str | None = None,
) -> KnowledgeObject:
    ko = KnowledgeObject(
        id=new_id(),
        org_id=org_id,
        kb_id=kb_id,
        ko_type="faq",
        title=title,
        question=f"Q:{title}",
        variants=[],
        answer=f"A:{title}",
        sources=[],
        status=KoStatus.PUBLISHED.value,
        version=1,
        published_version=1,
        acl_inherit=True,
        gap_ids=[],
        ai_draft={},
        conflicts=[],
        origin="manual",
    )
    session.add(ko)
    await session.flush()
    session.add(
        KoVersion(
            id=new_id(),
            org_id=org_id,
            ko_id=ko.id,
            version=1,
            ko_type=ko.ko_type,
            title=ko.title,
            question=ko.question,
            variants=[],
            answer=ko.answer,
            sources=[],
            status=KoVersionStatus.PUBLISHED.value,
        )
    )
    session.add(
        KoEntry(
            id=entry_id or new_id(),
            org_id=org_id,
            ko_id=ko.id,
            ko_version=1,
            seq=0,
            question=ko.question,
        )
    )
    await session.flush()
    return ko


async def test_traverse_ko_relations_bidirectional_hops(session: AsyncSession) -> None:
    org_id = "org-graph"
    kb = KnowledgeBase(id=new_id(), org_id=org_id, name="graph-kb", visibility="org")
    session.add(kb)
    await session.flush()

    a = await _published_ko(session, org_id=org_id, kb_id=kb.id, title="A", entry_id="a" * 32)
    b = await _published_ko(session, org_id=org_id, kb_id=kb.id, title="B", entry_id="b" * 32)
    c = await _published_ko(session, org_id=org_id, kb_id=kb.id, title="C", entry_id="c" * 32)
    # A -> B -> C (directed); walk is bidirectional so seed C also reaches A.
    session.add(
        KoRelation(
            id=new_id(),
            org_id=org_id,
            from_ko_id=a.id,
            to_ko_id=b.id,
            relation_type=KoRelationType.RELATED_TO.value,
        )
    )
    session.add(
        KoRelation(
            id=new_id(),
            org_id=org_id,
            from_ko_id=b.id,
            to_ko_id=c.id,
            relation_type=KoRelationType.DEPENDS_ON.value,
        )
    )
    await session.commit()

    from_a = await traverse_ko_relations(session, org_id, [a.id], max_hops=2, limit=10)
    by_id = {n.ko_id: n for n in from_a}
    assert set(by_id) == {b.id, c.id}
    assert by_id[b.id].hops == 1 and by_id[b.id].entry_id == "b" * 32
    assert by_id[c.id].hops == 2 and by_id[c.id].entry_id == "c" * 32

    hop1 = await traverse_ko_relations(session, org_id, [a.id], max_hops=1, limit=10)
    assert {n.ko_id for n in hop1} == {b.id}

    from_c = await traverse_ko_relations(session, org_id, [c.id], max_hops=2, limit=10)
    assert {n.ko_id for n in from_c} == {b.id, a.id}


class FakeGraph:
    def __init__(self, hits: Sequence[RouteHit], *, fail: bool = False) -> None:
        self.hits = list(hits)
        self.fail = fail
        self.seeds: list[str] = []

    async def retrieve(
        self, seed_ko_ids: Sequence[str], flt: object, cfg: object
    ) -> RouteResult:
        self.seeds = list(seed_ko_ids)
        if self.fail:
            raise RuntimeError("graph down")
        return RouteResult(Route.GRAPH, self.hits, took_ms=1.0, info={"kept": len(self.hits)})


async def test_pipeline_fuses_graph_hits(llm_gateway: LLMGateway) -> None:
    class KoDense(FakeDense):
        async def retrieve(self, *args: object, **kwargs: object) -> RouteResult:
            out = await super().retrieve(*args, **kwargs)
            return RouteResult(
                Route.DENSE,
                [
                    RouteHit(h.chunk_id, h.score, {"is_ko": True, "document_id": "ko-seed"})
                    for h in out.hits
                ],
                took_ms=out.took_ms,
            )

    class SparseOnlyDoc(FakeSparse):
        async def retrieve(self, *args: object, **kwargs: object) -> RouteResult:
            return RouteResult(
                Route.SPARSE,
                [RouteHit("doc-chunk", 5.0, {"is_ko": False})],
                took_ms=1.0,
            )

    graph = FakeGraph(
        [RouteHit("neighbor-entry", 1.0, {"is_ko": True, "document_id": "ko-n", "hops": 1})]
    )
    pipe = make_pipeline(llm_gateway, KoDense(["seed-entry"]), SparseOnlyDoc(["doc-chunk"]))
    out = await pipe.run(
        request(llm_gateway, config(rerank={"enabled": False}, top_k=5)),
        Hydrator(),
        graph=graph,
    )
    assert graph.seeds == ["ko-seed"]
    ids = {r.passage.chunk_id for r in out.results}
    assert "neighbor-entry" in ids and "seed-entry" in ids
    assert out.stages["routes"]["graph"]["status"] == "ok"
    assert out.stages["routes"]["graph"]["hits"][0]["hops"] == 1
    neighbor = next(r for r in out.results if r.passage.chunk_id == "neighbor-entry")
    assert neighbor.candidate.ranks.get(Route.GRAPH) == 1
    assert neighbor.candidate.is_ko


async def test_pipeline_graph_failure_degrades(llm_gateway: LLMGateway) -> None:
    class KoDense(FakeDense):
        async def retrieve(self, *args: object, **kwargs: object) -> RouteResult:
            out = await super().retrieve(*args, **kwargs)
            return RouteResult(
                Route.DENSE,
                [
                    RouteHit(h.chunk_id, h.score, {"is_ko": True, "document_id": "ko-seed"})
                    for h in out.hits
                ],
                took_ms=out.took_ms,
            )

    pipe = make_pipeline(llm_gateway, KoDense(["a"]), FakeSparse(["a"]))
    out = await pipe.run(
        request(llm_gateway, config(rerank={"enabled": False})),
        Hydrator(),
        graph=FakeGraph([], fail=True),
    )
    assert out.degraded == ["graph:error: RuntimeError"]
    assert out.stages["routes"]["graph"]["status"] != "ok"
    assert [r.passage.chunk_id for r in out.results]
