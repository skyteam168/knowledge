"""Diagnosis-oriented directed graph expansion (O3.2).

Uses outbound walks over industrial object_relations and KO relations
(hasFailureMode / causedBy / mitigates …). KO neighbours are ACL-checked via
``KoAccess.live_objects`` before they may enter evidence.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.curation import KoRelationType
from app.models.structured import ObjectRelationType
from app.retrieval.graph import GraphNeighbor, traverse_ko_relations
from app.retrieval.object_graph import (
    ObjectGraphNeighbor,
    ObjectGraphSeed,
    traverse_object_relations,
)
from app.services.authz import CurrentUser
from app.services.knowledge.ko_access import KoAccess

DIAGNOSIS_OBJECT_RELATION_TYPES: tuple[str, ...] = (
    ObjectRelationType.HAS_FAILURE_MODE.value,
    ObjectRelationType.CAUSED_BY.value,
    ObjectRelationType.WORK_ORDER_FOR.value,
    ObjectRelationType.SPARE_FOR.value,
    ObjectRelationType.HAS_PART.value,
)

# Outbound: defect/device causes / depends_on chains.
DIAGNOSIS_KO_OUT_TYPES: tuple[str, ...] = (
    KoRelationType.CAUSES.value,
    KoRelationType.DEPENDS_ON.value,
)
# Inbound: policy/faq mitigates ← defect (edge stored policy→defect).
DIAGNOSIS_KO_IN_TYPES: tuple[str, ...] = (KoRelationType.MITIGATES.value,)

DIAGNOSIS_KO_RELATION_TYPES: tuple[str, ...] = (
    *DIAGNOSIS_KO_OUT_TYPES,
    *DIAGNOSIS_KO_IN_TYPES,
)


@dataclass(frozen=True)
class DiagnosisExpansion:
    object_neighbors: list[ObjectGraphNeighbor]
    ko_neighbors: list[GraphNeighbor]
    dropped_acl_ko_ids: list[str]


async def expand_diagnosis_graph(
    session: AsyncSession,
    user: CurrentUser,
    *,
    object_seeds: Sequence[ObjectGraphSeed] = (),
    ko_seeds: Sequence[str] = (),
    max_hops: int = 2,
    limit: int = 40,
    kb_ids: Sequence[str] = (),
) -> DiagnosisExpansion:
    """Diagnosis walk; KO hits filtered by live ACL before evidence use."""
    object_neighbors = (
        await traverse_object_relations(
            session,
            user.org_id,
            object_seeds,
            max_hops=max_hops,
            limit=limit,
            relation_types=list(DIAGNOSIS_OBJECT_RELATION_TYPES),
            direction="out",
        )
        if object_seeds
        else []
    )
    raw_kos: list[GraphNeighbor] = []
    if ko_seeds:
        out_kos = await traverse_ko_relations(
            session,
            user.org_id,
            ko_seeds,
            max_hops=max_hops,
            limit=limit,
            kb_ids=kb_ids,
            relation_types=list(DIAGNOSIS_KO_OUT_TYPES),
            direction="out",
        )
        in_kos = await traverse_ko_relations(
            session,
            user.org_id,
            ko_seeds,
            max_hops=max_hops,
            limit=limit,
            kb_ids=kb_ids,
            relation_types=list(DIAGNOSIS_KO_IN_TYPES),
            direction="in",
        )
        by_id: dict[str, GraphNeighbor] = {}
        for n in (*out_kos, *in_kos):
            prev = by_id.get(n.ko_id)
            if prev is None or n.hops < prev.hops:
                by_id[n.ko_id] = n
        raw_kos = sorted(by_id.values(), key=lambda n: (n.hops, n.ko_id))[:limit]
    if not raw_kos:
        return DiagnosisExpansion(object_neighbors, [], [])

    kos = KoAccess(session)
    check = await kos.live_objects(user, [n.ko_id for n in raw_kos])
    allowed = set(check.objects)
    kept = [n for n in raw_kos if n.ko_id in allowed]
    dropped = [n.ko_id for n in raw_kos if n.ko_id not in allowed]
    return DiagnosisExpansion(object_neighbors, kept, dropped)
