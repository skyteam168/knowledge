"""Runs of the admin assistant: what was asked, how it was understood, the plan and every event.

A run is the approval unit: a plan can only be executed from its run, once, by its owner,
before `expires_at`.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, JsonType, TenantMixin, TimestampMixin


class AgentRunStatus(StrEnum):
    RUNNING = "running"
    ANSWERED = "answered"
    CLARIFY = "clarify"
    OUT_OF_SCOPE = "out_of_scope"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ERROR = "error"


class AgentRun(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "admin_agent_runs"
    __table_args__ = (Index("ix_admin_agent_runs_user_created", "org_id", "user_id", "created_at"),)

    user_id: Mapped[str] = mapped_column(String(32), nullable=False)
    user_name: Mapped[str] = mapped_column(String(128), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str | None] = mapped_column(String(16))
    intent: Mapped[str | None] = mapped_column(String(32))
    # How the understanding stage got its result: "tools" (native function call) or "json".
    understand_mode: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    risk: Mapped[str | None] = mapped_column(String(16))
    # Exactly the steps the admin approves; execution reads them from here, never the client.
    steps: Mapped[list[dict[str, Any]] | None] = mapped_column(JsonType)
    events: Mapped[list[dict[str, Any]]] = mapped_column(JsonType, default=list, nullable=False)
    exec_events: Mapped[list[dict[str, Any]]] = mapped_column(
        JsonType, default=list, nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
