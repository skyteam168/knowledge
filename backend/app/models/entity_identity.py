"""Canonical industrial entity + multi-system identifier mappings (Wave A Task2)."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TenantMixin, TimestampMixin


class CanonicalEntityStatus(StrEnum):
    ACTIVE = "active"
    CONFLICT = "conflict"
    MERGED = "merged"
    DEPRECATED = "deprecated"


class CanonicalEntity(IdMixin, TenantMixin, TimestampMixin, Base):
    """Org-scoped canonical identity independent of any single source system PK."""

    __tablename__ = "canonical_entities"
    __table_args__ = (
        Index("ix_canonical_entities_org_type", "org_id", "object_type"),
        Index("ix_canonical_entities_org_status", "org_id", "status"),
    )

    object_type: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=CanonicalEntityStatus.ACTIVE.value, nullable=False
    )
    # Optional mirror pointer (equip_* or structured_records id)
    structured_object_type: Mapped[str | None] = mapped_column(String(64))
    structured_object_id: Mapped[str | None] = mapped_column(String(32))


class EntityIdentifier(IdMixin, TenantMixin, TimestampMixin, Base):
    """External ID under a source system that resolves to a CanonicalEntity."""

    __tablename__ = "entity_identifiers"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "system",
            "id_kind",
            "external_id",
            name="uq_entity_identifiers_org_system_kind_ext",
        ),
        Index("ix_entity_identifiers_canonical", "org_id", "canonical_id"),
        Index("ix_entity_identifiers_lookup", "org_id", "system", "external_id"),
    )

    canonical_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("canonical_entities.id", ondelete="CASCADE"),
        nullable=False,
    )
    system: Mapped[str] = mapped_column(String(32), nullable=False)
    id_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="external_id")
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
