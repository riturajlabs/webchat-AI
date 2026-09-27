"""Isolated MongoDB-backed worker queue prototype (Phase 15).

This package is a READ-ONLY-of-production experiment. It is never imported
by production application code: nothing under ``backend/workers``,
``backend/api`` or ``backend/services`` references it, and it is not part of
any production startup path. It exists to measure whether a MongoDB queue can
match ARQ/Redis durability semantics for WebChat AI's worker jobs.
"""

from backend.prototypes.mongo_queue.config import (
    DEFAULT_COLLECTION,
    DEFAULT_DB_NAME,
    QueueConfig,
)
from backend.prototypes.mongo_queue.models import (
    STATUS_COMPLETED,
    STATUS_DEAD,
    STATUS_PENDING,
    STATUS_RETRY_PENDING,
    STATUS_RUNNING,
    Job,
    JobStatus,
)
from backend.prototypes.mongo_queue.queue import MongoQueue

__all__ = [
    "DEFAULT_COLLECTION",
    "DEFAULT_DB_NAME",
    "Job",
    "JobStatus",
    "MongoQueue",
    "QueueConfig",
    "STATUS_COMPLETED",
    "STATUS_DEAD",
    "STATUS_PENDING",
    "STATUS_RETRY_PENDING",
    "STATUS_RUNNING",
]