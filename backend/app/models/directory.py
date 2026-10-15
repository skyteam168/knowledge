"""Organization directory sources (WeCom / DingTalk / Weaver e-cology / Excel) and sync runs.

At most one source per org is primary: it owns the department tree, users, their department
memberships and job titles. Other sources only bind external identities to existing users
(used by QR-code login). Credentials are stored encrypted (see app.core.crypto).
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, JsonType, TenantMixin, TimestampMixin, created_at_column


class DirectorySourceType(StrEnum):
    WECOM = "wecom"
    DINGTALK = "dingtalk"
    WEAVER = "weaver"
    EXCEL = "excel"


class SyncMode(StrEnum):
    PREVIEW = "preview"
    APPLY = "apply"


class SyncStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    # Stopped by the disable-ratio guard; rerun with force to apply.
    ABORTED = "aborted"


class DirectorySource(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "directory_sources"

    type: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    config_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    # 0 = manual only.
    sync_interval_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str | None] = mapped_column(String(16))
    last_run_id: Mapped[str | None] = mapped_column(String(32))
    created_by: Mapped[str | None] = mapped_column(String(32))


class DirectorySyncRun(IdMixin, TenantMixin, Base):
    __tablename__ = "directory_sync_runs"
    __table_args__ = (Index("ix_directory_sync_runs_source_started", "source_id", "started_at"),)

    source_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("directory_sources.id", ondelete="CASCADE"), nullable=False
    )
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    forced: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # {departments: {created, updated, moved, archived, restored}, users: {...}, ...}
    stats: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, nullable=False)
    # Truncated change lists for review: {departments: [...], users: [...]}.
    changes: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    triggered_by: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime] = created_at_column()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
