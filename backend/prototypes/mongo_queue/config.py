"""Prototype configuration (Phase 15).

All values are prototype-scoped. They mirror the *shape* of the production
worker settings (max_tries=3, job_timeout short/medium) but are intentionally
independent: the prototype never reads ``backend.core.config`` so production
environment files cannot influence it and it cannot influence them.
"""

from __future__ import annotations

from dataclasses import dataclass

# Explicitly isolated namespace. Never reuse a production collection/database.
DEFAULT_DB_NAME = "webchat_ai_queue_prototype"
DEFAULT_COLLECTION = "worker_jobs_prototype"

# Default local prototype Mongo endpoint: dedicated ephemeral mongod, wholly
# separate from the dev docker stack and from production Atlas.
DEFAULT_MONGO_URI = "mongodb://127.0.0.1:27019"


def _default_schedule() -> tuple[float, ...]:
    # Adaptive polling schedule in seconds: first idle interval, then growth.
    return (1.0, 2.0, 5.0, 10.0, 30.0)


@dataclass(frozen=True)
class QueueConfig:
    """Immutable prototype configuration.

    ``backoff_seconds[i]`` is the delay before retry when ``attempts == i + 1``
    (attempt 1 -> 5 s, attempt 2 -> 30 s, attempt 3 -> 180 s). ``max_tries``
    bounds total claim attempts (matching production max_tries=3). ``poll
    _schedule`` drives the adaptive idle backoff. ``max_result_bytes`` guards
    the result payload so queue documents stay small on M0-class storage.
    """

    db_name: str = DEFAULT_DB_NAME
    collection_name: str = DEFAULT_COLLECTION
    lease_seconds: float = 120.0
    heartbeat_interval_seconds: float = 30.0
    max_tries: int = 3
    backoff_seconds: tuple[float, ...] = (5.0, 30.0, 180.0)
    poll_schedule: tuple[float, ...] = _default_schedule()
    max_result_bytes: int = 16_384

    @property
    def collection_label(self) -> str:
        return f"{self.db_name}.{self.collection_name}"
