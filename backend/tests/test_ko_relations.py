"""KO light ontology: extended KoType and relation edges."""

from datetime import UTC, datetime

from app.models import KoRelationType, KoStatus, KoType
from app.schemas.curation import KoRelationCreate, KoRelationOut


def test_ko_type_includes_business_kinds() -> None:
    values = {t.value for t in KoType}
    assert {"faq", "qa", "card", "policy_summary"} <= values
    assert {"device", "process", "defect", "policy", "it_term"} <= values


def test_relation_types_are_constrained() -> None:
    assert KoRelationType.RELATED_TO.value == "related_to"
    data = KoRelationCreate(to_ko_id="a" * 32, relation_type=KoRelationType.DEPENDS_ON)
    assert data.relation_type == KoRelationType.DEPENDS_ON


def test_relation_out_schema() -> None:
    row = KoRelationOut(
        id="r1",
        from_ko_id="a" * 32,
        to_ko_id="b" * 32,
        relation_type=KoRelationType.CAUSES,
        direction="outbound",
        peer_id="b" * 32,
        peer_title="交换机故障",
        peer_ko_type=KoType.DEVICE,
        peer_status=KoStatus.PUBLISHED,
        created_at=datetime.now(UTC),
    )
    assert row.direction == "outbound"
    assert row.peer_ko_type == KoType.DEVICE
    assert row.warnings == []
