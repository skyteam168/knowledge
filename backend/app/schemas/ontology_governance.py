"""Admin schemas for ontology rules and action types."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class OntologyRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=512)
    priority: int = Field(default=100)
    enabled: bool = True
    condition: dict[str, Any] = Field(default_factory=dict)
    verdict: str = Field(default="allow", max_length=32)
    message: str | None = Field(default=None, max_length=512)


class OntologyRuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=512)
    priority: int | None = None
    enabled: bool | None = None
    condition: dict[str, Any] | None = None
    verdict: str | None = Field(default=None, max_length=32)
    message: str | None = Field(default=None, max_length=512)


class OntologyRuleOut(BaseModel):
    id: str
    name: str
    description: str | None
    priority: int
    enabled: bool
    condition: dict[str, Any]
    verdict: str
    message: str | None
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


class ActionTypeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=512)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    preconditions: dict[str, Any] = Field(default_factory=dict)
    risk: str = Field(default="low", max_length=16)
    systems: list[str] = Field(default_factory=list)
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return value.strip()


class ActionTypeUpdate(BaseModel):
    description: str | None = Field(default=None, max_length=512)
    input_schema: dict[str, Any] | None = None
    preconditions: dict[str, Any] | None = None
    risk: str | None = Field(default=None, max_length=16)
    systems: list[str] | None = None
    enabled: bool | None = None


class ActionTypeOut(BaseModel):
    id: str
    name: str
    description: str | None
    input_schema: dict[str, Any]
    preconditions: dict[str, Any]
    risk: str
    systems: list[str]
    enabled: bool
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime
