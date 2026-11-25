"""KO soft warnings + industrial object_relations hard/soft constraints (O2.2)."""

from __future__ import annotations

from dataclasses import dataclass

from app.models.curation import KoRelationType, KoType
from app.models.structured import (
    ObjectEndpointKind,
    ObjectRelationType,
    RelationCardinality,
)

# Suggested (from_types → to_types). Empty frozenset = any type acceptable.
_SOFT: dict[KoRelationType, tuple[frozenset[KoType], frozenset[KoType]]] = {
    KoRelationType.RELATED_TO: (frozenset(), frozenset()),
    KoRelationType.PART_OF: (frozenset(), frozenset()),
    KoRelationType.DEPENDS_ON: (frozenset(), frozenset()),
    KoRelationType.CAUSES: (
        frozenset({KoType.DEFECT}),
        frozenset({KoType.DEVICE, KoType.PROCESS}),
    ),
    KoRelationType.MITIGATES: (
        frozenset({KoType.POLICY, KoType.FAQ, KoType.QA, KoType.POLICY_SUMMARY}),
        frozenset({KoType.DEFECT}),
    ),
    KoRelationType.APPLIES_TO: (
        frozenset({KoType.POLICY, KoType.POLICY_SUMMARY}),
        frozenset({KoType.DEVICE, KoType.PROCESS, KoType.IT_TERM}),
    ),
}


def relation_soft_warnings(
    relation_type: KoRelationType,
    from_ko_type: KoType,
    to_ko_type: KoType,
) -> list[str]:
    """Return human-readable warnings when types diverge from documented guidance."""
    preferred = _SOFT.get(relation_type)
    if preferred is None:
        return []
    from_ok, to_ok = preferred
    warnings: list[str] = []
    if from_ok and from_ko_type not in from_ok:
        expected = ", ".join(sorted(t.value for t in from_ok))
        warnings.append(
            f"本体软约束：关系 {relation_type.value} 建议起点类型为 [{expected}]，"
            f"当前为 {from_ko_type.value}"
        )
    if to_ok and to_ko_type not in to_ok:
        expected = ", ".join(sorted(t.value for t in to_ok))
        warnings.append(
            f"本体软约束：关系 {relation_type.value} 建议终点类型为 [{expected}]，"
            f"当前为 {to_ko_type.value}"
        )
    return warnings


@dataclass(frozen=True, slots=True)
class ObjectRelationConstraint:
    """Domain/range for industrial object_relations (structured object_type)."""

    from_types: frozenset[str]
    to_types: frozenset[str]
    hard: bool
    """When True, violations raise ValidationAppError; else soft warnings only."""


# Pilot core: hard domain/range. Non-core: soft guidance.
_OBJECT_RELATION_CONSTRAINTS: dict[ObjectRelationType, ObjectRelationConstraint] = {
    ObjectRelationType.HAS_PART: ObjectRelationConstraint(
        from_types=frozenset(
            {"site", "area", "line", "equipment", "device", "component"}
        ),
        to_types=frozenset({"area", "line", "equipment", "device", "component"}),
        hard=True,
    ),
    ObjectRelationType.HAS_FAILURE_MODE: ObjectRelationConstraint(
        from_types=frozenset({"equipment", "device", "component"}),
        to_types=frozenset({"failure_mode"}),
        hard=True,
    ),
    ObjectRelationType.CAUSED_BY: ObjectRelationConstraint(
        from_types=frozenset({"failure_mode", "event"}),
        to_types=frozenset(
            {
                "failure_mode",
                "component",
                "equipment",
                "device",
                "material",
                "operation",
            }
        ),
        hard=True,
    ),
    ObjectRelationType.WORK_ORDER_FOR: ObjectRelationConstraint(
        from_types=frozenset({"work_order"}),
        to_types=frozenset({"device", "equipment"}),
        hard=True,
    ),
    ObjectRelationType.SPARE_FOR: ObjectRelationConstraint(
        from_types=frozenset({"spare_part"}),
        to_types=frozenset({"device", "equipment", "component"}),
        hard=True,
    ),
    ObjectRelationType.LOCATED_IN: ObjectRelationConstraint(
        from_types=frozenset(
            {"equipment", "device", "component", "line", "area", "material"}
        ),
        to_types=frozenset({"site", "area", "line"}),
        hard=False,
    ),
    ObjectRelationType.CONSUMES: ObjectRelationConstraint(
        from_types=frozenset({"operation", "equipment", "device", "work_order"}),
        to_types=frozenset({"material", "spare_part"}),
        hard=False,
    ),
}


