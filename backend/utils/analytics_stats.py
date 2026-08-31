"""Response-time statistics shared by the analytics surfaces.

The performance section needs more than average/fastest/slowest: production
monitoring asks about *median* and *p95* latency and a response-time
distribution. Both the MongoDB repository and the in-memory test fake compute
these from the raw per-assistant-message ``response_time`` values using this
module, so their output is identical and unit-testable in isolation.

Statistics are computed with the nearest-rank method on the sorted values
(standard P95 semantics). The histogram buckets are:
  <1s, 1-2s, 2-5s, 5-10s, 10s+
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Latency histogram bucket lower bounds (seconds). Values below the first
# bound fall into "<1s"; values >= the last bound fall into "10s+".
_LATENCY_BUCKET_BOUNDS: tuple[float, ...] = (1.0, 2.0, 5.0, 10.0)

LATENCY_BUCKET_LABELS: tuple[str, ...] = ("<1s", "1-2s", "2-5s", "5-10s", "10s+")


@dataclass(frozen=True)
class ResponseTimeStats:
    """Aggregate response-time statistics for a window of assistant answers.

    All values are seconds; every field collapses to ``None`` / an empty
    distribution when there are no measurable responses in the window.
    """

    avg: float | None
    median: float | None
    p95: float | None
    fastest: float | None
    slowest: float | None
    distribution: dict[str, int]


def response_time_statistics(values: list[float]) -> ResponseTimeStats:
    """Compute median / p95 / distribution from raw ``response_time`` values.

    Empty or all-``None`` input yields ``None`` statistics so downstream
    consumers never divide by zero or present fabricated numbers.
    """
    clean = sorted(float(v) for v in values if v is not None)
    if not clean:
        return ResponseTimeStats(
            avg=None,
            median=None,
            p95=None,
            fastest=None,
            slowest=None,
            distribution={label: 0 for label in LATENCY_BUCKET_LABELS},
        )
    return ResponseTimeStats(
        avg=round(sum(clean) / len(clean), 3),
        median=round(_percentile(clean, 50), 3),
        p95=round(_percentile(clean, 95), 3),
        fastest=round(clean[0], 3),
        slowest=round(clean[-1], 3),
        distribution=_latency_distribution(clean),
    )


def _percentile(sorted_values: list[float], percentile: float) -> float:
    """Nearest-rank percentile over already-sorted values."""
    rank = math.ceil(percentile / 100 * len(sorted_values))
    return sorted_values[rank - 1]


def _latency_distribution(sorted_values: list[float]) -> dict[str, int]:
    distribution = {label: 0 for label in LATENCY_BUCKET_LABELS}
    for value in sorted_values:
        bucket = _bucket_label(value)
        distribution[bucket] += 1
    return distribution


def _bucket_label(value: float) -> str:
    if value < _LATENCY_BUCKET_BOUNDS[0]:
        return LATENCY_BUCKET_LABELS[0]
    for index, bound in enumerate(_LATENCY_BUCKET_BOUNDS):
        if value < bound:
            return LATENCY_BUCKET_LABELS[index]
    return LATENCY_BUCKET_LABELS[-1]


__all__ = [
    "LATENCY_BUCKET_LABELS",
    "ResponseTimeStats",
    "response_time_statistics",
]
