from datetime import datetime
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

Visibility = Literal["org", "restricted"]
AclPermissionName = Literal["read", "edit", "manage"]
GrantablePrincipal = Literal["user", "group", "role", "dept"]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- ACL ------------------------------------------------------------------------------


class AclEntryIn(BaseModel):
    principal_type: GrantablePrincipal
    principal_id: str = Field(min_length=1, max_length=64)
    permission: AclPermissionName


class AclEntryOut(AclEntryIn):
    principal_name: str | None = None


class KbAclOut(BaseModel):
    visibility: Visibility
    entries: list[AclEntryOut]


class KbAclUpdate(BaseModel):
    visibility: Visibility
    entries: list[AclEntryIn] = Field(default_factory=list, max_length=500)


class DocumentAclOut(BaseModel):
    inherit: bool
    kb_visibility: Visibility
    kb_entries: list[AclEntryOut]
    entries: list[AclEntryOut]


class DocumentAclUpdate(BaseModel):
    inherit: bool
    entries: list[AclEntryIn] = Field(default_factory=list, max_length=500)


# ---- knowledge bases ------------------------------------------------------------------


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    visibility: Visibility = "restricted"


class KnowledgeBaseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)


class KnowledgeBaseOut(ORMModel):
    id: str
    name: str
    description: str | None
    visibility: Visibility
    created_by: str | None
    created_at: datetime
    updated_at: datetime
    document_count: int = 0
    my_permission: AclPermissionName | None = None


# ---- documents ------------------------------------------------------------------------


class DocumentOut(ORMModel):
    id: str
    kb_id: str
    title: str
    filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    version: int
    status: str
    error_message: str | None
    tags: list[str]
    metadata: dict[str, Any] = Field(validation_alias=AliasChoices("meta", "metadata"))
    effective_from: datetime | None
    effective_to: datetime | None
    acl_inherit: bool
    chunk_count: int | None
    parsed_at: datetime | None
    chunked_at: datetime | None
    created_by: str | None
    created_at: datetime
    updated_at: datetime
    my_permission: AclPermissionName | None = None


class DocumentVersionOut(ORMModel):
    version: int
    filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    created_by: str | None
    created_at: datetime


class DocumentDetail(DocumentOut):
    kb_name: str
    versions: list[DocumentVersionOut]


class DocumentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=512)
    tags: list[str] | None = Field(default=None, max_length=50)
    metadata: dict[str, Any] | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None

    @field_validator("tags")
    @classmethod
    def _clean_tags(cls, tags: list[str] | None) -> list[str] | None:
        if tags is None:
            return None
        return list(dict.fromkeys(t.strip() for t in tags if t.strip()))


class UploadInit(BaseModel):
    filename: str = Field(min_length=1, max_length=512)
    size_bytes: int = Field(gt=0)
    mime_type: str | None = Field(default=None, max_length=255)
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")


class UploadInitOut(BaseModel):
    duplicate: bool
    document: DocumentOut | None = None
    ticket: str | None = None
    upload_url: str | None = None
    method: str = "PUT"
    expires_in: int | None = None


class UploadComplete(BaseModel):
    ticket: str = Field(min_length=1, max_length=64)
    tags: list[str] = Field(default_factory=list, max_length=50)


class UploadResult(BaseModel):
    document: DocumentOut
    duplicate: bool
    new_version: bool


class ChunkOut(ORMModel):
    id: str
    document_version: int
    parent_id: str | None
    level: int
    seq: int
    heading_path: list[str]
    content: str
    token_count: int
    page_start: int | None
    page_end: int | None
    sheet_name: str | None
    slide_number: int | None
    chunk_type: str


class PreviewOut(BaseModel):
    url: str
    filename: str
    mime_type: str
    expires_in: int


# ---- directory (principal picker) -----------------------------------------------------


class PrincipalOption(BaseModel):
    type: GrantablePrincipal
    id: str
    name: str
    description: str | None = None


class DirectoryDepartment(BaseModel):
    id: str
    name: str
    path_name: str | None = None
    children: list["DirectoryDepartment"] = Field(default_factory=list)
