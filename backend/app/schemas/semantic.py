"""Ontology Studio (OS1) request/response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class SemanticVersionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    notes: str | None = Field(default=None, max_length=512)


class SemanticVersionOut(BaseModel):
    id: str
    name: str
    status: str
    is_active: bool
    notes: str | None
    published_at: datetime | None
    published_by: str | None
    created_by: str | None
    created_at: datetime
    updated_at: datetime


class SemanticEntityCreate(BaseModel):
    local_name: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=1024)
    object_type: str | None = Field(default=None, max_length=64)
    owners: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("local_name", "object_type")
    @classmethod
    def _norm(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()


class SemanticEntityOut(BaseModel):
    id: str
    version_id: str
    local_name: str
    label: str
    description: str | None
    object_type: str | None
    owners: list[str] = Field(default_factory=list)
    status: str
    created_at: datetime
    updated_at: datetime


class SemanticAttributeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=1024)
    attr_kind: str = Field(default="string", max_length=32)
    unit: str | None = Field(default=None, max_length=32)
    enum_map: dict[str, Any] = Field(default_factory=dict)
    labels: dict[str, str] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return value.strip()

    @field_validator("unit")
    @classmethod
    def _unit(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None


class SemanticAttributeUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=1024)
    attr_kind: str | None = Field(default=None, max_length=32)
    unit: str | None = Field(default=None, max_length=32)
    enum_map: dict[str, Any] | None = None
    labels: dict[str, str] | None = None

    @field_validator("unit")
    @classmethod
    def _unit(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None


class SemanticAttributeOut(BaseModel):
    id: str
    version_id: str
    entity_id: str
    name: str
    label: str
    description: str | None
    attr_kind: str
    unit: str | None = None
    enum_map: dict[str, Any] = Field(default_factory=dict)
    labels: dict[str, str] = Field(default_factory=dict)
    status: str
    created_at: datetime
    updated_at: datetime


class SemanticMappingCreate(BaseModel):
    table_name: str = Field(min_length=1, max_length=128)
    column_name: str = Field(min_length=1, max_length=128)
    source_id: str | None = Field(default=None, max_length=32)
    source_of_truth: bool = False
    freshness_sla_seconds: int | None = Field(default=None, ge=1)


class SemanticMappingOut(BaseModel):
    id: str
    version_id: str
    attribute_id: str
    source_id: str | None
    table_name: str
    column_name: str
    source_of_truth: bool = False
    freshness_sla_seconds: int | None = None
    status: str
    created_at: datetime
    updated_at: datetime


class SemanticItemStatusUpdate(BaseModel):
    status: str = Field(pattern="^(draft|approved|rejected)$")


class SemanticVersionDetailOut(SemanticVersionOut):
    entities: list[SemanticEntityOut] = Field(default_factory=list)
    attributes: list[SemanticAttributeOut] = Field(default_factory=list)
    mappings: list[SemanticMappingOut] = Field(default_factory=list)


class OpenOntologyDescribeIn(BaseModel):
    """Query params / body for scoped ontology describe."""

    scope: str = Field(
        default="summary",
        description="summary|classes|relations|attributes|equipment|all",
    )
    version: str = Field(
        default="published",
        description="published|platform|<version_id>",
    )

    @field_validator("scope", "version")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip().lower()


class SchemaColumnIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    data_type: str | None = Field(default=None, max_length=64)
    comment: str | None = Field(default=None, max_length=512)


class SchemaTableIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    columns: list[SchemaColumnIn] = Field(min_length=1)
    comment: str | None = Field(default=None, max_length=512)


class SchemaImportIn(BaseModel):
    """OS2: import physical tables/columns into a draft semantic version."""

    version_id: str | None = Field(
        default=None,
        max_length=32,
        description="Existing draft version; omit to create a new draft",
    )
    version_name: str | None = Field(
        default=None,
        max_length=128,
        description="Name when creating a new draft version",
    )
    source_id: str | None = Field(default=None, max_length=32)
    tables: list[SchemaTableIn] = Field(min_length=1)
    auto_approve: bool = False


class SchemaImportStats(BaseModel):
    version_id: str
    entities_created: int
    entities_unchanged: int
    attributes_created: int
    attributes_unchanged: int
    mappings_created: int
    mappings_unchanged: int


class SchemaImportOut(BaseModel):
    version: SemanticVersionOut
    stats: SchemaImportStats


class SemanticSuggestOut(BaseModel):
    version_id: str
    entities_updated: int
    attributes_updated: int
    suggestions: list[dict[str, Any]] = Field(default_factory=list)


class SemanticBatchStatusIn(BaseModel):
    entity_ids: list[str] = Field(default_factory=list)
    attribute_ids: list[str] = Field(default_factory=list)
    mapping_ids: list[str] = Field(default_factory=list)
    status: str = Field(pattern="^(draft|approved|rejected)$")


class SemanticBatchStatusOut(BaseModel):
    entities_updated: int
    attributes_updated: int
    mappings_updated: int
