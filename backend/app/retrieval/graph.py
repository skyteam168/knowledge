"""KO relation multi-hop retrieval (RRF third route) via recursive CTE.

Seeds are published KO ids already found by dense / sparse. Neighbours are walked
on `ko_relations` with configurable direction (out / in / both), ACL-checked the
same way as KO hydration, and emitted as their published primary entry (seq=0)
chunk ids for fusion.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import String, and_, cast, func, literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from app.models import KnowledgeObject, KoEntry, KoRelation, KoStatus
from app.retrieval.config import GraphConfig, Route
from app.retrieval.filters import SearchFilter
from app.retrieval.retrievers import RouteHit, RouteResult
from app.services.authz import CurrentUser
from app.services.knowledge.ko_access import KoAccess

GraphDirection = Literal["out", "in", "both"]


@dataclass(frozen=True)
class GraphNeighbor:
    ko_id: str
    hops: int
    entry_id: str
    seed_ko_id: str
    path: str = ""


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 2)


def _seed_cte(seed_ko_ids: Sequence[str]):
    parts = [select(literal(kid).label("ko_id")) for kid in seed_ko_ids]
    return union_all(*parts).cte("seeds")


def _edge_cte(
    org_id: str,
    relation_types: Sequence[str] | None,
    direction: GraphDirection,
):
    cond: list[ColumnElement[bool]] = [KoRelation.org_id == org_id]
    if relation_types:
        cond.append(KoRelation.relation_type.in_(list(relation_types)))
    where = and_(*cond)
    forward = select(
        KoRelation.from_ko_id.label("src"),
        KoRelation.to_ko_id.label("dst"),
        KoRelation.relation_type.label("relation_type"),
    ).where(where)
    reverse = select(
        KoRelation.to_ko_id.label("src"),
        KoRelation.from_ko_id.label("dst"),
        KoRelation.relation_type.label("relation_type"),
    ).where(where)
    if direction == "out":
        return forward.cte("edges")
    if direction == "in":
        return reverse.cte("edges")
    return union_all(forward, reverse).cte("edges")


async def traverse_ko_relations(
    session: AsyncSession,
    org_id: str,
    seed_ko_ids: Sequence[str],
    *,
    max_hops: int = 2,
    limit: int = 40,
    kb_ids: Sequence[str] = (),
    relation_types: Sequence[str] | None = None,
    direction: GraphDirection = "both",
) -> list[GraphNeighbor]:
    """Return distinct published KO neighbours within `max_hops` (excluding seeds)."""
    seeds = list(dict.fromkeys(kid for kid in seed_ko_ids if kid))
    if not seeds or max_hops < 1 or limit < 1:
        return []
    if direction not in ("out", "in", "both"):
        direction = "both"

    seed_cte = _seed_cte(seeds)
    edge_cte = _edge_cte(org_id, relation_types, direction)

    # path is ",id1,id2," so LIKE '%,id,%' detects cycles on both SQLite and PG.
    walk = select(
        seed_cte.c.ko_id.label("ko_id"),
        literal(0).label("hops"),
        seed_cte.c.ko_id.label("seed_id"),
        (literal(",") + cast(seed_cte.c.ko_id, String) + literal(",")).label("path"),
    ).cte("walk", recursive=True)
    walk_alias = walk.alias()
    edge_alias = edge_cte.alias()
    cycle_guard = ~walk_alias.c.path.like(
        literal("%,") + cast(edge_alias.c.dst, String) + literal(",%")
    )
    walk = walk.union_all(
        select(
            edge_alias.c.dst.label("ko_id"),
            (walk_alias.c.hops + 1).label("hops"),
            walk_alias.c.seed_id.label("seed_id"),
            (
                walk_alias.c.path + cast(edge_alias.c.dst, String) + literal(",")
            ).label("path"),
        ).where(
            edge_alias.c.src == walk_alias.c.ko_id,
            walk_alias.c.hops < max_hops,
            cycle_guard,
        )
    )

    hop_rank = (
        select(
            walk.c.ko_id,
            walk.c.seed_id,
            walk.c.hops,
            walk.c.path,
            func.row_number()
            .over(partition_by=walk.c.ko_id, order_by=(walk.c.hops, walk.c.seed_id))
            .label("rn"),
        )
        .where(walk.c.hops > 0)
        .cte("hop_rank")
    )
    best = (
        select(
            hop_rank.c.ko_id, hop_rank.c.seed_id, hop_rank.c.hops, hop_rank.c.path
        )
        .where(hop_rank.c.rn == 1)
        .cte("best")
    )

    ko_ok = and_(
        KnowledgeObject.org_id == org_id,
        KnowledgeObject.published_version.is_not(None),
        KnowledgeObject.status != KoStatus.DEPRECATED.value,
    )
    if kb_ids:
        ko_ok = and_(ko_ok, KnowledgeObject.kb_id.in_(list(kb_ids)))

    stmt = (
        select(
            best.c.ko_id,
            best.c.hops,
            best.c.seed_id,
            best.c.path,
            KoEntry.id.label("entry_id"),
        )
        .join(KnowledgeObject, KnowledgeObject.id == best.c.ko_id)
        .join(
            KoEntry,
            and_(
                KoEntry.ko_id == KnowledgeObject.id,
                KoEntry.ko_version == KnowledgeObject.published_version,
                KoEntry.seq == 0,
            ),
        )
        .where(ko_ok)
        .order_by(best.c.hops, best.c.ko_id)
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [
        GraphNeighbor(
            ko_id=str(r.ko_id),
            hops=int(r.hops),
            entry_id=str(r.entry_id),
            seed_ko_id=str(r.seed_id),
            path=str(r.path or ""),
        )
        for r in rows
    ]


def seed_ko_ids_from_hits(hits: Sequence[RouteHit]) -> list[str]:
    """KO document_ids from index hits (payload is_ko / document_id)."""
    out: list[str] = []
    seen: set[str] = set()
    for hit in hits:
        if not hit.payload.get("is_ko"):
            continue
        ko_id = hit.payload.get("document_id")
        if isinstance(ko_id, str) and ko_id and ko_id not in seen:
            seen.add(ko_id)
            out.append(ko_id)
    return out


class GraphRetriever:
    """PG multi-hop over ko_relations; ACL via KoAccess (same gate as hydration)."""

    def __init__(self, session: AsyncSession, user: CurrentUser) -> None:
        self.session = session
        self.user = user
        self.kos = KoAccess(session)

    async def retrieve(
        self,
        seed_ko_ids: Sequence[str],
        flt: SearchFilter,
        cfg: GraphConfig,
    ) -> RouteResult:
        start = time.perf_counter()
        if not cfg.enabled or not seed_ko_ids:
            return RouteResult(route=Route.GRAPH, hits=[], took_ms=_ms(start), info={"seeds": 0})

        direction: GraphDirection = cfg.direction if cfg.direction in ("out", "in", "both") else "both"
        neighbors = await traverse_ko_relations(
            self.session,
            flt.acl.org_id,
            seed_ko_ids,
            max_hops=cfg.max_hops,
            limit=cfg.top_k,
            kb_ids=flt.acl.kb_ids,
            relation_types=cfg.relation_types or None,
            direction=direction,
        )
        if not neighbors:
            return RouteResult(
                route=Route.GRAPH,
                hits=[],
                took_ms=_ms(start),
                info={"seeds": len(list(seed_ko_ids)), "raw": 0, "kept": 0},
            )

        check = await self.kos.live_objects(self.user, [n.ko_id for n in neighbors])
        allowed = set(check.objects)

        hits: list[RouteHit] = []
        for n in neighbors:
            if n.ko_id not in allowed:
                continue
            hits.append(
                RouteHit(
                    chunk_id=n.entry_id,
                    score=1.0 / n.hops,
                    payload={
                        "document_id": n.ko_id,
                        "is_ko": True,
                        "hops": n.hops,
                        "seed_ko_id": n.seed_ko_id,
                        "path": n.path,
                    },
                )
            )
            if len(hits) >= cfg.top_k:
                break

        return RouteResult(
            route=Route.GRAPH,
            hits=hits,
            took_ms=_ms(start),
            info={
                "seeds": len(list(dict.fromkeys(seed_ko_ids))),
                "raw": len(neighbors),
                "kept": len(hits),
                "max_hops": cfg.max_hops,
                "direction": direction,
                "dropped_acl": sum(1 for n in neighbors if n.ko_id not in allowed),
            },
        )
