"""Enterprise OWL TBox contract: catalog, TTL validation, soft relation constraints."""

from typing import Any

from app.ontology.catalog import NS, OntologyCatalog, snake_to_camel, snake_to_pascal
from app.ontology.constraints import (
    relation_soft_warnings,
    validate_object_relation_endpoints,
)

__all__ = [
    "NS",
    "OntologyCatalog",
    "relation_soft_warnings",
    "snake_to_camel",
    "snake_to_pascal",
    "validate_enterprise_ttl",
    "validate_object_relation_endpoints",
]


def __getattr__(name: str) -> Any:
    if name == "validate_enterprise_ttl":
        from app.ontology.validate_ttl import validate_enterprise_ttl

        return validate_enterprise_ttl
    if name == "ValidationIssue":
        from app.ontology.validate_ttl import ValidationIssue

        return ValidationIssue
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
