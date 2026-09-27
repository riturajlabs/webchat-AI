"""Worker queue integration layer (Phase 17A).

The production worker queue is ARQ over Redis. This package introduces a single
``WorkerQueue`` interface behind which ARQ and a MongoDB-backed queue both
implement, without changing what the production worker actually uses.

Phase 17A scope is *integration, not cutover*: ARQ remains the production
default (``QUEUE_BACKEND=arq``), the Mongo queue is an explicit opt-in
(``QUEUE_BACKEND=mongo`` **and** ``MONGO_QUEUE_ENABLED=true``), and nothing in
``backend/workers`` / ``backend/api`` is rewired. No production job has been
routed to Mongo, no queue was drained, and no Redis queue data was migrated.
See ``docs/reports/MONGO_QUEUE_PHASE17A_INTEGRATION_REPORT.md``.
"""

from typing import Any

from backend.queue.arq_adapter import ArqQueueAdapter
from backend.queue.errors import (
    BackendNotSupportedError,
    DuplicateJobError,
    InvalidPayloadError,
    JobTimeoutError,
    MongoQueueNotEnabledError,
    QueueError,
    UnknownFunctionError,
)
from backend.queue.factory import get_queue, queue_database_name
from backend.queue.mail_idempotency import build_idempotency_key, key_for_payload, redact_key
from backend.queue.protocol import QueueJob, WorkerQueue, job_context
from backend.queue.registry import (
    JOB_ARGUMENTS,
    job_timeout_seconds,
    known_names,
    resolve,
    validate_function,
    validate_payload,
)
from backend.queue.worker import MongoWorkerLoop, WorkOutcome

__all__ = [
    "JOB_ARGUMENTS",
    "ArqQueueAdapter",
    "BackendNotSupportedError",
    "DuplicateJobError",
    "InvalidPayloadError",
    "JobTimeoutError",
    "MongoQueueAdapter",
    "MongoQueueNotEnabledError",
    "MongoWorkerLoop",
    "QueueError",
    "QueueJob",
    "UnknownFunctionError",
    "WorkOutcome",
    "WorkerQueue",
    "build_idempotency_key",
    "get_queue",
    "job_context",
    "job_timeout_seconds",
    "key_for_payload",
    "known_names",
    "queue_database_name",
    "redact_key",
    "resolve",
    "validate_function",
    "validate_payload",
]


def __getattr__(name: str) -> Any:  # pragma: no cover - lazy re-export
    """Import the Mongo adapter lazily.

    ``backend.queue.mongo_adapter`` pulls in motor/pymongo. Keeping it behind
    ``__getattr__`` means an API process that only needs the registry does not
    pay for the Mongo driver import, and the ARQ default path never imports the
    Mongo store at all.
    """
    if name == "MongoQueueAdapter":
        from backend.queue.mongo_adapter import MongoQueueAdapter

        return MongoQueueAdapter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