_DEFAULT_CARDINALITY: dict[ObjectRelationType, RelationCardinality] = {
    ObjectRelationType.HAS_PART: RelationCardinality.ONE_TO_MANY,
    ObjectRelationType.HAS_FAILURE_MODE: RelationCardinality.ONE_TO_MANY,
    ObjectRelationType.CAUSED_BY: RelationCardinality.MANY_TO_ONE,
    ObjectRelationType.WORK_ORDER_FOR: RelationCardinality.MANY_TO_ONE,
    ObjectRelationType.SPARE_FOR: RelationCardinality.MANY_TO_MANY,
    ObjectRelationType.LOCATED_IN: RelationCardinality.MANY_TO_ONE,
    ObjectRelationType.CONSUMES: RelationCardinality.ONE_TO_MANY,
}


def object_relation_constraint(
    relation_type: str | ObjectRelationType,
) -> ObjectRelationConstraint | None:
    try:
        key = (
            relation_type
            if isinstance(relation_type, ObjectRelationType)
            else ObjectRelationType(relation_type.strip().lower())
        )
    except ValueError:
        return None
    return _OBJECT_RELATION_CONSTRAINTS.get(key)


def default_relation_cardinality(
    relation_type: str | ObjectRelationType,
) -> RelationCardinality:
    try:
        key = (
            relation_type
            if isinstance(relation_type, ObjectRelationType)
            else ObjectRelationType(str(relation_type).strip().lower())
        )
    except ValueError:
        return RelationCardinality.ONE_TO_MANY
    return _DEFAULT_CARDINALITY.get(key, RelationCardinality.ONE_TO_MANY)


def cardinality_limits_outgoing(cardinality: str | RelationCardinality) -> bool:
    """True when from-endpoint may have at most one outgoing edge of this type."""
    value = (
        cardinality.value
        if isinstance(cardinality, RelationCardinality)
        else str(cardinality).strip().lower()
    )
    return value in {
        RelationCardinality.ONE_TO_ONE.value,
        RelationCardinality.MANY_TO_ONE.value,
    }


def validate_object_relation_endpoints(
    relation_type: str,
    *,
    from_kind: str,
    from_object_type: str | None,
    to_kind: str,
    to_object_type: str | None,
) -> list[str]:
    """Validate industrial relation domain/range.

    Returns soft warnings. Raises ``ValidationAppError`` for hard violations.
    """
    from app.core.exceptions import ValidationAppError

    constraint = object_relation_constraint(relation_type)
    if constraint is None:
        return []

    structured = ObjectEndpointKind.STRUCTURED.value
    from_ot = (from_object_type or "").strip().lower() or None
    to_ot = (to_object_type or "").strip().lower() or None
    messages: list[str] = []

    def _side_msg(side: str, kind: str, object_type: str | None, allowed: frozenset[str]) -> str:
        expected = ", ".join(sorted(allowed))
        got = f"{kind}:{object_type or '-'}"
        return (
            f"本体约束：关系 {relation_type} 的 {side} 须为 structured 且 "
            f"object_type ∈ [{expected}]，当前为 {got}"
        )

    from_ok = (
        from_kind == structured and from_ot is not None and from_ot in constraint.from_types
    )
    to_ok = to_kind == structured and to_ot is not None and to_ot in constraint.to_types

    if not from_ok:
        messages.append(_side_msg("起点", from_kind, from_ot, constraint.from_types))
    if not to_ok:
        messages.append(_side_msg("终点", to_kind, to_ot, constraint.to_types))

    if not messages:
        return []

    if constraint.hard:
        raise ValidationAppError(
            "Object relation domain/range violation",
            detail={"relation_type": relation_type, "violations": messages},
        )
    return [f"本体软约束：{m.removeprefix('本体约束：')}" for m in messages]
