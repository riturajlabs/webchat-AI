"""Shadow-comparison telemetry (Phase 17B).

Counters for the envelope comparator so an operator can see, over time:

* how many submissions were compared,
* how many matched,
* which *category* mismatched,

without ever exposing user data. Every counter here is a bounded-cardinality
label (a job function name, a field name, a status) - never a payload value, a
recipient address, an API key, a Mongo URI or a raw idempotency key.

The collector is intentionally tiny and dependency-free: a metrics backend is
deployment-specific, so this exposes a stable ``snapshot()`` shape that a
Prometheus/StatsD/OTel bridge can read, and it is what the local staging harness
prints. It is also the single place that decides whether a shadow *failure* is
observational or blocking, because "a mismatch must never break production" is
an invariant worth testing in one spot.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from backend.queue.envelope import EnvelopeParity

logger = logging.getLogger("webchat_ai.mongo_queue")

#: The counters the migration dashboard needs. Fixed set: nothing is created
#: dynamically, so the metric namespace cannot be poisoned by input.
COUNTER_FIELDS: Final[tuple[str, ...]] = (
    "shadow_envelopes_compared",
    "shadow_envelope_match",
    "shadow_envelope_mismatch",
    "shadow_envelope_mismatch_unexplained",
    "shadow_comparison_errors",
    "shadow_side_effect_blocked",
)


@dataclass
class ShadowTelemetry:
    """In-process counters for shadow comparisons.

    ``strict`` is the only switch with behavioural effect, and it defaults to
    the safe setting: in production a comparison problem is *reported and
    swallowed*, never raised, because the ARQ enqueue that the caller actually
    asked for must proceed regardless of what the Mongo shadow copy thought.
    A test-only strict run re-raises so a parity gate can fail loudly.
    """

    strict: bool = False
    counters: dict[str, int] = field(default_factory=lambda: dict.fromkeys(COUNTER_FIELDS, 0))
    by_function: dict[str, dict[str, int]] = field(default_factory=dict)
    mismatch_fields: dict[str, int] = field(default_factory=dict)
    unexplained: list[dict[str, Any]] = field(default_factory=list)

    def _bucket(self, function: str) -> dict[str, int]:
        return self.by_function.setdefault(
            function,
            dict.fromkeys(
                (
                    "compared",
                    "match",
                    "mismatch",
                    "mismatch_unexplained",
                ),
                0,
            ),
        )

    def record(self, parity: EnvelopeParity) -> EnvelopeParity:
        """Count one comparison and return it unchanged.

        Never raises in non-strict mode: a shadow comparison is observational,
        so the caller's production enqueue continues either way.
        """
        self.counters["shadow_envelopes_compared"] += 1
        bucket = self._bucket(parity.function)
        bucket["compared"] += 1
        if parity.matches:
            self.counters["shadow_envelope_match"] += 1
            bucket["match"] += 1
        else:
            self.counters["shadow_envelope_mismatch"] += 1
            bucket["mismatch"] += 1
            if parity.unexplained:
                self.counters["shadow_envelope_mismatch_unexplained"] += 1
                bucket["mismatch_unexplained"] += 1
                self.unexplained.append(
                    {
                        "function": parity.function,
                        "fields": [difference.field for difference in parity.unexplained],
                    }
                )
            for difference in parity.differences:
                self.mismatch_fields[difference.field] = (
                    self.mismatch_fields.get(difference.field, 0) + 1
                )
        if self.strict and parity.unexplained:
            fields = ", ".join(difference.field for difference in parity.unexplained)
            raise ShadowParityError(
                f"shadow envelope parity failed for {parity.function!r}: {fields}"
            )
        return parity

    def record_error(self, function: str, exc: BaseException) -> None:
        """Count a comparison that could not be completed.

        A shadow *error* (a bug in the comparator, an unreachable store) is
        equally non-fatal in production, so this logs and counts rather than
        raising, unless the run is strict.
        """
        self.counters["shadow_comparison_errors"] += 1
        logger.warning(
            "shadow_envelope_compare_error function=%s error=%s",
            function,
            type(exc).__name__,
        )
        if self.strict:
            raise ShadowParityError(f"shadow comparison failed for {function!r}") from exc

    def record_blocked_side_effect(self, attempt: str) -> None:
        """Count a shadow-path attempt to execute a real job (must stay 0)."""
        self.counters["shadow_side_effect_blocked"] += 1
        logger.error("shadow_side_effect_blocked attempt=%s", attempt)

    def snapshot(self) -> dict[str, Any]:
        """Log-safe snapshot: bounded labels and counts only."""
        return {
            "counters": dict(self.counters),
            "by_function": {
                function: dict(values) for function, values in sorted(self.by_function.items())
            },
            "mismatch_fields": dict(sorted(self.mismatch_fields.items())),
            "unexplained": list(self.unexplained),
        }

    @property
    def has_unexplained(self) -> bool:
        return bool(self.unexplained)


class ShadowParityError(RuntimeError):
    """Raised only in strict (test/gate) mode when parity fails."""


async def shadow_compare(
    telemetry: ShadowTelemetry,
    build: Any,
    function: str,
    *,
    strict: bool | None = None,
) -> EnvelopeParity | None:
    """Run ``build()`` and record the parity result, never raising in production.

    ``build`` is a zero-argument coroutine factory returning an
    :class:`~backend.queue.envelope.EnvelopeParity`. Keeping the comparison
    behind a callable means the caller controls *how* the envelopes are produced
    and this helper can guarantee the non-blocking behaviour in one place.
    """
    try:
        parity = await build()
    except Exception as exc:  # noqa: BLE001 - shadow must not break production
        telemetry.record_error(function, exc)
        return None
    if strict is not None and strict != telemetry.strict:
        scoped = ShadowTelemetry(strict=strict)
        scoped.counters = telemetry.counters
        scoped.by_function = telemetry.by_function
        scoped.mismatch_fields = telemetry.mismatch_fields
        scoped.unexplained = telemetry.unexplained
        return scoped.record(parity)
    return telemetry.record(parity)


#: Module-level default collector, so production code can record without
#: threading a collector through every call site. Tests construct their own.
_DEFAULT: ShadowTelemetry = ShadowTelemetry()


def default_telemetry() -> ShadowTelemetry:
    return _DEFAULT


def reset_default_telemetry() -> None:
    """Reset the process-wide collector (tests only)."""
    global _DEFAULT
    _DEFAULT = ShadowTelemetry()


def render_summary(snapshot: Mapping[str, Any]) -> str:
    """Render a snapshot as the concise staging-harness summary block."""
    counters = snapshot.get("counters", {})
    lines = [
        f"envelopes compared: {counters.get('shadow_envelopes_compared', 0)}",
        f"matched:           {counters.get('shadow_envelope_match', 0)}",
        f"mismatched:        {counters.get('shadow_envelope_mismatch', 0)}",
        f"unexplained:       {counters.get('shadow_envelope_mismatch_unexplained', 0)}",
        f"compare errors:    {counters.get('shadow_comparison_errors', 0)}",
        f"side effects:      {counters.get('shadow_side_effect_blocked', 0)}",
    ]
    by_function = snapshot.get("by_function", {})
    if by_function:
        lines.append("per function:")
        for function, values in by_function.items():
            lines.append(
                f"  {function}: compared={values.get('compared', 0)} "
                f"match={values.get('match', 0)} mismatch={values.get('mismatch', 0)}"
            )
    return "\n".join(lines)


__all__ = [
    "COUNTER_FIELDS",
    "ShadowParityError",
    "ShadowTelemetry",
    "default_telemetry",
    "render_summary",
    "reset_default_telemetry",
    "shadow_compare",
]
