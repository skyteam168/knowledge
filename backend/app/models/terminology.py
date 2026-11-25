"""Org-scoped terminology entities and aliases for query expansion."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    IdMixin,
    TenantMixin,
    TimestampMixin,
    created_at_column,
)


class TerminologyEntityType(StrEnum):
    DEVICE = "device"
    PROCESS = "process"
    DEFECT = "defect"
    POLICY = "policy"
    IT_TERM = "it_term"
    OTHER = "other"
    # Industrial tagging (aligned with StructuredObjectType / KoType for pilot)
    COMPONENT = "component"
    FAILURE_MODE = "failure_mode"


class TerminologyStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class TerminologyLang(StrEnum):
    ZH = "zh"
    EN = "en"
    VI = "vi"
    ANY = "any"


class TerminologyEntity(IdMixin, TenantMixin, TimestampMixin, Base):
    """A canonical business / IT term within one organization."""

    __tablename__ = "terminology_entities"
    __table_args__ = (
        Index("ix_terminology_entities_org_type", "org_id", "entity_type"),
        Index("ix_terminology_entities_org_status", "org_id", "status"),
    )

    canonical_name: Mapped[str] = mapped_column(String(256), nullable=False)
    entity_type: Mapped[str] = mapped_column(
        String(32), default=TerminologyEntityType.OTHER.value, nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(16), default=TerminologyStatus.ACTIVE.value, nullable=False
    )


class TerminologyAlias(IdMixin, TenantMixin, Base):
    """Alternate spelling / language form that maps to a terminology entity."""

    __tablename__ = "terminology_aliases"
    __table_args__ = (
        UniqueConstraint("org_id", "alias_normalized", name="uq_terminology_aliases_org_norm"),
        Index("ix_terminology_aliases_entity", "entity_id"),
    )

    entity_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("terminology_entities.id", ondelete="CASCADE"),
        nullable=False,
    )
    alias: Mapped[str] = mapped_column(String(256), nullable=False)
    # Lowercased form for uniqueness and lookup (set in service layer).
    alias_normalized: Mapped[str] = mapped_column(String(256), nullable=False)
    lang: Mapped[str] = mapped_column(String(8), default=TerminologyLang.ANY.value, nullable=False)
    created_at: Mapped[datetime] = created_at_column()


class TerminologyRelationKind(StrEnum):
    INHERITS = "inherits"
    CONTAINS = "contains"
    RELATED = "related"


class TerminologyRelation(IdMixin, TenantMixin, TimestampMixin, Base):
    """DataHub-style term hierarchy / association edges."""

    __tablename__ = "terminology_relations"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "from_id",
            "to_id",
            "kind",
            name="uq_terminology_relations_edge",
        ),
        Index("ix_terminology_relations_from", "org_id", "from_id"),
        Index("ix_terminology_relations_to", "org_id", "to_id"),
    )

    from_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("terminology_entities.id", ondelete="CASCADE"),
        nullable=False,
    )
    to_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("terminology_entities.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(32))
