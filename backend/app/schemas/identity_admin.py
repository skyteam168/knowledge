"""Admin schemas for canonical identity management."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class CanonicalCreate(BaseModel):
    object_type: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=256)
    structured_object_type: str | None = Field(default=None, max_length=64)
    structured_object_id: str | None = Field(default=None, max_length=32)
    status: str = Field(default="active", max_length=16)

    @field_validator("object_type", "structured_object_type")
    @classmethod
    def _lower(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip().lower()


class IdentifierCreate(BaseModel):
    system: str = Field(min_length=1, max_length=32)
    external_id: str = Field(min_length=1, max_length=128)
    id_kind: str = Field(default="external_id", max_length=32)
    is_primary: bool = False

    @field_validator("system", "id_kind")
    @classmethod
    def _norm(cls, value: str) -> str:
        return value.strip().lower()


class IdentifierOut(BaseModel):
    id: str
    canonical_id: str
    system: str
    id_kind: str
    external_id: str
    is_primary: bool
    created_at: datetime
    updated_at: datetime


class CanonicalOut(BaseModel):
    id: str
    object_type: str
    display_name: str
    status: str
    structured_object_type: str | None = None
    structured_object_id: str | None = None
    created_at: datetime
    updated_at: datetime
    identifiers: list[IdentifierOut] = Field(default_factory=list)


class ResolveMatchIn(BaseModel):
    identifiers: list[dict[str, Any]] = Field(min_length=1)


class ResolveMatchOut(BaseModel):
    status: str
    canonical_ids: list[str] = Field(default_factory=list)
    canonical: CanonicalOut | None = None
