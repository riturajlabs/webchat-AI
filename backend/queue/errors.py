"""Queue integration errors (Phase 17A).

All errors raised by the queue interface layer derive from ``QueueError`` so a
caller can catch one type regardless of backend.
"""


class QueueError(Exception):
    """Base class for worker-queue integration errors."""


class UnknownFunctionError(QueueError):
    """No production job is registered under this function name.

    Raised instead of ever executing an arbitrary payload-driven name: the
    registry is a closed, explicit set of known jobs - no dynamic imports, no
    ``eval``/``exec``. An unknown name fails safely at enqueue time.
    """


class InvalidPayloadError(QueueError):
    """The payload does not satisfy the registered function's shape."""


class BackendNotSupportedError(QueueError):
    """The requested operation is not supported by this backend adapter.

    ARQ owns job *consumption* (its worker entrypoint), so ``ArqQueueAdapter``
    is producer-side: ``claim``/``complete``/``fail``/``heartbeat`` raise this
    error instead of silently pretending ARQ exposes a claim API.
    """


class DuplicateJobError(QueueError):
    """The backend deliberately collapsed this submission into an existing job.

    ARQ signals this by returning ``None`` from ``enqueue_job`` when the
    ``_job_id`` already exists within the result-retention window.
    """


class MongoQueueNotEnabledError(QueueError):
    """The Mongo queue was requested but not explicitly enabled."""


class JobTimeoutError(QueueError):
    """A job exceeded its function-level timeout.

    Raised by the Mongo worker loop where ARQ raises the builtin
    ``TimeoutError``. It is a *terminal* failure under ARQ 0.28 semantics (a
    timed-out job is not retried), and is surfaced as its own type so the
    mapping is explicit and testable rather than incidental.
    """


__all__ = [
    "BackendNotSupportedError",
    "DuplicateJobError",
    "InvalidPayloadError",
    "JobTimeoutError",
    "MongoQueueNotEnabledError",
    "QueueError",
    "UnknownFunctionError",
]
