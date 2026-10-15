from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- organizations ----------------------------------------------------------


class OrganizationOut(ORMModel):
    id: str
    code: str
    name: str
    status: str
    created_at: datetime


class OrganizationCreate(BaseModel):
    code: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")
    name: str = Field(min_length=1, max_length=128)


class OrganizationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    status: str | None = Field(default=None, pattern=r"^(active|disabled)$")


# ---- departments ------------------------------------------------------------


class DepartmentOut(ORMModel):
    id: str
    parent_id: str | None
    name: str
    sort_order: int
    source: str = "local"
    external_id: str | None = None
    status: str = "active"
    path_name: str | None = None


class DepartmentNode(DepartmentOut):
    children: list["DepartmentNode"] = []


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    parent_id: str | None = None
    sort_order: int = 0


class DepartmentUpdate(BaseModel):
    """Only fields present in the payload are applied; `parent_id: null` moves to root."""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    parent_id: str | None = None
    sort_order: int | None = None


# ---- groups / roles / permissions -------------------------------------------


class GroupOut(ORMModel):
    id: str
    name: str
    description: str | None
    source: str
    member_count: int = 0


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None


class GroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None


class PermissionOut(ORMModel):
    code: str
    name: str


class RoleOut(ORMModel):
    id: str
    code: str
    name: str
    description: str | None
    is_system: bool
    is_default: bool = False
    permissions: list[str] = []


class RoleCreate(BaseModel):
    code: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9_\-:]+$")
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    is_default: bool | None = None


class PermissionAssign(BaseModel):
    permissions: list[str]


class RoleBulkAssign(BaseModel):
    """Grant / revoke a role for everyone in the given departments (incl. sub-departments)
    or user groups."""

    action: Literal["grant", "revoke"]
    department_ids: list[str] = Field(default_factory=list, max_length=200)
    group_ids: list[str] = Field(default_factory=list, max_length=200)
    include_inactive: bool = False
    dry_run: bool = False

    @model_validator(mode="after")
    def _has_target(self) -> "RoleBulkAssign":
        if not self.department_ids and not self.group_ids:
            raise ValueError("Select at least one department or group")
        return self


class RoleBulkResult(BaseModel):
    matched: int
    changed: int
    unchanged: int
    # revoke only: links owned by another source (e.g. Keycloak) or the caller's own.
    skipped: int
    dry_run: bool


# ---- users ------------------------------------------------------------------


class RoleBrief(ORMModel):
    id: str
    code: str
    name: str


class GroupBrief(ORMModel):
    id: str
    name: str


class UserDepartmentBrief(BaseModel):
    id: str
    name: str
    path_name: str
    is_primary: bool


class UserIdentityBrief(ORMModel):
    provider: str
    external_id: str


class PasswordLoginOut(BaseModel):
    username: str
    created: bool
    temporary_password: str


class UserOut(ORMModel):
    id: str
    username: str
    email: str | None
    display_name: str | None
    department_id: str | None
    employee_no: str | None = None
    mobile: str | None = None
    job_title: str | None = None
    source: str = "local"
    is_active: bool
    keycloak_bound: bool = False
    last_login_at: datetime | None
    created_at: datetime
    departments: list[UserDepartmentBrief] = []


class UserDetail(UserOut):
    roles: list[RoleBrief] = []
    groups: list[GroupBrief] = []
    identities: list[UserIdentityBrief] = []


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    email: EmailStr | None = None
    display_name: str | None = Field(default=None, max_length=128)
    department_id: str | None = None
    # Extra departments besides the primary one.
    department_ids: list[str] = Field(default_factory=list, max_length=50)
    employee_no: str | None = Field(default=None, max_length=64)
    mobile: str | None = Field(default=None, max_length=32)
    job_title: str | None = Field(default=None, max_length=128)


class UserUpdate(BaseModel):
    """Only fields present in the payload are applied; `department_id: null` clears it.

    For users owned by a directory source, profile and department fields are read-only.
    """

    email: EmailStr | None = None
    display_name: str | None = Field(default=None, max_length=128)
    department_id: str | None = None
    department_ids: list[str] | None = Field(default=None, max_length=50)
    employee_no: str | None = Field(default=None, max_length=64)
    mobile: str | None = Field(default=None, max_length=32)
    job_title: str | None = Field(default=None, max_length=128)
    is_active: bool | None = None


class IdsPayload(BaseModel):
    ids: list[str]


# ---- current user -----------------------------------------------------------


class MeResponse(BaseModel):
    id: str
    username: str
    display_name: str | None
    email: str | None
    org: OrganizationOut
    department: DepartmentOut | None
    roles: list[RoleBrief]
    groups: list[GroupBrief]
    permissions: list[str]
    is_platform_admin: bool
