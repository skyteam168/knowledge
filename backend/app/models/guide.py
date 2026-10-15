"""Per-user progress of the in-app onboarding tours (personal UI state, not audited)."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TenantMixin, utcnow


class GuideStatus(StrEnum):
    COMPLETED = "completed"
    SKIPPED = "skipped"


class UserGuideProgress(IdMixin, TenantMixin, Base):
    __tablename__ = "user_guide_progress"
    __table_args__ = (UniqueConstraint("user_id", "guide_key"),)

    user_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    guide_key: Mapped[str] = mapped_column(String(64), nullable=False)
    # Tours are re-shown when the frontend bumps their version.
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
