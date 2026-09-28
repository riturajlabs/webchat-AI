"""Process-scoped worker queue binding (Phase 18A).

One queue instance per process: API producers enqueue through it, and a cached
adapter avoids re-deriving the backend and rebuilding the ARQ connection pool /
``MongoQueue`` on every call. :func:`backend.queue.factory.get_queue` stays
uncached (tests rely on fresh adapters); this module owns the process singleton
instead.

Producers go through :func:`enqueue_worker_job` so the queue-backend selection
lives exactly here and every producer behaves identically:

* ARQ (production default) - enqueue through :class:`ArqQueueAdapter`. A
  duplicate ``_job_id`` surfaces as :class:`DuplicateJobError` (ARQ's own
  suppression, the same ``enqueue_job -> None`` the producers saw before
  Phase 18A); the producer treats it as a no-op and returns ``None``.
* Mongo (opt-in) - enqueue through :class:`MongoQueueAdapter`. The tenant is
  resolved from the authoritative domain row by the producer via
  :func:`producer_tenant` (never fabricated), and the adapter rejects an empty
  tenant at the producer boundary.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from backend.core.config import get_settings
from backend.queue.errors import DuplicateJobError, UnresolvedTenantError
from backend.queue.factory import get_queue
from backend.queue.protocol import WorkerQueue

logger = logging.getLogger("webchat_ai")

_worker_queue: WorkerQueue | None = None


def mongo_backend_selected() -> bool:
    """Whether the configured queue backend is Mongo (normalized).

    Matches ``Settings``' own case-insensitive validation so a ``QUEUE_BACKEND``
    of ``"MONGO"`` cannot silently build an ARQ adapter.
    """
    return get_settings().queue_backend.strip().lower() == "mongo"


def get_worker_queue() -> WorkerQueue:
    """Return the process worker queue, building it on first use."""
    global _worker_queue
    if _worker_queue is None:
        _worker_queue = get_queue()
    return _worker_queue


def reset_worker_queue() -> None:
    """Drop the cached queue without closing it (tests / in-process restarts)."""
    global _worker_queue
    _worker_queue = None


async def close_worker_queue() -> None:
    """Best-effort close of the cached queue, if any.

    Only the ARQ adapter owns a Redis connection pool to release; the Mongo
    adapter reuses the shared application ``MongoDB`` client and has no pool of
    its own. A race-free ``None`` swap keeps a concurrent producer from enqueueing
    onto a closed adapter.
    """
    global _worker_queue
    queue = _worker_queue
    _worker_queue = None
    closer = getattr(queue, "close", None)
    if closer is None:
        return
    try:
        await closer()
    except Exception:  # noqa: BLE001 - shutdown must be best-effort
        logger.exception("Failed to close the worker queue.")


async def producer_tenant(resolve: Callable[[], Awaitable[str]]) -> str:
    """Resolve the tenant for a producer submission.

    ARQ mode returns ``""`` and never touches a domain row: ARQ jobs derive
    their authoritative tenant from the domain row at execution time, so a
    production lookup at enqueue would add a round-trip for attributability that
    ARQ does not need. Mongo mode resolves the tenant from the caller-supplied
    resolver (which reads the authoritative domain row); a missing or empty
    tenant raises :class:`UnresolvedTenantError` so no unattributed job is ever
    submitted.
    """
    if not mongo_backend_selected():
        return ""
    tenant = (await resolve()).strip()
    if not tenant:
        raise UnresolvedTenantError(
            "The authoritative tenant for this job could not be resolved in "
            "Mongo mode; refusing to enqueue an unattributed job (the Mongo "
            "adapter requires a non-empty tenant_id and the domain row is the "
            "only trustworthy source)."
        )
    return tenant


async def enqueue_worker_job(
    function: str,
    *,
    payload: dict[str, Any] | None = None,
    tenant_id: str = "",
    dedup_key: str | None = None,
    defer_by: float | None = None,
    job_id: str | None = None,
    max_tries: int | None = None,
) -> str | None:
    """Enqueue one job through the process worker queue.

    Returns the job id on success and ``None`` when ARQ suppressed a duplicate
    (``DuplicateJobError``) - the same silent no-op the producers returned
    before Phase 18A when ``enqueue_job`` handed back ``None``.
    """
    try:
        return await get_worker_queue().enqueue(
            function,
            payload=payload,
            tenant_id=tenant_id,
            dedup_key=dedup_key,
            defer_by=defer_by,
            job_id=job_id,
            max_tries=max_tries,
        )
    except DuplicateJobError:
        logger.debug(
            "queue_duplicate_suppressed function=%s key=%s",
            function,
            job_id if job_id is not None else dedup_key,
        )
        return None


__all__ = [
    "close_worker_queue",
    "enqueue_worker_job",
    "get_worker_queue",
    "mongo_backend_selected",
    "producer_tenant",
    "reset_worker_queue",
]
