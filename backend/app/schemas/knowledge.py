from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

Visibility = Literal["org", "restricted"]
AclPermissionName = Literal["read", "edit", "manage"]
AclEffectName = Literal["allow", "deny"]
GrantablePrincipal = Literal["user", "group", "role", "dept"]
ReviewDays = Annotated[int, Field(ge=1, le=3650)]
ReviewStateName = Literal["none", "ok", "due_soon", "overdue"]
LifecycleStatusName = Literal["draft", "in_review", "published", "retired", "archived"]
ClassificationName = Literal["internal", "confidential", "restricted", "secret"]
LifecycleActionName = Literal["submit", "approve", "reject", "retire", "archive", "reopen"]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- ACL ------------------------------------------------------------------------------


class AclEntryIn(BaseModel):
    principal_type: GrantablePrincipal
    principal_id: str = Field(min_length=1, max_length=64)
    permission: AclPermissionName = "read"
    effect: AclEffectName = "allow"


class AclEntryOut(AclEntryIn):
    principal_name: str | None = None
    # Users only: "username · employee no." so people with the same name can be told apart.
    principal_detail: str | None = None
    principal_active: bool = True


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
    watermark: bool = False
    copy_protect: bool = False
    download_permission: AclPermissionName = "read"
    review_interval_days: ReviewDays | None = None


class KnowledgeBaseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    watermark: bool | None = None
    copy_protect: bool | None = None
    download_permission: AclPermissionName | None = None
    # null = no periodic review (only applied when sent).
    review_interval_days: ReviewDays | None = None


class KnowledgeBaseOut(ORMModel):
    id: str
    name: str
    description: str | None
    visibility: Visibility
    watermark: bool = False
    copy_protect: bool = False
    download_permission: AclPermissionName = "read"
    review_interval_days: int | None = None
    created_by: str | None
    created_at: datetime
    updated_at: datetime
    document_count: int = 0
    my_permission: AclPermissionName | None = None


# ---- documents ------------------------------------------------------------------------


class ProtectionOut(BaseModel):
    watermark: bool = False
    copy_protect: bool = False
    download_permission: AclPermissionName = "read"


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
    lifecycle_status: LifecycleStatusName = "published"
    classification: ClassificationName = "internal"
    error_message: str | None
    tags: list[str]
    metadata: dict[str, Any] = Field(validation_alias=AliasChoices("meta", "metadata"))
    effective_from: datetime | None
    effective_to: datetime | None
    acl_inherit: bool
    # The document's own protection settings (None = as the knowledge base).
    watermark: bool | None = None
    copy_protect: bool | None = None
    download_permission: AclPermissionName | None = None
    owner_id: str | None = None
    owner_name: str | None = None
    # Own review interval (None = as the knowledge base, 0 = never) and the effective one.
    review_interval_days: int | None = None
    review_interval: int | None = None
    reviewed_at: datetime | None = None
    reviewed_by: str | None = None
    review_due_at: datetime | None = None
    review_state: ReviewStateName = "none"
    chunk_count: int | None
    parsed_at: datetime | None
    chunked_at: datetime | None
    created_by: str | None
    created_at: datetime
    updated_at: datetime
    my_permission: AclPermissionName | None = None
    # Effective protection (knowledge base + document) and what it means for the caller.
    protection: ProtectionOut = Field(default_factory=lambda: ProtectionOut())
    can_download: bool = True


class DocumentVersionOut(ORMModel):
    version: int
    filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    restored_from: int | None = None
    created_by: str | None
    created_by_name: str | None = None
    created_at: datetime


class VersionTextOut(BaseModel):
    version: int
    # False when the version was never parsed (or its parse result is gone).
    available: bool
    lines: list[str] = Field(default_factory=list)
    truncated: bool = False


class DiffLineOut(BaseModel):
    op: Literal["equal", "add", "del"]
    text: str
    old_no: int | None
    new_no: int | None


class VersionCompareOut(BaseModel):
    base: DocumentVersionOut
    target: DocumentVersionOut
    available: bool
    same_file: bool
    added: int = 0
    removed: int = 0
    hunks: list[list[DiffLineOut]] = Field(default_factory=list)
    truncated: bool = False


class DocumentDetail(DocumentOut):
    kb_name: str
    kb_review_interval_days: int | None = None
    versions: list[DocumentVersionOut]


class DocumentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=512)
    tags: list[str] | None = Field(default=None, max_length=50)
    metadata: dict[str, Any] | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    classification: ClassificationName | None = None
    # Protection overrides (manage permission); null = as the knowledge base.
    watermark: bool | None = None
    copy_protect: bool | None = None
    download_permission: AclPermissionName | None = None
    # Applied when sent: owner null = none (the uploader gets reminders);
    # review interval null = as the knowledge base, 0 = never.
    owner_id: str | None = Field(default=None, max_length=32)
    review_interval_days: int | None = Field(default=None, ge=0, le=3650)

    @field_validator("tags")
    @classmethod
    def _clean_tags(cls, tags: list[str] | None) -> list[str] | None:
        if tags is None:
            return None
        return list(dict.fromkeys(t.strip() for t in tags if t.strip()))


class DocumentLifecycleIn(BaseModel):
    action: LifecycleActionName
    reason: str | None = Field(default=None, max_length=500)


MAX_ONLINE_CHARS = 500_000


class MarkdownCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=MAX_ONLINE_CHARS)
    tags: list[str] = Field(default_factory=list, max_length=50)


class DocumentContentOut(BaseModel):
    version: int
    filename: str
    mime_type: str
    content: str


class DocumentContentUpdate(BaseModel):
    content: str = Field(min_length=1, max_length=MAX_ONLINE_CHARS)
    # The version the edit started from; a newer one means someone else saved first.
    base_version: int = Field(ge=1)


class DocumentReviewIn(BaseModel):
    note: str | None = Field(default=None, max_length=500)


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


class PagePreviewOut(BaseModel):
    index: int
    url: str
    width: int | None = None
    height: int | None = None


class PreviewOut(BaseModel):
    # "file": the original inline (`url`); "pages": page images only (`pages`, watermarked
    # when the document has a watermark); "none": no page images, text only.
    mode: Literal["file", "pages", "none"] = "file"
    url: str | None = None
    filename: str
    mime_type: str
    expires_in: int
    pages: list[PagePreviewOut] = Field(default_factory=list)


class BatchReprocessIn(BaseModel):
    """Re-enqueue parse for selected documents in a knowledge base."""

    document_ids: list[str] = Field(default_factory=list, max_length=500)
    status: str | None = Field(default=None, max_length=32)
    missing_page_images: bool = False
    limit: int = Field(default=100, ge=1, le=500)


class BatchReprocessSkip(BaseModel):
    id: str
    reason: str


class BatchReprocessOut(BaseModel):
    queued: list[str]
    skipped: list[BatchReprocessSkip]
    total_candidates: int


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
