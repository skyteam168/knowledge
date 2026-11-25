"""Canonical entity state history with valid time (Wave B Task8)."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TenantMixin, created_at_column


class EntityStateHistory(IdMixin, TenantMixin, Base):
    """Valid-time snapshot of a canonical entity's standard status."""

    __tablename__ = "entity_state_history"
    __table_args__ = (
        Index("ix_entity_state_history_canonical", "org_id", "canonical_id"),
        Index("ix_entity_state_history_valid", "org_id", "valid_from", "valid_to"),
    )

    canonical_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("canonical_entities.id", ondelete="CASCADE"),
        nullable=False,
    )
    standard_status: Mapped[str] = mapped_column(String(32), nullable=False)
    status_label: Mapped[str | None] = mapped_column(String(64))
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recorded_at: Mapped[datetime] = created_at_column()
    source: Mapped[str | None] = mapped_column(String(64))
