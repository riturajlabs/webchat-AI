"""ARQ (Redis) queue adapter - the production default (Phase 17A).

A producer-side adapter over the existing ARQ broker. It reproduces exactly
what the production enqueue helpers do today - one ``ArqRedis.enqueue_job``
call with the same positional arguments, ``_job_id`` and ``_defer_by`` - so a
job enqueued through this adapter is indistinguishable from one enqueued by
``enqueue_email`` / ``enqueue_crawl_website`` / ``enqueue_process_document``.
This adapter does not rewrite, wrap or reorder ARQ behaviour.

Two measured ARQ facts shape this adapter (arq 0.28, verified by running a real
worker; see the Phase 17A report section 5):

1. ``ArqRedis.enqueue_job`` returns an ``arq.jobs.Job`` (or ``None``), not a
   string. It returns ``None`` when the requested ``_job_id`` already exists
   inside the result-retention window - that is ARQ's *own* deduplication, and
   ``enqueue_crawl_website`` depends on it (FIND-02: a JOB-scoped
   ``crawl:<crawl_job_id>`` key means a legitimate new crawl still enqueues).
   The adapter surfaces that outcome as :class:`DuplicateJobError` rather than
   inventing a job id.
2. ARQ owns job *consumption* through its worker entrypoint
   (``python -m backend.workers``), so the consumer-side operations of
   ``WorkerQueue`` raise :class:`BackendNotSupportedError` instead of pretending
   ARQ exposes a claim API.
"""

from __future__ import annotations

from typing import Any

from arq.connections import ArqRedis
from redis.asyncio import ConnectionPool

from backend.core.config import get_settings
from backend.queue.errors import BackendNotSupportedError, DuplicateJobError
from backend.queue.protocol import QueueJob
from backend.queue.registry import args_from_payload, validate_function

#: ARQ's default queue name; the production worker consumes this exact ZSET.
DEFAULT_QUEUE_NAME = "arq:queue"

_CONSUMER_ONLY = (
    "ArqQueueAdapter is producer-side: ARQ owns job consumption via "
    "python -m backend.workers. Use MongoQueueAdapter if a claim API is required."
)


class ArqQueueAdapter:
    """Producer-side ``WorkerQueue`` adapter backed by the ARQ Redis broker."""

    def __init__(self, redis_url: str | None = None) -> None:
        self._redis_url = redis_url if redis_url is not None else get_settings().redis_url
        self._pool: ConnectionPool | None = None

    @property
    def queue_name(self) -> str:
        return DEFAULT_QUEUE_NAME

    def _arq_redis(self) -> ArqRedis:
        if self._pool is None:
            self._pool = ConnectionPool.from_url(self._redis_url, decode_responses=True)
        return ArqRedis(connection_pool=self._pool)

    async def enqueue(
        self,
        function: str,
        *,
        payload: dict[str, Any] | None = None,
        tenant_id: str = "",
        dedup_key: str | None = None,
        defer_by: float | None = None,
        job_id: str | None = None,
        max_tries: int | None = None,
    ) -> str:
        """Enqueue one job, faithfully reproducing today's ARQ call shape.

        ``job_id``/``dedup_key`` map to ARQ's ``_job_id`` (its idempotency
        handle): ``crawl_website`` uses the JOB-scoped ``crawl:<crawl_job_id>``
        exactly as today, and a plain dedup key is namespaced as
        ``<function>:<key>``. ``tenant_id`` is accepted for interface parity and
        deliberately not sent: ARQ's job arguments are fixed positional values,
        so adding a tenant argument would change every job signature. Tenant
        isolation is preserved downstream because production jobs read their
        authoritative tenant from the domain row, not from the queue.
        ``max_tries`` is ignored - ARQ applies it at the worker
        (``max_tries=3`` in ``WorkerSettings``), never per enqueue.

        Raises :class:`DuplicateJobError` when ARQ itself suppressed the enqueue
        because ``_job_id`` already exists within ``keep_result``.
        """
        _ = (tenant_id, max_tries)
        validate_function(function)
        args = args_from_payload(function, payload or {})
        _job_id: str | None
        if job_id is not None:
            _job_id = job_id
        elif dedup_key is not None:
            _job_id = f"{function}:{dedup_key}"
        else:
            _job_id = None
        kwargs: dict[str, Any] = {}
        if _job_id is not None:
            kwargs["_job_id"] = _job_id
        if defer_by is not None and defer_by > 0:
            kwargs["_defer_by"] = defer_by
        job = await self._arq_redis().enqueue_job(function, *args, **kwargs)
        if job is None:
            # ARQ declined the enqueue: the _job_id is already known inside the
            # keep_result window. Report it rather than fabricating an id.
            raise DuplicateJobError(
                f"ARQ suppressed the enqueue of {function!r}: job id {_job_id!r} already "
                "exists within the result-retention window."
            )
        return str(job.job_id)

    async def claim(self, worker_id: str) -> QueueJob | None:
        _ = worker_id
        raise BackendNotSupportedError(_CONSUMER_ONLY)

    async def heartbeat(
        self, job_id: str, worker_id: str, *, execution_version: int | None = None
    ) -> bool:
        _ = (job_id, worker_id, execution_version)
        raise BackendNotSupportedError(_CONSUMER_ONLY)

    async def complete(
        self,
        job_id: str,
        worker_id: str,
        *,
        execution_version: int,
        result: Any = None,
    ) -> bool:
        _ = (job_id, worker_id, execution_version, result)
        raise BackendNotSupportedError(_CONSUMER_ONLY)

    async def fail(
        self,
        job_id: str,
        worker_id: str,
        *,
        execution_version: int,
        error: str,
        retry: bool = True,
    ) -> str:
        _ = (job_id, worker_id, execution_version, error, retry)
        raise BackendNotSupportedError(_CONSUMER_ONLY)

    async def retire_expired(self) -> int:
        raise BackendNotSupportedError(_CONSUMER_ONLY)

    async def ping(self) -> bool:
        try:
            return bool(await self._arq_redis().ping())
        except Exception:  # noqa: BLE001 - probe must never raise
            return False

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.aclose()
            self._pool = None


__all__ = ["DEFAULT_QUEUE_NAME", "ArqQueueAdapter"]
