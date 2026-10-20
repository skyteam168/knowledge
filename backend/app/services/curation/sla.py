"""Default due dates for knowledge gaps from priority SLA settings."""

from __future__ import annotations

from datetime import timedelta

from app.core.config import Settings
from app.models import KnowledgeGap
from app.models.base import utcnow

_PRIORITY_ATTR = {
    "critical": "gap_sla_hours_critical",
    "high": "gap_sla_hours_high",
    "normal": "gap_sla_hours_normal",
    "low": "gap_sla_hours_low",
}


def sla_hours(settings: Settings, priority: str | None) -> int:
    key = _PRIORITY_ATTR.get((priority or "normal").lower(), "gap_sla_hours_normal")
    return int(getattr(settings, key))


def apply_gap_sla(
    gap: KnowledgeGap, settings: Settings, *, force: bool = False
) -> None:
    """Fill `due_at` from priority when missing (or always when `force`)."""
    if gap.due_at is not None and not force:
        return
    hours = sla_hours(settings, gap.priority)
    gap.due_at = utcnow() + timedelta(hours=hours)
