from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.schemas.knowledge import AclEntryIn, AclEntryOut


class StructuredSourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    type: str = Field(default="manual", max_length=16)
    enabled: bool = True
    meta: dict[str, Any] = Field(default_factory=dict)


class MysqlConnectIn(BaseModel):
    """Ephemeral MySQL connection for admin schema introspection (password not stored)."""

    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=3306, ge=1, le=65535)
    database: str = Field(min_length=1, max_length=128)
    user: str = Field(min_length=1, max_length=128)
    password_env: str = Field(default="MES_MYSQL_PASSWORD", min_length=1, max_length=128)
    password: str | None = Field(
        default=None,
        max_length=256,
        description="One-shot password for this request only; prefer password_env",
    )
    charset: str = Field(default="utf8mb4", min_length=1, max_length=32)
    source_id: str | None = Field(
        default=None,
        max_length=32,
        description="Optional structured source with meta.connector=mysql to reuse",
    )


class MysqlListTablesIn(MysqlConnectIn):
    pass


class MysqlTableInfo(BaseModel):
    name: str
    table_type: str = ""
    approx_rows: int = 0
    comment: str | None = None


class MysqlListTablesOut(BaseModel):
    database: str
    tables: list[MysqlTableInfo]


class MysqlProbeIn(MysqlConnectIn):
    table: str = Field(min_length=1, max_length=128)
    sample_limit: int = Field(default=3, ge=1, le=20)


class MysqlColumnInfo(BaseModel):
    name: str
    type: str
    nullable: str | None = None
    key: str | None = None


class MysqlProbeOut(BaseModel):
    database: str
    table: str
    columns: list[MysqlColumnInfo]
    row_count: int = 0
    samples: list[dict[str, Any]] = Field(default_factory=list)


class PostgresConnectIn(BaseModel):
    """Ephemeral PostgreSQL connection for admin schema introspection."""

    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=5432, ge=1, le=65535)
    database: str = Field(min_length=1, max_length=128)
    user: str = Field(min_length=1, max_length=128)
    password_env: str = Field(default="MES_PG_PASSWORD", min_length=1, max_length=128)
    password: str | None = Field(default=None, max_length=256)
    schema: str = Field(default="public", min_length=1, max_length=64)
    source_id: str | None = Field(default=None, max_length=32)


class PostgresListTablesIn(PostgresConnectIn):
    pass


class PostgresProbeIn(PostgresConnectIn):
    table: str = Field(min_length=1, max_length=128)
    sample_limit: int = Field(default=3, ge=1, le=20)


class PostgresListTablesOut(BaseModel):
    database: str
    schema: str = "public"
    tables: list[MysqlTableInfo]


class PostgresProbeOut(BaseModel):
    database: str
    schema: str = "public"
    table: str
    columns: list[MysqlColumnInfo]
    row_count: int = 0
    samples: list[dict[str, Any]] = Field(default_factory=list)


class MongoConnectIn(BaseModel):
    """Ephemeral MongoDB connection for admin collection introspection."""

    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=27017, ge=1, le=65535)
    database: str = Field(min_length=1, max_length=128)
    user: str = Field(default="", max_length=128)
    password_env: str = Field(default="MES_MONGO_PASSWORD", min_length=1, max_length=128)
    password: str | None = Field(default=None, max_length=256)
    auth_source: str = Field(default="admin", min_length=1, max_length=128)
    source_id: str | None = Field(default=None, max_length=32)


class MongoListCollectionsIn(MongoConnectIn):
    pass


class MongoProbeIn(MongoConnectIn):
    table: str = Field(
        min_length=1,
        max_length=128,
        description="Collection name (same field as SQL table for Studio reuse)",
    )
    sample_limit: int = Field(default=3, ge=1, le=20)


class MongoListCollectionsOut(BaseModel):
    database: str
    tables: list[MysqlTableInfo]


class MongoProbeOut(BaseModel):
    database: str
    table: str
    columns: list[MysqlColumnInfo]
    row_count: int = 0
    samples: list[dict[str, Any]] = Field(default_factory=list)


class MssqlConnectIn(BaseModel):
    """Ephemeral SQL Server connection for admin schema introspection."""

    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=1433, ge=1, le=65535)
    database: str = Field(min_length=1, max_length=128)
    user: str = Field(min_length=1, max_length=128)
    password_env: str = Field(default="MES_MSSQL_PASSWORD", min_length=1, max_length=128)
    password: str | None = Field(default=None, max_length=256)
    schema: str = Field(default="dbo", min_length=1, max_length=64)
    source_id: str | None = Field(default=None, max_length=32)


class MssqlListTablesIn(MssqlConnectIn):
    pass


class MssqlProbeIn(MssqlConnectIn):
    table: str = Field(min_length=1, max_length=128)
    sample_limit: int = Field(default=3, ge=1, le=20)


class MssqlListTablesOut(BaseModel):
    database: str
    schema: str = "dbo"
    tables: list[MysqlTableInfo]


class MssqlProbeOut(BaseModel):
    database: str
    schema: str = "dbo"
    table: str
    columns: list[MysqlColumnInfo]
    row_count: int = 0
    samples: list[dict[str, Any]] = Field(default_factory=list)


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
    parent_object_type: str | None = Field(default=None, max_length=64)
    parent_external_id: str | None = Field(default=None, max_length=64)


class StructuredRecordOut(BaseModel):
    id: str
    domain_id: str
    source_id: str
    object_type: str
    external_id: str
    title: str
    status: str
    parent_object_type: str | None = None
    parent_external_id: str | None = None
    occurred_at: datetime | None = None
    ended_at: datetime | None = None
    event_type: str | None = None
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
    object_type: str = Field(max_length=64)
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
    force_full: bool = False
    mode: str = "full"
    stats: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    synced_at: str | None = None
    triggered_by: str | None = None
    sync_cursor: dict[str, Any] | None = None


class StructuredObjectAclOut(BaseModel):
    object_type: str
    object_id: str
    entries: list[AclEntryOut] = Field(default_factory=list)


class StructuredObjectAclUpdate(BaseModel):
    entries: list[AclEntryIn] = Field(default_factory=list, max_length=500)


class StructuredAttrDefOut(BaseModel):
    name: str
    kind: str
    required: bool
    description: str = ""
    unit: str | None = None
    allowed_units: list[str] | None = None
    minimum: float | None = None
    maximum: float | None = None
    enum_values: list[str] | None = None


class StructuredAttrSchemaOut(BaseModel):
    object_type: str
    label: str
    description: str
    attributes: list[StructuredAttrDefOut]
    json_schema: dict[str, Any]


class ObjectRelationCreate(BaseModel):
    relation_type: str = Field(min_length=1, max_length=32)
    from_kind: str = Field(min_length=1, max_length=16)
    from_id: str = Field(min_length=1, max_length=32)
    from_object_type: str | None = Field(default=None, max_length=64)
    to_kind: str = Field(min_length=1, max_length=16)
    to_id: str = Field(min_length=1, max_length=32)
    to_object_type: str | None = Field(default=None, max_length=64)
    cardinality: str | None = Field(default=None, max_length=16)
    attrs: dict[str, Any] = Field(default_factory=dict)
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class ObjectRelationOut(BaseModel):
    id: str
    relation_type: str
    relation_local_name: str
    from_kind: str
    from_id: str
    from_object_type: str | None
    to_kind: str
    to_id: str
    to_object_type: str | None
    cardinality: str = "one_to_many"
    attrs: dict[str, Any] = Field(default_factory=dict)
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    created_by: str | None
    created_at: datetime
    updated_at: datetime
    warnings: list[str] = Field(default_factory=list)
