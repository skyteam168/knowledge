"""Documented soft constraints for KO relation types (warnings only, never hard-block)."""

from __future__ import annotations

from app.models.curation import KoRelationType, KoType

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
