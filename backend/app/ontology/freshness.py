"""Attribute / object freshness helpers (Wave B Task7)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class FreshnessReport:
    stale: bool
    age_seconds: int | None
    sla_seconds: int | None
    source_of_truth: list[dict[str, Any]]

    def as_meta(self) -> dict[str, Any]:
        return {
            "stale": self.stale,
            "age_seconds": self.age_seconds,
            "sla_seconds": self.sla_seconds,
            "source_of_truth": list(self.source_of_truth),
        }


def compute_freshness(
    *,
    updated_at: datetime | None,
    now: datetime | None = None,
    sla_seconds: int | None,
    source_of_truth: list[dict[str, Any]] | None = None,
) -> FreshnessReport:
    """Mark stale when age exceeds SLA; missing updated_at → unknown age, stale if SLA set."""
    clock = now or datetime.now(UTC)
    if updated_at is not None and updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    age: int | None = None
    if updated_at is not None:
        age = max(0, int((clock - updated_at).total_seconds()))
    stale = False
    if sla_seconds is not None and sla_seconds > 0:
        if age is None or age > sla_seconds:
            stale = True
    return FreshnessReport(
        stale=stale,
        age_seconds=age,
        sla_seconds=sla_seconds,
        source_of_truth=list(source_of_truth or ()),
    )
