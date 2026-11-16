"""Expected OWL local names derived from backend StrEnum values."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from app.models.curation import KoRelationType, KoType
from app.models.structured import StructuredDomainKind, StructuredObjectType
from app.models.terminology import TerminologyEntityType

NS = "https://flyknit.local/ontology/enterprise#"

# Enum value → OWL local name when simple snake_case conversion is insufficient.
_CLASS_OVERRIDES: dict[str, str] = {
    "generic": "GenericDomain",
}

_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_TTL_PATH = _REPO_ROOT / "ontology" / "enterprise.ttl"
DEFAULT_SAMPLE_ABOX_PATH = _REPO_ROOT / "ontology" / "examples" / "seed-abox.ttl"


def snake_to_pascal(value: str) -> str:
    parts = value.split("_")
    return "".join(p[:1].upper() + p[1:] for p in parts if p)


def snake_to_camel(value: str) -> str:
    pascal = snake_to_pascal(value)
    if not pascal:
        return pascal
    return pascal[:1].lower() + pascal[1:]


def class_local_name(enum_value: str) -> str:
    return _CLASS_OVERRIDES.get(enum_value, snake_to_pascal(enum_value))


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
    link_properties: frozenset[str]

    @classmethod
    def from_enums(cls) -> OntologyCatalog:
        return cls(
            terminology_classes=frozenset(
                class_local_name(v.value) for v in TerminologyEntityType
            ),
            ko_classes=frozenset(class_local_name(v.value) for v in KoType),
            structured_domain_classes=frozenset(
                class_local_name(v.value) for v in StructuredDomainKind
            ),
            structured_object_classes=frozenset(
                class_local_name(v.value) for v in StructuredObjectType
            ),
            relation_properties=frozenset(
                property_local_name(v.value) for v in KoRelationType
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
                }
            )
        )

    def all_required_object_properties(self) -> frozenset[str]:
        # Datatype properties are validated separately in validate_ttl.
        return self.relation_properties | frozenset(
            {"linkedToTerminology", "linkedToKnowledgeObject"}
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
