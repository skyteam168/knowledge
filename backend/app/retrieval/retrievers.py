"""Dense (Qdrant) and sparse (OpenSearch BM25) retrievers; each returns ranked route hits."""

import time
from dataclasses import dataclass, field
from typing import Any

from app.core.metrics import cache_lookup
from app.llm import EmbeddingSpec, LLMGateway
from app.retrieval.backends import TextIndex, VectorIndex
from app.retrieval.cache import EmbeddingCache
from app.retrieval.config import DenseConfig, Route, SparseConfig
from app.retrieval.filters import SearchFilter
from app.retrieval.highlight import POST_TAG, PRE_TAG
from app.retrieval.query import ParsedQuery

PAYLOAD_FIELDS = (
    "document_id",
    "kb_id",
    "doc_version",
    "heading_path",
    "page_start",
    "page_end",
    "is_ko",
)


@dataclass(frozen=True)
class SearchTarget:
    """Physical collection / index of the active generation and its embedding space."""

    generation: int
    collection: str
    index: str
    embedding: EmbeddingSpec


@dataclass(frozen=True)
class RouteHit:
    chunk_id: str
    score: float
    payload: dict[str, Any] = field(default_factory=dict)
    highlight: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class RouteResult:
    route: Route
    hits: list[RouteHit]
    took_ms: float
    info: dict[str, Any] = field(default_factory=dict)


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 2)


class DenseRetriever:
    def __init__(self, index: VectorIndex, gateway: LLMGateway, cache: EmbeddingCache) -> None:
        self.index = index
        self.gateway = gateway
        self.cache = cache

    @staticmethod
    def query_text(query: ParsedQuery, cfg: DenseConfig) -> str:
        return f"{cfg.query_instruction}{query.text}"

    async def embed_query(
        self, text: str, spec: EmbeddingSpec, ttl_seconds: int
    ) -> tuple[list[float], bool]:
        cached = await self.cache.get(spec, text)
        cache_lookup("query_embedding", cached is not None)
        if cached is not None:
            return cached, True
        (vector,) = await self.gateway.embedding(spec).embed([text])
        await self.cache.set(spec, text, vector, ttl_seconds)
        return vector, False

    async def retrieve(
        self,
        query: ParsedQuery,
        flt: SearchFilter,
        target: SearchTarget,
        cfg: DenseConfig,
        *,
        embedding_ttl_seconds: int,
    ) -> RouteResult:
        start = time.perf_counter()
        vector, cached = await self.embed_query(
            self.query_text(query, cfg), target.embedding, embedding_ttl_seconds
        )
        embed_ms = _ms(start)
        hits = await self.index.search(
            target.collection, vector, flt.to_qdrant(), cfg.top_k, hnsw_ef=cfg.hnsw_ef
        )
        if cfg.score_threshold is not None:
            hits = [h for h in hits if h.score >= cfg.score_threshold]
        return RouteResult(
            route=Route.DENSE,
            hits=[
                RouteHit(
                    chunk_id=h.chunk_id,
                    score=h.score,
                    payload={k: h.payload.get(k) for k in PAYLOAD_FIELDS if k in h.payload},
                )
                for h in hits
            ],
            took_ms=_ms(start),
            info={
                "embedding_cached": cached,
                "embed_ms": embed_ms,
                "model": target.embedding.model,
            },
        )


class SparseRetriever:
    def __init__(self, index: TextIndex) -> None:
        self.index = index

    @staticmethod
    def build_body(query: ParsedQuery, flt: SearchFilter, cfg: SparseConfig) -> dict[str, Any]:
        multi_match: dict[str, Any] = {
            "query": query.text,
            "fields": [f"{name}^{boost:g}" for name, boost in cfg.field_boosts.items()],
            "type": "best_fields",
        }
        if cfg.minimum_should_match:
            multi_match["minimum_should_match"] = cfg.minimum_should_match
        should: list[dict[str, Any]] = []
        if cfg.phrase_boost > 0:
            for term in query.exact_terms:
                for name in ("title", "content"):
                    if name in cfg.field_boosts:
                        should.append(
                            {"match_phrase": {name: {"query": term, "boost": cfg.phrase_boost}}}
                        )
        bool_query: dict[str, Any] = {
            "filter": flt.to_opensearch(),
            "must": [{"multi_match": multi_match}],
        }
        if should:
            bool_query["should"] = should
        return {
            "size": cfg.top_k,
            "track_total_hits": False,
            "_source": list(PAYLOAD_FIELDS),
            "query": {"bool": bool_query},
            "highlight": {
                "encoder": "html",
                "pre_tags": [PRE_TAG],
                "post_tags": [POST_TAG],
                "fields": {
                    "content": {"fragment_size": cfg.fragment_size, "number_of_fragments": 2},
                    "title": {"number_of_fragments": 0},
                    "heading_path": {"number_of_fragments": 0},
                },
            },
        }

    async def retrieve(
        self, query: ParsedQuery, flt: SearchFilter, target: SearchTarget, cfg: SparseConfig
    ) -> RouteResult:
        start = time.perf_counter()
        hits = await self.index.search(target.index, self.build_body(query, flt, cfg))
        return RouteResult(
            route=Route.SPARSE,
            hits=[
                RouteHit(
                    chunk_id=h.chunk_id,
                    score=h.score,
                    payload={k: h.source.get(k) for k in PAYLOAD_FIELDS if k in h.source},
                    highlight=h.highlight,
                )
                for h in hits
            ],
            took_ms=_ms(start),
            info={"exact_terms": list(query.exact_terms)},
        )
