"""Adaptive polling policy for the prototype (Phase 15).

The entire motivation of this investigation is that ARQ's default idle
behaviour issues a Redis ``ZRANGEBYSCORE`` every 0.5 s regardless of load
(~172,800 commands/day/worker). This poller instead:

    work found  -> poll every 1 s   (hot, low latency)
    idle        -> 1 s -> 2 s -> 5 s -> 10 s -> 30 s  (capped)
    work again  -> reset to 1 s

CONTRACT: the caller sleeps (or skips sleeping under a fake clock) for
``next_interval`` BEFORE issuing the next claim. Idle MongoDB cost therefore
decays to ~2,880 claim ops/day/worker at the 30 s cap instead of ~172,800.
"""

from __future__ import annotations

from dataclasses import dataclass

# Fixed 0.5 s interval used by ARQ 0.28 by default (measured against
# ``arq.worker`` source: ``poll_delay == 0.5``). Kept here as the comparison
# baseline for the polling-cost experiment (§25).
ARQ_DEFAULT_POLL_DELAY_SECONDS = 0.5


@dataclass
class PollStats:
    """Accumulated poller behaviour (for the measurement experiment)."""

    iterations: int = 0
    work_found: int = 0
    idle_waits: int = 0
    total_idle_sleep_seconds: float = 0.0

    def as_dict(self) -> dict[str, float | int]:
        return {
            "iterations": self.iterations,
            "work_found": self.work_found,
            "idle_waits": self.idle_waits,
            "total_idle_sleep_seconds": self.total_idle_sleep_seconds,
        }


class AdaptivePoller:
    """Pure interval policy; deterministic and unit-testable.

    ``nick()`` returns the sleep interval for the next poll given whether
    work was found on the previous poll. Exporting the pure policy lets the
    measurements simulate hours of idle time without sleeping.
    """

    def __init__(self, schedule: tuple[float, ...] = (1.0, 2.0, 5.0, 10.0, 30.0)) -> None:
        if not schedule or any(d <= 0 for d in schedule):
            raise ValueError("poll schedule must be a non-empty sequence of positive seconds")
        self._schedule = tuple(schedule)
        self._step = 0
        self._stats = PollStats()

    @property
    def stats(self) -> PollStats:
        return self._stats

    @property
    def current_interval(self) -> float:
        return self._schedule[self._step]

    def nick(self, found_work: bool) -> float:
        """Advance the policy one poll and return the next sleep interval."""
        self._stats.iterations += 1
        if found_work:
            self._stats.work_found += 1
            self._step = 0
        else:
            self._stats.idle_waits += 1
            self._stats.total_idle_sleep_seconds += self._schedule[self._step]
            bottom = len(self._schedule) - 1
            if self._step < bottom:
                self._step += 1
        return self._schedule[self._step]

    def reset(self) -> None:
        self._step = 0
        self._stats = PollStats()


def estimate_idle_ops_per_day(schedule: tuple[float, ...], workers: int) -> float:
    """Steady-state idle claim ops/day for ``workers`` independent pollers.

    Each idle poller eventually dwells on the longest schedule slot. The
    claim attempt is always issued before the sleep, so in steady state each
    worker performs ``86400 / max(schedule)`` claim ops per day.
    """
    if not schedule:
        raise ValueError("empty schedule")
    cap = max(schedule)
    per_worker = 86400.0 / cap
    return per_worker * workers