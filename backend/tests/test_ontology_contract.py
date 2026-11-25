"""OWL TBox contract stays aligned with backend StrEnum catalogs."""

from pathlib import Path

from app.models.curation import KoRelationType, KoType
from app.models.structured import (
    ObjectRelationType,
    StructuredDomainKind,
    StructuredObjectType,
)
from app.models.terminology import TerminologyEntityType
from app.ontology.catalog import (
    DEFAULT_TTL_PATH,
    EQUIP_TABLE_OBJECT_TYPES,
    INDUSTRIAL_OBJECT_CLASSES,
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
        class_local_name(v.value, enum_name="TerminologyEntityType")
        for v in TerminologyEntityType
    }
    assert cat.ko_classes == {
        class_local_name(v.value, enum_name="KoType") for v in KoType
    }
    assert cat.structured_domain_classes == {
        class_local_name(v.value, enum_name="StructuredDomainKind")
        for v in StructuredDomainKind
    }
    assert "GenericDomain" in cat.structured_domain_classes
    assert "EquipmentDomain" in cat.structured_domain_classes
    assert "Equipment" not in cat.structured_domain_classes
    assert cat.structured_object_classes == {
        class_local_name(v.value, enum_name="StructuredObjectType")
        for v in StructuredObjectType
    }
    assert cat.relation_properties == {
        property_local_name(v.value) for v in KoRelationType
    }
    assert cat.industrial_relation_properties == {
        property_local_name(v.value) for v in ObjectRelationType
    }
    assert "relatedTo" in cat.relation_properties
    assert "appliesTo" in cat.relation_properties
    assert "hasFailureMode" in cat.industrial_relation_properties
    assert "workOrderFor" in cat.industrial_relation_properties


def test_industrial_object_classes_in_catalog() -> None:
    cat = OntologyCatalog.from_enums()
    missing = INDUSTRIAL_OBJECT_CLASSES - cat.structured_object_classes
    assert missing == set(), f"missing industrial classes: {sorted(missing)}"
    assert "IndustrialObject" in cat.all_required_classes()
    assert {"component", "failure_mode"} <= {t.value for t in TerminologyEntityType}
    assert {"component", "failure_mode"} <= {t.value for t in KoType}
    required = {
        "site",
        "area",
        "line",
        "equipment",
        "component",
        "material",
        "operation",
        "process_parameter",
        "failure_mode",
        "event",
    }
    assert required <= {t.value for t in StructuredObjectType}


def test_equipment_domain_vs_equipment_object_names_do_not_collide() -> None:
    domain = class_local_name(
        StructuredDomainKind.EQUIPMENT.value, enum_name="StructuredDomainKind"
    )
    equipment = class_local_name(
        StructuredObjectType.EQUIPMENT.value, enum_name="StructuredObjectType"
    )
    assert domain == "EquipmentDomain"
    assert equipment == "Equipment"
    assert domain != equipment


def test_equip_table_object_types_remain_narrow() -> None:
    assert EQUIP_TABLE_OBJECT_TYPES == {"device", "work_order", "spare_part"}
    assert StructuredObjectType.EQUIPMENT.value not in EQUIP_TABLE_OBJECT_TYPES
    assert StructuredObjectType.FAILURE_MODE.value not in EQUIP_TABLE_OBJECT_TYPES


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
