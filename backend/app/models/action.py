"""Ontology Action / rules / approvals (Wave C Kinetic)."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, JsonType, TenantMixin, TimestampMixin


class RuleVerdict(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_CONFIRM = "require_confirm"


class ActionRisk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ActionExecutionStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DENIED = "denied"
    AWAITING_APPROVAL = "awaiting_approval"
    CANCELLED = "cancelled"


class OntologyRule(IdMixin, TenantMixin, TimestampMixin, Base):
    """Priority-ordered business rule evaluated before actions / transitions."""

    __tablename__ = "ontology_rules"
    __table_args__ = (
        Index("ix_ontology_rules_org_priority", "org_id", "priority"),
        Index("ix_ontology_rules_org_enabled", "org_id", "enabled"),
    )

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String(512))
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # {"action":"device.set_status","when":{"standard_status":"RUNNING"},"to":"MAINTENANCE"}
    condition: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, nullable=False)
    verdict: Mapped[str] = mapped_column(
        String(32), default=RuleVerdict.ALLOW.value, nullable=False
    )
    message: Mapped[str | None] = mapped_column(String(512))
    created_by: Mapped[str | None] = mapped_column(String(32))


class ActionType(IdMixin, TenantMixin, TimestampMixin, Base):
    """Registered action type (schema + risk + systems)."""

    __tablename__ = "action_types"
    __table_args__ = (
        Index("ix_action_types_org_name", "org_id", "name", unique=True),
    )

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String(512))
    input_schema: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, nullable=False)
    preconditions: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, nullable=False)
    risk: Mapped[str] = mapped_column(String(16), default=ActionRisk.LOW.value, nullable=False)
    systems: Mapped[list[Any]] = mapped_column(JsonType, default=list, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(32))


class ActionApproval(IdMixin, TenantMixin, TimestampMixin, Base):
    """Single-use high-risk approval (30 minutes)."""

    __tablename__ = "action_approvals"
    __table_args__ = (Index("ix_action_approvals_org_actor", "org_id", "actor_id"),)

    action_type: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledge_risk: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ActionExecution(IdMixin, TenantMixin, TimestampMixin, Base):
    """Idempotent action run record + audit trail."""

    __tablename__ = "action_executions"
    __table_args__ = (
        Index("ix_action_executions_org_idem", "org_id", "idempotency_key", unique=True),
        Index("ix_action_executions_org_type", "org_id", "action_type"),
    )

    action_type: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(32), nullable=False)
    on_behalf_of: Mapped[str | None] = mapped_column(String(32))
    input: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default=ActionExecutionStatus.PENDING.value, nullable=False
    )
    result: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    approval_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("action_approvals.id", ondelete="SET NULL")
    )
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    compensated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
