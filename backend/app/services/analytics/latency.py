"""Latency statistics: exact daily percentiles plus a fixed histogram for multi-day ranges.

Daily p50/p95 are exact; percentiles over several days are estimated from the summed
histograms (linear interpolation inside the bucket), which keeps the summary rows tiny.
"""

import math
from collections.abc import Iterable, Sequence
from typing import Any

# Upper bounds (ms) of the histogram buckets; one extra overflow bucket follows.
LATENCY_BUCKETS_MS: tuple[float, ...] = (
    10,
    25,
    50,
    100,
    200,
    300,
    500,
    750,
    1000,
    1500,
    2000,
    3000,
    5000,
    7500,
    10000,
    15000,
    20000,
    30000,
    60000,
)


def percentile(values: Sequence[float], q: float) -> float | None:
    """Linear-interpolated percentile (q in [0, 1]) of unsorted values."""
    if not values:
        return None
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return float(ordered[lo])
    return float(ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo))


def histogram(values: Iterable[float]) -> list[int]:
    hist = [0] * (len(LATENCY_BUCKETS_MS) + 1)
    for v in values:
        idx = next((i for i, b in enumerate(LATENCY_BUCKETS_MS) if v <= b), len(LATENCY_BUCKETS_MS))
        hist[idx] += 1
    return hist


def hist_percentile(hist: Sequence[int], q: float) -> float | None:
    total = sum(hist)
    if total == 0:
        return None
    target = q * total
    cumulative = 0
    for i, count in enumerate(hist):
        if count == 0:
            continue
        if cumulative + count >= target:
            if i >= len(LATENCY_BUCKETS_MS):
                return float(LATENCY_BUCKETS_MS[-1])
            lower = LATENCY_BUCKETS_MS[i - 1] if i > 0 else 0.0
            upper = LATENCY_BUCKETS_MS[i]
            return float(lower + (upper - lower) * (target - cumulative) / count)
        cumulative += count
    return float(LATENCY_BUCKETS_MS[-1])


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


def summarize(values: Sequence[float]) -> dict[str, Any]:
    return {
        "count": len(values),
        "p50": _round(percentile(values, 0.5)),
        "p95": _round(percentile(values, 0.95)),
        "avg": _round(sum(values) / len(values)) if values else None,
        "hist": histogram(values),
    }


def merge(stats: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Combine daily summaries: counts and histograms add up, percentiles are estimated."""
    hist = [0] * (len(LATENCY_BUCKETS_MS) + 1)
    count = 0
    weighted = 0.0
    non_empty = [s for s in stats if int(s.get("count") or 0) > 0]
    for s in non_empty:
        n = int(s["count"])
        count += n
        weighted += float(s.get("avg") or 0.0) * n
        for i, c in enumerate(s.get("hist") or []):
            if i < len(hist):
                hist[i] += int(c)
    if len(non_empty) == 1:
        only = non_empty[0]
        return {
            "count": count,
            "p50": only.get("p50"),
            "p95": only.get("p95"),
            "avg": only.get("avg"),
        }
    return {
        "count": count,
        "p50": _round(hist_percentile(hist, 0.5)),
        "p95": _round(hist_percentile(hist, 0.95)),
        "avg": _round(weighted / count) if count else None,
    }
