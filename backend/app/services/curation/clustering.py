"""Incremental clustering of knowledge gaps on question embeddings.

Each new gap joins the most similar recent cluster of its org / knowledge base when the
cosine similarity to the cluster centroid reaches the threshold, else it starts a cluster.
Within a cluster, a gap asking the identical (normalized) question as an active gap is
folded into it: status=duplicate and the primary gap's occurrences grow.
"""

import hashlib
import logging
import math
import re
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.llm import EmbeddingSpec, LLMGateway
from app.llm.usage import FEATURE_CURATION, STAGE_CLUSTER, usage_scope
from app.models import GapCluster, GapStatus, KnowledgeGap
from app.models.base import utcnow
from app.repositories.curation_repo import GapClusterRepository, GapRepository
from app.schemas.curation import ClusterRunOut

logger = logging.getLogger(__name__)

_SPACE = re.compile(r"\s+")
_TRAILING = re.compile(r"[\s?？!！。.,，;；:：~～]+$")


def normalize_question(text: str) -> str:
    return _TRAILING.sub("", _SPACE.sub(" ", text.strip().lower()))


def question_hash(text: str) -> str:
    return hashlib.sha256(normalize_question(text).encode()).hexdigest()


def gap_text(gap: KnowledgeGap) -> str:
    return (gap.rewritten_query or gap.query or "").strip()


def _unit(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return -1.0
    return sum(x * y for x, y in zip(a, b, strict=True))


async def refresh_cluster_stats(session: AsyncSession, cluster_id: str | None) -> None:
    if cluster_id is None:
        return
    cluster = await session.get(GapCluster, cluster_id)
    if cluster is None:
        return
    await session.flush()
    gap_count, occurrences, open_count, sources, last = await GapClusterRepository(session).stats(
        cluster_id
    )
    cluster.gap_count = gap_count
    cluster.occurrences = occurrences
    cluster.open_count = open_count
    cluster.sources = sources
    if last is not None:
        cluster.last_seen_at = last


@dataclass
class _Stats:
    processed: int = 0
    clustered: int = 0
    new_clusters: int = 0
    folded: int = 0

    def out(self) -> ClusterRunOut:
        return ClusterRunOut(
            processed=self.processed,
            clustered=self.clustered,
            new_clusters=self.new_clusters,
            folded=self.folded,
        )


class GapClusterer:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        gateway: LLMGateway,
        settings: Settings,
    ) -> None:
        self.session_factory = session_factory
        self.gateway = gateway
        self.settings = settings

    async def run_once(self, org_id: str | None = None) -> ClusterRunOut:
        """Cluster pending gaps (of one org, or all tenants) in batches until none is left."""
        total = _Stats()
        while True:
            async with self.session_factory() as session:
                stats = await self._batch(session, org_id)
                await session.commit()
            total.processed += stats.processed
            total.clustered += stats.clustered
            total.new_clusters += stats.new_clusters
            total.folded += stats.folded
            if stats.processed < self.settings.gap_cluster_batch_size:
                break
        if total.processed:
            logger.info("gap_clustering_done", extra=total.out().model_dump())
        return total.out()

    async def _embed(self, spec: EmbeddingSpec, gaps: list[KnowledgeGap]) -> list[list[float]]:
        """One call per org so the usage is attributed to the tenant; input order is kept."""
        by_org: dict[str, list[int]] = {}
        for i, g in enumerate(gaps):
            by_org.setdefault(g.org_id, []).append(i)
        vectors: list[list[float]] = [[] for _ in gaps]
        client = self.gateway.embedding(spec)
        for org, idx in by_org.items():
            with usage_scope(feature=FEATURE_CURATION, stage=STAGE_CLUSTER, org_id=org):
                out = await client.embed([normalize_question(gap_text(gaps[i])) for i in idx])
            for i, vec in zip(idx, out, strict=True):
                vectors[i] = vec
        return vectors

    async def _batch(self, session: AsyncSession, org_id: str | None) -> _Stats:
        stats = _Stats()
        batch = await GapRepository(session).unclustered(
            self.settings.gap_cluster_batch_size, org_id
        )
        gaps = [g for g in batch if gap_text(g)]
        # Blank questions cannot be embedded: park them in no cluster but stop retrying.
        for g in batch:
            if not gap_text(g):
                g.query_hash = ""
        stats.processed = len(batch) - len(gaps)
        if not gaps:
            return stats
        spec = self.gateway.default_embedding
        vectors = await self._embed(spec, gaps)

        clusters_repo = GapClusterRepository(session)
        since = utcnow() - timedelta(days=self.settings.gap_cluster_window_days)
        pools: dict[tuple[str, str | None], list[GapCluster]] = {}
        touched: set[str] = set()
        threshold = self.settings.gap_cluster_similarity
        for gap, raw in zip(gaps, vectors, strict=True):
            vec = _unit(raw)
            key = (gap.org_id, gap.kb_id)
            if key not in pools:
                pools[key] = await clusters_repo.candidates(
                    gap.org_id, gap.kb_id, spec.model, spec.dim, since
                )
            best: GapCluster | None = None
            best_score = -1.0
            for cluster in pools[key]:
                score = cosine(vec, cluster.centroid)
                if score > best_score:
                    best, best_score = cluster, score
            if best is None or best_score < threshold:
                best = GapCluster(
                    org_id=gap.org_id,
                    kb_id=gap.kb_id,
                    representative_query=gap_text(gap)[:2000],
                    centroid=vec,
                    embedding_model=spec.model,
                    embedding_dim=spec.dim,
                    gap_count=0,
                    occurrences=0,
                    open_count=0,
                    sources={},
                    last_seen_at=gap.last_seen_at,
                )
                session.add(best)
                await session.flush()
                pools[key].append(best)
                stats.new_clusters += 1
            else:
                n = max(1, best.gap_count)
                best.centroid = _unit([c * n + v for c, v in zip(best.centroid, vec, strict=True)])
                best.gap_count = n + 1
            gap.cluster_id = best.id
            gap.query_hash = question_hash(gap_text(gap))
            touched.add(best.id)
            stats.processed += 1
            stats.clustered += 1
            await session.flush()

            primary = await GapRepository(session).primary_in_cluster(
                best.id, gap.query_hash, gap.id
            )
            if primary is not None:
                primary.occurrences += gap.occurrences
                if gap.last_seen_at > primary.last_seen_at:
                    primary.last_seen_at = gap.last_seen_at
                gap.status = GapStatus.DUPLICATE.value
                gap.duplicate_of_id = primary.id
                gap.resolution = {"action": "duplicate", "auto": True}
                gap.resolved_at = utcnow()
                stats.folded += 1

        for cluster_id in sorted(touched):
            await refresh_cluster_stats(session, cluster_id)
        return stats
