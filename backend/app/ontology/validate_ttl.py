"""Parse enterprise.ttl and assert coverage against OntologyCatalog."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rdflib import OWL, RDF, RDFS, Graph, URIRef

from app.ontology.catalog import DEFAULT_TTL_PATH, NS, OntologyCatalog


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    message: str


def _local_name(uri: URIRef) -> str | None:
    text = str(uri)
    if text.startswith(NS):
        return text[len(NS) :]
    return None


def validate_enterprise_ttl(
    path: Path | None = None,
    catalog: OntologyCatalog | None = None,
) -> list[ValidationIssue]:
    ttl_path = path or DEFAULT_TTL_PATH
    cat = catalog or OntologyCatalog.from_enums()
    issues: list[ValidationIssue] = []

    if not ttl_path.is_file():
        return [ValidationIssue("missing_ttl", f"ontology file not found: {ttl_path}")]

    graph = Graph()
    try:
        graph.parse(ttl_path, format="turtle")
    except Exception as exc:
        return [ValidationIssue("parse_error", f"failed to parse TTL: {exc}")]

    declared_classes: set[str] = set()
    for s in graph.subjects(RDF.type, OWL.Class):
        if isinstance(s, URIRef):
            local = _local_name(s)
            if local:
                declared_classes.add(local)

    declared_object_props: set[str] = set()
    for s in graph.subjects(RDF.type, OWL.ObjectProperty):
        if isinstance(s, URIRef):
            local = _local_name(s)
            if local:
                declared_object_props.add(local)

    declared_datatype_props: set[str] = set()
    for s in graph.subjects(RDF.type, OWL.DatatypeProperty):
        if isinstance(s, URIRef):
            local = _local_name(s)
            if local:
                declared_datatype_props.add(local)

    for name in sorted(cat.all_required_classes() - declared_classes):
        issues.append(
            ValidationIssue("missing_class", f"OWL class missing in TTL: {name}")
        )

    for name in sorted(cat.all_required_object_properties() - declared_object_props):
        issues.append(
            ValidationIssue(
                "missing_object_property",
                f"OWL object property missing in TTL: {name}",
            )
        )

    for name in sorted(cat.all_required_datatype_properties() - declared_datatype_props):
        issues.append(
            ValidationIssue(
                "missing_datatype_property",
                f"OWL datatype property missing in TTL: {name}",
            )
        )

    # Orphan object properties in our namespace that are not in the catalog
    # (allow only documented extras — none today).
    allowed_object = cat.all_required_object_properties()
    for name in sorted(declared_object_props - allowed_object):
        issues.append(
            ValidationIssue(
                "orphan_object_property",
                f"TTL object property not in catalog enums: {name}",
            )
        )

    # KO relation properties should have domain/range KnowledgeObject.
    ko_iri = URIRef(f"{NS}KnowledgeObject")
    for local in sorted(cat.relation_properties):
        prop = URIRef(f"{NS}{local}")
        domains = set(graph.objects(prop, RDFS.domain))
        ranges = set(graph.objects(prop, RDFS.range))
        if ko_iri not in domains:
            issues.append(
                ValidationIssue(
                    "relation_domain",
                    f"relation {local} domain should include KnowledgeObject",
                )
            )
        if ko_iri not in ranges:
            issues.append(
                ValidationIssue(
                    "relation_range",
                    f"relation {local} range should include KnowledgeObject",
                )
            )

    # Industrial object relations: domain/range IndustrialObject (or StructuredObject).
    industrial_iri = URIRef(f"{NS}IndustrialObject")
    structured_iri = URIRef(f"{NS}StructuredObject")
    for local in sorted(cat.industrial_relation_properties):
        prop = URIRef(f"{NS}{local}")
        domains = set(graph.objects(prop, RDFS.domain))
        ranges = set(graph.objects(prop, RDFS.range))
        if industrial_iri not in domains and structured_iri not in domains:
            issues.append(
                ValidationIssue(
                    "industrial_relation_domain",
                    f"relation {local} domain should include IndustrialObject",
                )
            )
        if industrial_iri not in ranges and structured_iri not in ranges:
            issues.append(
                ValidationIssue(
                    "industrial_relation_range",
                    f"relation {local} range should include IndustrialObject",
                )
            )

    return issues
