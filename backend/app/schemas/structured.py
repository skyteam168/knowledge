from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator


class StructuredSourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    type: str = Field(default="manual", max_length=16)
    enabled: bool = True
    meta: dict[str, Any] = Field(default_factory=dict)


class StructuredSourceOut(BaseModel):
    id: str
    name: str
    type: str
    enabled: bool
    meta: dict[str, Any]
    created_by: str | None
    created_at: datetime
    updated_at: datetime


class StructuredDomainCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=512)
    enabled: bool = True


class StructuredDomainOut(BaseModel):
    id: str
    code: str
    name: str
    kind: str
    description: str | None
    enabled: bool
    created_by: str | None
    created_at: datetime
    updated_at: datetime


class StructuredRecordCreate(BaseModel):
    domain_id: str = Field(min_length=1, max_length=32)
    source_id: str = Field(min_length=1, max_length=32)
    object_type: str = Field(min_length=1, max_length=64)
    external_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=512)
    status: str = Field(default="active", max_length=32)
    attrs: dict[str, Any] = Field(default_factory=dict)


class StructuredRecordOut(BaseModel):
    id: str
    domain_id: str
    source_id: str
    object_type: str
    external_id: str
    title: str
    status: str
    attrs: dict[str, Any]
    created_by: str | None
    created_at: datetime
    updated_at: datetime


class EquipDeviceOut(BaseModel):
    id: str
    source_id: str
    external_id: str
    name: str
    status: str
    location: str | None
    meta: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class EquipWorkOrderOut(BaseModel):
    id: str
    source_id: str
    external_id: str
    device_external_id: str | None
    title: str
    status: str
    opened_at: datetime | None
    meta: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class EquipSparePartOut(BaseModel):
    id: str
    source_id: str
    external_id: str
    name: str
    sku: str | None
    qty_on_hand: float
    meta: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class StructuredLinkCreate(BaseModel):
    object_type: str = Field(max_length=32)
    object_id: str = Field(min_length=1, max_length=32)
    terminology_entity_id: str | None = Field(default=None, max_length=32)
    ko_id: str | None = Field(default=None, max_length=32)

    @model_validator(mode="after")
    def _one_target(self) -> "StructuredLinkCreate":
        if not self.terminology_entity_id and not self.ko_id:
            raise ValueError("terminology_entity_id or ko_id is required")
        return self


class StructuredLinkOut(BaseModel):
    id: str
    object_type: str
    object_id: str
    terminology_entity_id: str | None
    terminology_name: str | None = None
    ko_id: str | None
    ko_title: str | None = None
    created_by: str | None
    created_at: datetime


class StructuredResolveOut(BaseModel):
    object_type: str
    object_id: str
    external_id: str
    source_id: str
    label: str
    status: str
    links: list[StructuredLinkOut] = Field(default_factory=list)


class StructuredSyncResult(BaseModel):
    source_id: str
    source_name: str
    connector: str
    status: str
    dry_run: bool = False
    stats: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    synced_at: str | None = None
    triggered_by: str | None = None
