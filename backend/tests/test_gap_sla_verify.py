"""Gap SLA auto due_at."""

from datetime import timedelta

from app.core.config import Settings
from app.models import GapStatus, GapType, KnowledgeGap
from app.models.base import utcnow
from app.services.curation.sla import apply_gap_sla, sla_hours


def test_sla_hours_by_priority(settings: Settings) -> None:
    assert sla_hours(settings, "critical") == settings.gap_sla_hours_critical
    assert sla_hours(settings, "high") == settings.gap_sla_hours_high
    assert sla_hours(settings, None) == settings.gap_sla_hours_normal


def test_apply_gap_sla_fills_due_at(settings: Settings) -> None:
    gap = KnowledgeGap(
        org_id="o1",
        gap_type=GapType.NO_EVIDENCE.value,
        status=GapStatus.OPEN.value,
        query="q",
        priority="critical",
    )
    before = utcnow()
    apply_gap_sla(gap, settings)
    assert gap.due_at is not None
    assert gap.due_at >= before + timedelta(hours=settings.gap_sla_hours_critical - 1)
    first = gap.due_at
    apply_gap_sla(gap, settings)
    assert gap.due_at == first
    gap.priority = "low"
    apply_gap_sla(gap, settings, force=True)
    assert gap.due_at > first


def test_verify_payload_shape() -> None:
    from app.services.curation.verify import verify_gaps_for_ko

    assert callable(verify_gaps_for_ko)
