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


class UnresolvedTenantError(QueueError):
    """The authoritative tenant for a Mongo queue job could not be resolved.

    The Mongo adapter rejects empty-tenant jobs at the producer boundary, and
    the producers normally resolve the tenant from the authoritative domain row
    (crawl job / document / website). When that row is missing or carries no
    tenant in Mongo mode, the submission would be unowned work nobody can
    observe or cancel, so it fails loud instead of falling back to ARQ or to a
    fabricated scope.
    """


__all__ = [
    "BackendNotSupportedError",
    "DuplicateJobError",
    "InvalidPayloadError",
    "JobTimeoutError",
    "MongoQueueNotEnabledError",
    "QueueError",
    "UnknownFunctionError",
    "UnresolvedTenantError",
]
