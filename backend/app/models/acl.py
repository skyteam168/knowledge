from datetime import datetime

from sqlalchemy import Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TenantMixin, created_at_column


class ResourceAcl(IdMixin, TenantMixin, Base):
    __tablename__ = "resource_acl"
    __table_args__ = (
        UniqueConstraint(
            "resource_type",
            "resource_id",
            "principal_type",
            "principal_id",
            "permission",
            name="uq_resource_acl_entry",
        ),
        Index("ix_resource_acl_resource", "org_id", "resource_type", "resource_id"),
        Index("ix_resource_acl_principal", "org_id", "principal_type", "principal_id"),
    )

    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(64), nullable=False)
    principal_type: Mapped[str] = mapped_column(String(16), nullable=False)
    principal_id: Mapped[str] = mapped_column(String(64), nullable=False)
    permission: Mapped[str] = mapped_column(String(16), nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = created_at_column()
