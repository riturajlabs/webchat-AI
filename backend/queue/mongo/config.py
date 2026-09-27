"""Immutable configuration for the production Mongo queue.

Values are supplied by :class:`backend.core.config.Settings` (see
``backend/queue/factory.py``); this dataclass exists so the storage engine has
no import-time dependency on application settings. The defaults reproduce the
validated Phase 15/16 prototype shape and ARQ's production worker shape
(``max_tries=3``).
"""

from __future__ import annotations

from dataclasses import dataclass, field


def _default_poll_schedule() -> tuple[float, ...]:
    # Adaptive idle polling: 1 s hot, ratcheting to a 30 s idle cap.
    return (1.0, 2.0, 5.0, 10.0, 30.0)


@dataclass(frozen=True)
class QueueConfig:
    """Storage-level queue configuration.

    ``backoff_seconds[i]`` is the delay before a retry when ``attempts == i + 1``.
    ``lease_seconds`` is how long a claim owns a job before it becomes
    reclaimable; ``heartbeat_interval_seconds`` is how often the owner renews.
    ``max_result_bytes`` clamps a stored result so queue documents stay small.
    """

    db_name: str = "webchat_ai_queue"
    collection_name: str = "worker_jobs"
    lease_seconds: float = 120.0
    heartbeat_interval_seconds: float = 30.0
    max_tries: int = 3
    # NOTE: this is the *knowledge domain* schedule (knowledge_retry_base_delay
    # 5 s x backoff factor 6 -> 5/30/180 s), NOT an ARQ behaviour. ARQ applies
    # no backoff to its own retry paths; see docs/reports/
    # MONGO_QUEUE_PHASE17A_INTEGRATION_REPORT.md section 8.
    backoff_seconds: tuple[float, ...] = (5.0, 30.0, 180.0)
    poll_schedule: tuple[float, ...] = field(default_factory=_default_poll_schedule)
    max_result_bytes: int = 16_384

    @property
    def collection_label(self) -> str:
        return f"{self.db_name}.{self.collection_name}"
