from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TenantMixin, TimestampMixin


class Organization(IdMixin, TimestampMixin, Base):
    """Tenant root. Its own id is the org_id carried by every business table."""

    __tablename__ = "organizations"

    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)


LOCAL_SOURCE = "local"


class DepartmentStatus(StrEnum):
    ACTIVE = "active"
    # Removed upstream: hidden from pickers, existing ACL entries keep working.
    ARCHIVED = "archived"


class Department(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "departments"
    __table_args__ = (UniqueConstraint("org_id", "source", "external_id"),)

    parent_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("departments.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    # Materialized path of ancestor ids including self: "/root/child/self/"
    path: Mapped[str] = mapped_column(String(1024), index=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # "local" or the directory source type that owns this department.
    source: Mapped[str] = mapped_column(String(16), default=LOCAL_SOURCE, nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(
        String(16), default=DepartmentStatus.ACTIVE.value, nullable=False
    )

    @property
    def ancestor_ids(self) -> list[str]:
        return [p for p in self.path.split("/") if p]


class User(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("org_id", "username"),)

    keycloak_sub: Mapped[str | None] = mapped_column(String(64), unique=True)
    username: Mapped[str] = mapped_column(String(128), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(128))
    # Primary department; every membership (including this one) is in user_departments.
    department_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("departments.id", ondelete="SET NULL"), index=True
    )
    employee_no: Mapped[str | None] = mapped_column(String(64), index=True)
    mobile: Mapped[str | None] = mapped_column(String(32))
    job_title: Mapped[str | None] = mapped_column(String(128))
    source: Mapped[str] = mapped_column(String(16), default=LOCAL_SOURCE, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    claims_hash: Mapped[str | None] = mapped_column(String(64))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserDepartment(TenantMixin, Base):
    __tablename__ = "user_departments"

    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    department_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("departments.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source: Mapped[str] = mapped_column(String(16), default=LOCAL_SOURCE, nullable=False)


class UserIdentity(IdMixin, TenantMixin, TimestampMixin, Base):
    """An account of the user in an external directory (WeCom / DingTalk / Weaver ...)."""

    __tablename__ = "user_identities"
    __table_args__ = (UniqueConstraint("org_id", "provider", "external_id"),)

    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    union_id: Mapped[str | None] = mapped_column(String(128))


class Group(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "groups"
    __table_args__ = (UniqueConstraint("org_id", "name"),)

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(16), default="local", nullable=False)


class UserGroup(TenantMixin, Base):
    __tablename__ = "user_groups"

    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    group_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    source: Mapped[str] = mapped_column(String(16), default="local", nullable=False)


class Role(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("org_id", "code"),)

    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Granted automatically to users created by directory sync or first login.
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Permission(IdMixin, Base):
    """Global permission catalog (system dictionary, not tenant data)."""

    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)


class RolePermission(TenantMixin, Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    permission_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True
    )


class UserRole(TenantMixin, Base):
    __tablename__ = "user_roles"

    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    source: Mapped[str] = mapped_column(String(16), default="local", nullable=False)
