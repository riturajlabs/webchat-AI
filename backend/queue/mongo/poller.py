"""Adaptive polling policy for the Mongo queue worker.

ARQ's default idle behaviour issues a Redis poll every 0.5 s regardless of load
(~172,800 commands/day/worker). This poller instead:

    work found  -> poll every 1 s   (hot, low latency)
    idle        -> 1 s -> 2 s -> 5 s -> 10 s -> 30 s  (capped)
    work again  -> reset to 1 s

CONTRACT: the caller sleeps for the returned interval BEFORE issuing the next
claim, so idle database cost decays to ~2,880 claim ops/day/worker at the 30 s
cap. The schedule is configurable (``MONGO_QUEUE_POLL_SCHEDULE``) and the
worker never issues a database command while sleeping.
"""

from __future__ import annotations

from dataclasses import dataclass

#: ARQ 0.28's fixed idle poll interval, kept only as the comparison baseline
#: for the polling-cost measurement in the Phase 17A report.
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

    ``nick()`` returns the sleep interval for the next poll given whether work
    was found on the previous poll. Exporting the pure policy lets the
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
        """Advance the policy one poll and return the next sleep interval.

        The returned value is the interval to wait *after* the poll that just
        happened, i.e. the wait before the next claim. On the idle path the
        current slot is returned first and then advanced, so the sequence really
        is 1 -> 2 -> 5 -> 10 -> 30 (capped), as documented above; finding work
        resets straight to the hot interval.
        """
        self._stats.iterations += 1
        if found_work:
            self._stats.work_found += 1
            self._step = 0
            return self._schedule[0]
        self._stats.idle_waits += 1
        interval = self._schedule[self._step]
        self._stats.total_idle_sleep_seconds += interval
        bottom = len(self._schedule) - 1
        if self._step < bottom:
            self._step += 1
        return interval

    def reset(self) -> None:
        self._step = 0
        self._stats = PollStats()


def estimate_idle_ops_per_day(schedule: tuple[float, ...], workers: int) -> float:
    """Steady-state idle claim ops/day for ``workers`` independent pollers.

    Each idle poller dwells on the longest schedule slot, and the claim is
    always issued before the sleep, so in steady state each worker performs
    ``86400 / max(schedule)`` claim ops per day.
    """
    if not schedule:
        raise ValueError("empty schedule")
    cap = max(schedule)
    per_worker = 86400.0 / cap
    return per_worker * workers
