"""Write a read-only sample ABox TTL for Protégé (not a runtime data source)."""

from __future__ import annotations

from pathlib import Path

from app.ontology.catalog import DEFAULT_SAMPLE_ABOX_PATH, NS

_SAMPLE = f"""@prefix : <{NS}> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

#################################################################
# Sample ABox for Protégé preview only.
# Authoritative instances live in PostgreSQL (seed-equipment).
#################################################################

:ontology a owl:Ontology ;
    owl:imports <{NS.rstrip("#")}> ;
    rdfs:comment "演示实例：织机 / EQ-LOOM-01 / 种子 KO。勿作为运行时加载源。"@zh .

:term_loom a :Device ;
    rdfs:label "织机"@zh ;
    :hasAlias "loom" ;
    :hasAlias "飞织机" ;
    :hasAlias "knitting machine" .

:device_eq_loom_01 a :Device ;
    rdfs:label "1号飞织机"@zh ;
    :externalId "EQ-LOOM-01" ;
    :linkedToTerminology :term_loom ;
    :linkedToKnowledgeObject :ko_loom_maint .

:ko_loom_maint a :Device ;
    rdfs:label "【种子】织机维保要点"@zh .

:ko_yarn_break a :Qa ;
    rdfs:label "【种子】织机断纱检修"@zh .

:ko_yarn_break :relatedTo :ko_loom_maint .
:ko_loom_maint :mitigates :ko_yarn_break .
"""


def write_seed_abox(path: Path | None = None) -> Path:
    out = path or DEFAULT_SAMPLE_ABOX_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_SAMPLE, encoding="utf-8")
    return out
