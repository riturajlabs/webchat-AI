"""MongoDB queue storage engine (production).

This sub-package is the promoted, production-safe form of the validated Phase
15/16 prototype at ``backend/prototypes/mongo_queue``. It is a self-contained
storage engine: it imports nothing from ``backend.prototypes`` and nothing from
application settings, so the prototype sandbox and the production queue share no
code path. (The prototype remains in place, untouched, as the measured evidence
record for Phases 15/16.)
"""

from backend.queue.mongo.config import QueueConfig
from backend.queue.mongo.ids import add_seconds, new_job_id, new_worker_id, utcnow
from backend.queue.mongo.models import (
    CLAIMABLE_PENDING,
    STATUS_COMPLETED,
    STATUS_DEAD,
    STATUS_PENDING,
    STATUS_RETRY_PENDING,
    STATUS_RUNNING,
    TERMINAL_STATUSES,
    Job,
    JobStatus,
    status_is_terminal,
)
from backend.queue.mongo.poller import AdaptivePoller, PollStats, estimate_idle_ops_per_day
from backend.queue.mongo.store import MongoQueue

__all__ = [
    "CLAIMABLE_PENDING",
    "STATUS_COMPLETED",
    "STATUS_DEAD",
    "STATUS_PENDING",
    "STATUS_RETRY_PENDING",
    "STATUS_RUNNING",
    "TERMINAL_STATUSES",
    "AdaptivePoller",
    "Job",
    "JobStatus",
    "MongoQueue",
    "PollStats",
    "QueueConfig",
    "add_seconds",
    "estimate_idle_ops_per_day",
    "new_job_id",
    "new_worker_id",
    "status_is_terminal",
    "utcnow",
]
