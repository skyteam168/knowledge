"""Organization semantic layer (Ontology Studio OS1): draft → published versions."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, JsonType, TenantMixin, TimestampMixin


class SemanticModelStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class SemanticItemStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"


class SemanticModelVersion(IdMixin, TenantMixin, TimestampMixin, Base):
    """One semantic model revision per org; at most one active published."""

    __tablename__ = "semantic_model_versions"
    __table_args__ = (
        Index("ix_semantic_model_versions_org_status", "org_id", "status"),
        Index(
            "ix_semantic_model_versions_org_active",
            "org_id",
            "is_active",
        ),
    )

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=SemanticModelStatus.DRAFT.value, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[str | None] = mapped_column(String(512))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by: Mapped[str | None] = mapped_column(String(32))
    created_by: Mapped[str | None] = mapped_column(String(32))


class SemanticEntity(IdMixin, TenantMixin, TimestampMixin, Base):
    """Business entity definition within a semantic model version."""

    __tablename__ = "semantic_entities"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "version_id",
            "local_name",
            name="uq_semantic_entities_version_local",
        ),
        Index("ix_semantic_entities_version", "org_id", "version_id"),
    )

    version_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("semantic_model_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    local_name: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1024))
    object_type: Mapped[str | None] = mapped_column(String(64))
    owners: Mapped[list[Any]] = mapped_column(JsonType, default=list, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=SemanticItemStatus.DRAFT.value, nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(String(32))


class SemanticAttribute(IdMixin, TenantMixin, TimestampMixin, Base):
    """Attribute on a semantic entity (business name + type hint)."""

    __tablename__ = "semantic_attributes"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "entity_id",
            "name",
            name="uq_semantic_attributes_entity_name",
        ),
        Index("ix_semantic_attributes_entity", "org_id", "entity_id"),
        Index("ix_semantic_attributes_version", "org_id", "version_id"),
    )

    version_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("semantic_model_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    entity_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("semantic_entities.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1024))
    attr_kind: Mapped[str] = mapped_column(String(32), default="string", nullable=False)
    unit: Mapped[str | None] = mapped_column(String(32))
    enum_map: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, nullable=False)
    labels: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, nullable=False)
    compute_expr: Mapped[str | None] = mapped_column(Text)
    compute_inputs: Mapped[list[Any]] = mapped_column(JsonType, default=list, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=SemanticItemStatus.DRAFT.value, nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(String(32))


class SemanticEvidence(IdMixin, TenantMixin, TimestampMixin, Base):
    """Link a semantic entity/attribute to KO / document / chunk evidence."""

    __tablename__ = "semantic_evidences"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "version_id",
            "target_kind",
            "target_id",
            "evidence_kind",
            "evidence_id",
            name="uq_semantic_evidences_target_ref",
        ),
        Index("ix_semantic_evidences_version", "org_id", "version_id"),
        Index("ix_semantic_evidences_target", "org_id", "target_kind", "target_id"),
    )

    version_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("semantic_model_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    target_id: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    evidence_id: Mapped[str] = mapped_column(String(64), nullable=False)
    note: Mapped[str | None] = mapped_column(String(512))
    created_by: Mapped[str | None] = mapped_column(String(32))


class SemanticMapping(IdMixin, TenantMixin, TimestampMixin, Base):
    """Physical column representation of a semantic attribute (Represented by)."""

    __tablename__ = "semantic_mappings"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "attribute_id",
            "table_name",
            "column_name",
            name="uq_semantic_mappings_attr_col",
        ),
        Index("ix_semantic_mappings_attr", "org_id", "attribute_id"),
        Index("ix_semantic_mappings_version", "org_id", "version_id"),
    )

    version_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("semantic_model_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    attribute_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("semantic_attributes.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_id: Mapped[str | None] = mapped_column(String(32))
    table_name: Mapped[str] = mapped_column(String(128), nullable=False)
    column_name: Mapped[str] = mapped_column(String(128), nullable=False)
    source_of_truth: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    freshness_sla_seconds: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(
        String(16), default=SemanticItemStatus.DRAFT.value, nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(String(32))
