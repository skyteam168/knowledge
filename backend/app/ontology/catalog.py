"""Expected OWL local names derived from backend StrEnum values."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from app.models.curation import KoRelationType, KoType
from app.models.structured import (
    ObjectRelationType,
    StructuredDomainKind,
    StructuredObjectType,
)
from app.models.terminology import TerminologyEntityType

NS = "https://flyknit.local/ontology/enterprise#"

# (EnumClassName, enum value) → OWL local name when snake_case conversion collides.
_CLASS_OVERRIDES_BY_ENUM: dict[tuple[str, str], str] = {
    ("StructuredDomainKind", "generic"): "GenericDomain",
    # Domain kind "equipment" must not collide with ISA-95 StructuredObjectType.equipment → Equipment
    ("StructuredDomainKind", "equipment"): "EquipmentDomain",
}

_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_TTL_PATH = _REPO_ROOT / "ontology" / "enterprise.ttl"
DEFAULT_SAMPLE_ABOX_PATH = _REPO_ROOT / "ontology" / "examples" / "seed-abox.ttl"

# ISA-95 / FMEA industrial structured object classes (O1.1 contract).
INDUSTRIAL_OBJECT_CLASSES: frozenset[str] = frozenset(
    {
        "Site",
        "Area",
        "Line",
        "Equipment",
        "Component",
        "Material",
        "Operation",
        "ProcessParameter",
        "FailureMode",
        "Event",
        "Factory",
        "CustomerOrder",
        "ProductionOrder",
        "Inventory",
        "Employee",
    }
)

# Dedicated equip_* table kinds (not stored as generic structured_records).
EQUIP_TABLE_OBJECT_TYPES: frozenset[str] = frozenset(
    {
        StructuredObjectType.DEVICE.value,
        StructuredObjectType.WORK_ORDER.value,
        StructuredObjectType.SPARE_PART.value,
    }
)

# Industrial kinds stored in structured_records (O1.3); may live under equipment domain.
INDUSTRIAL_RECORD_OBJECT_TYPES: frozenset[str] = frozenset(
    {
        StructuredObjectType.SITE.value,
        StructuredObjectType.AREA.value,
        StructuredObjectType.LINE.value,
        StructuredObjectType.EQUIPMENT.value,
        StructuredObjectType.COMPONENT.value,
        StructuredObjectType.MATERIAL.value,
        StructuredObjectType.OPERATION.value,
        StructuredObjectType.PROCESS_PARAMETER.value,
        StructuredObjectType.FAILURE_MODE.value,
        StructuredObjectType.EVENT.value,
        StructuredObjectType.FACTORY.value,
        StructuredObjectType.CUSTOMER_ORDER.value,
        StructuredObjectType.PRODUCTION_ORDER.value,
        StructuredObjectType.INVENTORY.value,
        StructuredObjectType.EMPLOYEE.value,
    }
)

# Per object_type: ordered (attr_key, parent_object_type) candidates for hierarchy denorm.
_PARENT_CANDIDATES: dict[str, tuple[tuple[str, str], ...]] = {
    "area": (("site_external_id", "site"),),
    "line": (("area_external_id", "area"), ("site_external_id", "site")),
    "equipment": (
        ("line_external_id", "line"),
        ("area_external_id", "area"),
        ("site_external_id", "site"),
    ),
    "component": (("equipment_external_id", "equipment"),),
    "failure_mode": (
        ("component_external_id", "component"),
        ("equipment_external_id", "equipment"),
    ),
    "event": (("equipment_external_id", "equipment"),),
    "operation": (("line_external_id", "line"), ("area_external_id", "area")),
    "process_parameter": (("operation_external_id", "operation"),),
    "customer_order": (("factory_external_id", "factory"),),
    "production_order": (
        ("customer_order_external_id", "customer_order"),
        ("line_external_id", "line"),
        ("factory_external_id", "factory"),
    ),
    "inventory": (
        ("factory_external_id", "factory"),
        ("line_external_id", "line"),
    ),
    "employee": (("factory_external_id", "factory"),),
}


def derive_parent_ref(
    object_type: str, attrs: dict[str, object] | None
) -> tuple[str | None, str | None]:
    """Pick parent (type, external_id) from typed attrs for structured_records columns."""
    data = dict(attrs or {})
    for key, parent_type in _PARENT_CANDIDATES.get(object_type.strip().lower(), ()):
        raw = data.get(key)
        if isinstance(raw, str) and raw.strip():
            return parent_type, raw.strip()
    return None, None


def snake_to_pascal(value: str) -> str:
    parts = value.split("_")
    return "".join(p[:1].upper() + p[1:] for p in parts if p)


def snake_to_camel(value: str) -> str:
    pascal = snake_to_pascal(value)
    if not pascal:
        return pascal
    return pascal[:1].lower() + pascal[1:]


def class_local_name(enum_value: str, *, enum_name: str | None = None) -> str:
    if enum_name:
        override = _CLASS_OVERRIDES_BY_ENUM.get((enum_name, enum_value))
        if override:
            return override
    return snake_to_pascal(enum_value)


def property_local_name(enum_value: str) -> str:
    return snake_to_camel(enum_value)


def iri(local: str) -> str:
    return f"{NS}{local}"


@dataclass(frozen=True, slots=True)
class OntologyCatalog:
    """Snapshot of classes / object properties the enterprise.ttl must declare."""

    terminology_classes: frozenset[str]
    ko_classes: frozenset[str]
    structured_domain_classes: frozenset[str]
    structured_object_classes: frozenset[str]
    relation_properties: frozenset[str]
    industrial_relation_properties: frozenset[str]
    link_properties: frozenset[str]

    @classmethod
    def from_enums(cls) -> OntologyCatalog:
        return cls(
            terminology_classes=frozenset(
                class_local_name(v.value, enum_name="TerminologyEntityType")
                for v in TerminologyEntityType
            ),
            ko_classes=frozenset(
                class_local_name(v.value, enum_name="KoType") for v in KoType
            ),
            structured_domain_classes=frozenset(
                class_local_name(v.value, enum_name="StructuredDomainKind")
                for v in StructuredDomainKind
            ),
            structured_object_classes=frozenset(
                class_local_name(v.value, enum_name="StructuredObjectType")
                for v in StructuredObjectType
            ),
            relation_properties=frozenset(
                property_local_name(v.value) for v in KoRelationType
            ),
            industrial_relation_properties=frozenset(
                property_local_name(v.value) for v in ObjectRelationType
            ),
            link_properties=frozenset(
                {"linkedToTerminology", "linkedToKnowledgeObject", "hasAlias", "externalId"}
            ),
        )

    def all_required_classes(self) -> frozenset[str]:
        return (
            self.terminology_classes
            | self.ko_classes
            | self.structured_domain_classes
            | self.structured_object_classes
            | frozenset(
                {
                    "TerminologyEntity",
                    "KnowledgeObject",
                    "StructuredObject",
                    "StructuredDomain",
                    "IndustrialObject",
                }
            )
        )

    def all_required_object_properties(self) -> frozenset[str]:
        # Datatype properties are validated separately in validate_ttl.
        return (
            self.relation_properties
            | self.industrial_relation_properties
            | frozenset({"linkedToTerminology", "linkedToKnowledgeObject"})
        )

    def all_required_datatype_properties(self) -> frozenset[str]:
        return frozenset({"hasAlias", "externalId"})

    @staticmethod
    def enum_value_for_relation_local(local: str) -> str | None:
        for item in KoRelationType:
            if property_local_name(item.value) == local:
                return item.value
        return None

    @staticmethod
    def enum_members(enum_cls: type[StrEnum]) -> list[str]:
        return [m.value for m in enum_cls]
