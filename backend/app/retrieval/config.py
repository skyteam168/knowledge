"""Retrieval strategy: everything tunable per profile (stored as JSON in retrieval_profiles)."""

import hashlib
import json
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.config import Settings


class Route(StrEnum):
    DENSE = "dense"
    SPARSE = "sparse"


SPARSE_FIELDS = ("title", "heading_path", "content")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DenseConfig(_Strict):
    enabled: bool = True
    top_k: int = Field(default=40, ge=1, le=200)
    # Prepended to the query before embedding (Qwen3-Embedding expects
    # "Instruct: <task>\nQuery:<query>"); documents are embedded without it.
    query_instruction: str = Field(default="", max_length=1000)
    hnsw_ef: int | None = Field(default=None, ge=1, le=2048)
    score_threshold: float | None = Field(default=None, ge=-1, le=1)
    timeout_seconds: float = Field(default=5.0, gt=0, le=60)


class SparseConfig(_Strict):
    enabled: bool = True
    top_k: int = Field(default=40, ge=1, le=200)
    field_boosts: dict[str, float] = Field(
        default_factory=lambda: {"title": 3.0, "heading_path": 2.0, "content": 1.0}
    )
    # Extra score for exact phrase hits of quoted text / codes (e.g. "HR-2024-001").
    phrase_boost: float = Field(default=2.0, ge=0, le=100)
    minimum_should_match: str | None = Field(default=None, max_length=16)
    fragment_size: int = Field(default=160, ge=40, le=1000)
    timeout_seconds: float = Field(default=5.0, gt=0, le=60)

    @field_validator("field_boosts")
    @classmethod
    def _known_fields(cls, value: dict[str, float]) -> dict[str, float]:
        unknown = set(value) - set(SPARSE_FIELDS)
        if unknown:
            raise ValueError(f"unknown fields {sorted(unknown)}; allowed: {list(SPARSE_FIELDS)}")
        if not value or any(b <= 0 for b in value.values()):
            raise ValueError("at least one field with a positive boost is required")
        return value


class FusionConfig(_Strict):
    k: int = Field(default=60, ge=1, le=1000)
    weights: dict[Route, float] = Field(
        default_factory=lambda: {Route.DENSE: 1.0, Route.SPARSE: 1.0}
    )

    @field_validator("weights")
    @classmethod
    def _non_negative(cls, value: dict[Route, float]) -> dict[Route, float]:
        if any(w < 0 for w in value.values()):
            raise ValueError("weights must be >= 0")
        return value

    def weight(self, route: Route) -> float:
        return self.weights.get(route, 1.0)


class RerankConfig(_Strict):
    enabled: bool = True
    top_n: int = Field(default=40, ge=1, le=200)
    batch_size: int = Field(default=16, ge=1, le=128)
    concurrency: int = Field(default=4, ge=1, le=32)
    timeout_seconds: float = Field(default=8.0, gt=0, le=120)
    # Passage text sent to the reranker is cut to this many characters.
    max_chars: int = Field(default=2000, ge=100, le=20000)


class CacheConfig(_Strict):
    embedding_ttl_seconds: int = Field(default=7 * 24 * 3600, ge=0)
    # 0 disables the result cache.
    result_ttl_seconds: int = Field(default=60, ge=0, le=24 * 3600)


class KoBoostConfig(_Strict):
    """Curated knowledge objects (is_ko) are preferred over raw document chunks."""

    enabled: bool = True
    # Multiplier of a KO entry's RRF score.
    rrf_weight: float = Field(default=1.5, ge=0, le=10)
    # Added to a KO entry's rerank score (rerank scores are roughly in [0, 1]).
    rerank_bonus: float = Field(default=0.1, ge=-1, le=1)


class RetrievalConfig(_Strict):
    dense: DenseConfig = Field(default_factory=DenseConfig)
    sparse: SparseConfig = Field(default_factory=SparseConfig)
    fusion: FusionConfig = Field(default_factory=FusionConfig)
    rerank: RerankConfig = Field(default_factory=RerankConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    ko: KoBoostConfig = Field(default_factory=KoBoostConfig)
    top_k: int = Field(default=10, ge=1, le=100)

    @model_validator(mode="after")
    def _one_route(self) -> "RetrievalConfig":
        if not (self.dense.enabled or self.sparse.enabled):
            raise ValueError("at least one of dense / sparse retrieval must be enabled")
        return self

    @classmethod
    def from_settings(cls, settings: Settings) -> "RetrievalConfig":
        return cls(
            dense=DenseConfig(
                top_k=settings.retrieval_dense_top_k,
                query_instruction=settings.retrieval_query_instruction,
            ),
            sparse=SparseConfig(top_k=settings.retrieval_sparse_top_k),
            fusion=FusionConfig(k=settings.retrieval_rrf_k),
            rerank=RerankConfig(
                enabled=settings.retrieval_rerank_enabled, top_n=settings.retrieval_rerank_top_n
            ),
            cache=CacheConfig(
                embedding_ttl_seconds=settings.retrieval_embedding_cache_ttl_seconds,
                result_ttl_seconds=settings.retrieval_result_cache_ttl_seconds,
            ),
            ko=KoBoostConfig(
                enabled=settings.retrieval_ko_boost_enabled,
                rrf_weight=settings.retrieval_ko_rrf_weight,
                rerank_bonus=settings.retrieval_ko_rerank_bonus,
            ),
            top_k=settings.retrieval_top_k,
        )

    def fingerprint(self) -> str:
        """Stable hash of the settings that influence results (cache keys, traces)."""
        data = self.model_dump(mode="json", exclude={"cache"})
        raw = json.dumps(data, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]
