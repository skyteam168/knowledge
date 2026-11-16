"""OWL TBox contract stays aligned with backend StrEnum catalogs."""

from pathlib import Path

from app.models.curation import KoRelationType, KoType
from app.models.structured import StructuredDomainKind, StructuredObjectType
from app.models.terminology import TerminologyEntityType
from app.ontology.catalog import (
    DEFAULT_TTL_PATH,
    OntologyCatalog,
    class_local_name,
    property_local_name,
)
from app.ontology.constraints import relation_soft_warnings
from app.ontology.export_sample import write_seed_abox
from app.ontology.validate_ttl import validate_enterprise_ttl


def test_catalog_covers_all_enums() -> None:
    cat = OntologyCatalog.from_enums()
    assert cat.terminology_classes == {
        class_local_name(v.value) for v in TerminologyEntityType
    }
    assert cat.ko_classes == {class_local_name(v.value) for v in KoType}
    assert cat.structured_domain_classes == {
        class_local_name(v.value) for v in StructuredDomainKind
    }
    assert "GenericDomain" in cat.structured_domain_classes
    assert cat.structured_object_classes == {
        class_local_name(v.value) for v in StructuredObjectType
    }
    assert cat.relation_properties == {
        property_local_name(v.value) for v in KoRelationType
    }
    assert "relatedTo" in cat.relation_properties
    assert "appliesTo" in cat.relation_properties


def test_enterprise_ttl_matches_catalog() -> None:
    assert DEFAULT_TTL_PATH.is_file(), f"missing {DEFAULT_TTL_PATH}"
    issues = validate_enterprise_ttl()
    assert issues == [], [f"{i.code}: {i.message}" for i in issues]


def test_relation_soft_warnings_causes() -> None:
    ok = relation_soft_warnings(KoRelationType.CAUSES, KoType.DEFECT, KoType.DEVICE)
    assert ok == []
    bad = relation_soft_warnings(KoRelationType.CAUSES, KoType.FAQ, KoType.DEVICE)
    assert any("起点类型" in w for w in bad)
    bad_to = relation_soft_warnings(KoRelationType.CAUSES, KoType.DEFECT, KoType.FAQ)
    assert any("终点类型" in w for w in bad_to)


def test_relation_soft_warnings_related_to_always_ok() -> None:
    assert (
        relation_soft_warnings(KoRelationType.RELATED_TO, KoType.CARD, KoType.IT_TERM)
        == []
    )


def test_export_sample_abox(tmp_path: Path) -> None:
    out = write_seed_abox(tmp_path / "seed-abox.ttl")
    text = out.read_text(encoding="utf-8")
    assert "EQ-LOOM-01" in text
    assert "织机" in text
    assert ":relatedTo" in text or "relatedTo" in text
