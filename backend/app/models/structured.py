"""Local structured mirror (equipment + extensible domains) linked to terminology / KOs."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, JsonType, TenantMixin, TimestampMixin


class StructuredSourceType(StrEnum):
    ERP = "erp"
    MES = "mes"
    MANUAL = "manual"
    QMS = "qms"
    PLM = "plm"
    WMS = "wms"


class StructuredDomainKind(StrEnum):
    """equipment = dedicated equip_* tables; generic = structured_records."""

    EQUIPMENT = "equipment"
    GENERIC = "generic"


class StructuredObjectType(StrEnum):
    """Structured mirror object kinds.

    ``device`` / ``work_order`` / ``spare_part`` map to dedicated ``equip_*`` tables.
    ISA-95 / FMEA kinds (site…event) are declared in the ontology contract now; until
    O1.3 dedicated tables land they may live in ``structured_records``.
    """

    DEVICE = "device"
    WORK_ORDER = "work_order"
    SPARE_PART = "spare_part"
    # ISA-95 asset hierarchy
    SITE = "site"
    AREA = "area"
    LINE = "line"
    EQUIPMENT = "equipment"
    COMPONENT = "component"
    # Process / quality / FMEA
    MATERIAL = "material"
    OPERATION = "operation"
    PROCESS_PARAMETER = "process_parameter"
    FAILURE_MODE = "failure_mode"
    EVENT = "event"
    # Manufacturing closed-loop (fixture ABox + Kinetic actions)
    FACTORY = "factory"
    CUSTOMER_ORDER = "customer_order"
    PRODUCTION_ORDER = "production_order"
    INVENTORY = "inventory"
    EMPLOYEE = "employee"


class ObjectEndpointKind(StrEnum):
    """Endpoint of a typed object_relations edge."""

    TERMINOLOGY = "terminology"
    KO = "ko"
    STRUCTURED = "structured"


class ObjectRelationType(StrEnum):
    """Directed industrial / structured object relations (O2.1)."""

    HAS_PART = "has_part"
    LOCATED_IN = "located_in"
    HAS_FAILURE_MODE = "has_failure_mode"
    CAUSED_BY = "caused_by"
    CONSUMES = "consumes"
    WORK_ORDER_FOR = "work_order_for"
    SPARE_FOR = "spare_for"
    BELONGS_TO = "belongs_to"
    RESPONSIBLE_FOR = "responsible_for"


class StructuredSource(IdMixin, TenantMixin, TimestampMixin, Base):
    """Registered structured data source; ``meta.connector`` enables CSV/REST pull into mirror tables."""

    __tablename__ = "structured_sources"
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_structured_sources_org_name"),)

    type: Mapped[str] = mapped_column(
        String(16), default=StructuredSourceType.MANUAL.value, nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    meta: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(32))


class StructuredDomain(IdMixin, TenantMixin, TimestampMixin, Base):
    """Business domain under structured mirror (equipment / process / material / qc / custom)."""

    __tablename__ = "structured_domains"
    __table_args__ = (UniqueConstraint("org_id", "code", name="uq_structured_domains_org_code"),)

    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(
        String(16), default=StructuredDomainKind.GENERIC.value, nullable=False
    )
    description: Mapped[str | None] = mapped_column(String(512))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(32))


class StructuredRecord(IdMixin, TenantMixin, TimestampMixin, Base):
    """Generic mirrored business row for non-equipment domains."""

    __tablename__ = "structured_records"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "source_id",
            "object_type",
            "external_id",
            name="uq_structured_records_source_type_ext",
        ),
        Index("ix_structured_records_domain", "org_id", "domain_id"),
        Index("ix_structured_records_ext", "org_id", "object_type", "external_id"),
    )

    domain_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("structured_domains.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("structured_sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    object_type: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    # ISA-95 hierarchy / FMEA ownership (denormalized from attrs for query).
    parent_object_type: Mapped[str | None] = mapped_column(String(64))
    parent_external_id: Mapped[str | None] = mapped_column(String(64))
    # S2 event timeline denorm (from attrs.occurred_at / ended_at / event_type).
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    event_type: Mapped[str | None] = mapped_column(String(32))
    attrs: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(32))


class EquipDevice(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "equip_devices"
    __table_args__ = (
        UniqueConstraint(
            "org_id", "source_id", "external_id", name="uq_equip_devices_source_ext"
        ),
        Index("ix_equip_devices_org_source", "org_id", "source_id"),
    )

    source_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("structured_sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    location: Mapped[str | None] = mapped_column(String(256))
    meta: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, nullable=False)


class EquipWorkOrder(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "equip_work_orders"
    __table_args__ = (
        UniqueConstraint(
            "org_id", "source_id", "external_id", name="uq_equip_work_orders_source_ext"
        ),
        Index("ix_equip_work_orders_org_source", "org_id", "source_id"),
        Index("ix_equip_work_orders_device_ext", "org_id", "device_external_id"),
    )

    source_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("structured_sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    device_external_id: Mapped[str | None] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="open", nullable=False)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    meta: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, nullable=False)


class EquipSparePart(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "equip_spare_parts"
    __table_args__ = (
        UniqueConstraint(
            "org_id", "source_id", "external_id", name="uq_equip_spare_parts_source_ext"
        ),
        Index("ix_equip_spare_parts_org_source", "org_id", "source_id"),
    )

    source_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("structured_sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    sku: Mapped[str | None] = mapped_column(String(64))
    qty_on_hand: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    meta: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, nullable=False)


class RelationCardinality(StrEnum):
    ONE_TO_ONE = "one_to_one"
    ONE_TO_MANY = "one_to_many"
    MANY_TO_ONE = "many_to_one"
    MANY_TO_MANY = "many_to_many"


class ObjectRelation(IdMixin, TenantMixin, TimestampMixin, Base):
    """Directed typed edge between terminology / KO / structured objects."""

    __tablename__ = "object_relations"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "relation_type",
            "from_kind",
            "from_id",
            "from_object_type",
            "to_kind",
            "to_id",
            "to_object_type",
            name="uq_object_relations_edge",
        ),
        Index("ix_object_relations_from", "org_id", "from_kind", "from_id"),
        Index("ix_object_relations_to", "org_id", "to_kind", "to_id"),
        Index("ix_object_relations_type", "org_id", "relation_type"),
    )

    relation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    from_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    from_id: Mapped[str] = mapped_column(String(32), nullable=False)
    from_object_type: Mapped[str | None] = mapped_column(String(64))
    to_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    to_id: Mapped[str] = mapped_column(String(32), nullable=False)
    to_object_type: Mapped[str | None] = mapped_column(String(64))
    cardinality: Mapped[str] = mapped_column(
        String(16), default=RelationCardinality.ONE_TO_MANY.value, nullable=False
    )
    attrs: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, nullable=False)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(String(32))


class StructuredEntityLink(IdMixin, TenantMixin, TimestampMixin, Base):
    """Maps a mirrored equipment row to a terminology entity and/or knowledge object."""

    __tablename__ = "structured_entity_links"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "object_type",
            "object_id",
            "terminology_entity_id",
            "ko_id",
            name="uq_structured_entity_links_edge",
        ),
        Index("ix_structured_entity_links_object", "org_id", "object_type", "object_id"),
        Index("ix_structured_entity_links_term", "org_id", "terminology_entity_id"),
        Index("ix_structured_entity_links_ko", "org_id", "ko_id"),
    )

    object_type: Mapped[str] = mapped_column(String(64), nullable=False)
    object_id: Mapped[str] = mapped_column(String(32), nullable=False)
    terminology_entity_id: Mapped[str | None] = mapped_column(
        String(32),
        ForeignKey("terminology_entities.id", ondelete="CASCADE"),
    )
    ko_id: Mapped[str | None] = mapped_column(
        String(32),
        ForeignKey("knowledge_objects.id", ondelete="CASCADE"),
    )
    created_by: Mapped[str | None] = mapped_column(String(32))
