from datetime import datetime

from pydantic import BaseModel, Field


class TerminologyAliasOut(BaseModel):
    id: str
    entity_id: str
    alias: str
    lang: str
    created_at: datetime


class TerminologyEntityOut(BaseModel):
    id: str
    canonical_name: str
    entity_type: str
    description: str | None
    status: str
    aliases: list[TerminologyAliasOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class TerminologyEntityCreate(BaseModel):
    canonical_name: str = Field(min_length=1, max_length=256)
    entity_type: str = Field(default="other", max_length=32)
    description: str | None = Field(default=None, max_length=4000)
    status: str = Field(default="active", max_length=16)
    aliases: list[str] = Field(default_factory=list, max_length=50)


class TerminologyEntityUpdate(BaseModel):
    canonical_name: str | None = Field(default=None, min_length=1, max_length=256)
    entity_type: str | None = Field(default=None, max_length=32)
    description: str | None = Field(default=None, max_length=4000)
    status: str | None = Field(default=None, max_length=16)


class TerminologyAliasCreate(BaseModel):
    alias: str = Field(min_length=1, max_length=256)
    lang: str = Field(default="any", max_length=8)


class TerminologyRelationCreate(BaseModel):
    from_id: str = Field(min_length=1, max_length=32)
    to_id: str = Field(min_length=1, max_length=32)
    kind: str = Field(min_length=1, max_length=16)


class TerminologyRelationOut(BaseModel):
    id: str
    from_id: str
    to_id: str
    kind: str
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


class ConceptGraphNode(BaseModel):
    id: str
    label: str
    kind: str  # term | mirror | ko
    meta: dict[str, str] = Field(default_factory=dict)


class ConceptGraphEdge(BaseModel):
    source: str
    target: str
    relation: str


class TerminologyNeighborhoodOut(BaseModel):
    """Lightweight neighborhood for admin relationship preview (≤ ~20 nodes)."""

    entity: TerminologyEntityOut
    nodes: list[ConceptGraphNode] = Field(default_factory=list)
    edges: list[ConceptGraphEdge] = Field(default_factory=list)


class TerminologySynonymsSyncOut(BaseModel):
    """Result of exporting active terminology into OpenSearch synonyms.txt."""

    path: str
    lines: int
    reloaded: bool
