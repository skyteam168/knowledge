"""Directed multi-hop over `object_relations` (industrial / structured edges)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import String, and_, cast, func, literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from app.models import ObjectRelation
from app.retrieval.graph import GraphDirection


@dataclass(frozen=True)
class ObjectGraphSeed:
    kind: str
    object_id: str
    object_type: str | None = None


@dataclass(frozen=True)
class ObjectGraphNeighbor:
    kind: str
    object_id: str
    object_type: str | None
    hops: int
    seed_kind: str
    seed_id: str
    seed_object_type: str | None
    path: str
    via_relation_types: str = ""


def _node_key(kind: str, object_id: str, object_type: str | None) -> str:
    return f"{kind}|{(object_type or '').strip()}|{object_id}"


def _edge_parts(
    org_id: str,
    relation_types: Sequence[str] | None,
    direction: GraphDirection,
):
    cond: list[ColumnElement[bool]] = [ObjectRelation.org_id == org_id]
    if relation_types:
        cond.append(ObjectRelation.relation_type.in_(list(relation_types)))
    where = and_(*cond)

    forward = select(
        ObjectRelation.from_kind.label("src_kind"),
        ObjectRelation.from_id.label("src_id"),
        func.coalesce(ObjectRelation.from_object_type, literal("")).label("src_ot"),
        ObjectRelation.to_kind.label("dst_kind"),
        ObjectRelation.to_id.label("dst_id"),
        func.coalesce(ObjectRelation.to_object_type, literal("")).label("dst_ot"),
        ObjectRelation.relation_type.label("relation_type"),
    ).where(where)
    reverse = select(
        ObjectRelation.to_kind.label("src_kind"),
        ObjectRelation.to_id.label("src_id"),
        func.coalesce(ObjectRelation.to_object_type, literal("")).label("src_ot"),
        ObjectRelation.from_kind.label("dst_kind"),
        ObjectRelation.from_id.label("dst_id"),
        func.coalesce(ObjectRelation.from_object_type, literal("")).label("dst_ot"),
        ObjectRelation.relation_type.label("relation_type"),
    ).where(where)
    if direction == "out":
        return forward.cte("obj_edges")
    if direction == "in":
        return reverse.cte("obj_edges")
    return union_all(forward, reverse).cte("obj_edges")


async def traverse_object_relations(
    session: AsyncSession,
    org_id: str,
    seeds: Sequence[ObjectGraphSeed],
    *,
    max_hops: int = 2,
    limit: int = 40,
    relation_types: Sequence[str] | None = None,
    direction: GraphDirection = "out",
) -> list[ObjectGraphNeighbor]:
    """Walk directed object_relations; default direction is outbound (diagnosis chain)."""
    clean = [
        ObjectGraphSeed(
            kind=s.kind.strip().lower(),
            object_id=s.object_id.strip(),
            object_type=(s.object_type or "").strip().lower() or None,
        )
        for s in seeds
        if s.kind.strip() and s.object_id.strip()
    ]
    if not clean or max_hops < 1 or limit < 1:
        return []
    if direction not in ("out", "in", "both"):
        direction = "out"

    seed_selects = []
    for s in clean:
        ot = s.object_type or ""
        seed_selects.append(
            select(
                literal(s.kind).label("kind"),
                literal(s.object_id).label("object_id"),
                literal(ot).label("object_type"),
            )
        )
    seed_cte = union_all(*seed_selects).cte("obj_seeds")
    edge_cte = _edge_parts(org_id, relation_types, direction)

    seed_key = (
        cast(seed_cte.c.kind, String)
        + literal("|")
        + cast(seed_cte.c.object_type, String)
        + literal("|")
        + cast(seed_cte.c.object_id, String)
    )
    walk = select(
        seed_cte.c.kind.label("kind"),
        seed_cte.c.object_id.label("object_id"),
        seed_cte.c.object_type.label("object_type"),
        literal(0).label("hops"),
        seed_cte.c.kind.label("seed_kind"),
        seed_cte.c.object_id.label("seed_id"),
        seed_cte.c.object_type.label("seed_object_type"),
        (literal(",") + seed_key + literal(",")).label("path"),
        literal("").label("via_types"),
    ).cte("obj_walk", recursive=True)
    walk_alias = walk.alias()
    edge_alias = edge_cte.alias()
    dst_key = (
        cast(edge_alias.c.dst_kind, String)
        + literal("|")
        + cast(edge_alias.c.dst_ot, String)
        + literal("|")
        + cast(edge_alias.c.dst_id, String)
    )
    cycle_guard = ~walk_alias.c.path.like(literal("%,") + dst_key + literal(",%"))
    walk = walk.union_all(
        select(
            edge_alias.c.dst_kind.label("kind"),
            edge_alias.c.dst_id.label("object_id"),
            edge_alias.c.dst_ot.label("object_type"),
            (walk_alias.c.hops + 1).label("hops"),
            walk_alias.c.seed_kind.label("seed_kind"),
            walk_alias.c.seed_id.label("seed_id"),
            walk_alias.c.seed_object_type.label("seed_object_type"),
            (walk_alias.c.path + dst_key + literal(",")).label("path"),
            (
                walk_alias.c.via_types
                + literal("|")
                + cast(edge_alias.c.relation_type, String)
            ).label("via_types"),
        ).where(
            and_(
                edge_alias.c.src_kind == walk_alias.c.kind,
                edge_alias.c.src_id == walk_alias.c.object_id,
                edge_alias.c.src_ot == walk_alias.c.object_type,
                walk_alias.c.hops < max_hops,
                cycle_guard,
            )
        )
    )

    hop_rank = (
        select(
            walk.c.kind,
            walk.c.object_id,
            walk.c.object_type,
            walk.c.hops,
            walk.c.seed_kind,
            walk.c.seed_id,
            walk.c.seed_object_type,
            walk.c.path,
            walk.c.via_types,
            func.row_number()
            .over(
                partition_by=(walk.c.kind, walk.c.object_id, walk.c.object_type),
                order_by=(walk.c.hops, walk.c.seed_id),
            )
            .label("rn"),
        )
        .where(walk.c.hops > 0)
        .cte("obj_hop_rank")
    )
    stmt = (
        select(
            hop_rank.c.kind,
            hop_rank.c.object_id,
            hop_rank.c.object_type,
            hop_rank.c.hops,
            hop_rank.c.seed_kind,
            hop_rank.c.seed_id,
            hop_rank.c.seed_object_type,
            hop_rank.c.path,
            hop_rank.c.via_types,
        )
        .where(hop_rank.c.rn == 1)
        .order_by(hop_rank.c.hops, hop_rank.c.kind, hop_rank.c.object_id)
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [
        ObjectGraphNeighbor(
            kind=str(r.kind),
            object_id=str(r.object_id),
            object_type=(str(r.object_type) or None) or None,
            hops=int(r.hops),
            seed_kind=str(r.seed_kind),
            seed_id=str(r.seed_id),
            seed_object_type=(str(r.seed_object_type) or None) or None,
            path=str(r.path or ""),
            via_relation_types=str(r.via_types or "").strip("|"),
        )
        for r in rows
    ]


__all__ = [
    "ObjectGraphNeighbor",
    "ObjectGraphSeed",
    "traverse_object_relations",
    "_node_key",
]
