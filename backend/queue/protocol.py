"""``WorkerQueue``: the production-facing queue contract (Phase 17A).

The interface names queue *semantics* (enqueue, claim, heartbeat, complete,
fail, retire_expired), never storage. No Redis key, ZSET or ARQ job-key concept
crosses this boundary, and neither does any "the worker is ARQ's worker"
assumption.

Two adapters implement it:

* :class:`backend.queue.arq_adapter.ArqQueueAdapter` - the production default.
  ARQ owns consumption, so the adapter is producer-side and the consumer
  operations raise :class:`BackendNotSupportedError` rather than pretending
  ARQ exposes a claim API.
* :class:`backend.queue.mongo_adapter.MongoQueueAdapter` - the opt-in Mongo
  backend, which implements the full consumer side.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class QueueJob:
    """One claimed job handed to a consumer (backend-agnostic).

    Field naming is deliberately ARQ-flavoured where the concepts genuinely
    coincide (``job_try``/``enqueue_time``) so the same job context can be
    rebuilt for an ARQ worker or for direct dispatch. No Redis concept leaks
    through this type.
    """

    id: str
    function: str
    payload: dict[str, Any]
    tenant_id: str
    job_try: int
    max_tries: int
    execution_version: int
    enqueue_time: datetime
    score: datetime


def job_context(
    job: QueueJob,
    *,
    timeout: int,
    queue_name: str,
    queue: WorkerQueue | None = None,
) -> dict[str, Any]:
    """Build the job context a production job coroutine receives.

    ARQ injects exactly ``job_id``/``job_try``/``enqueue_time``/``score``
    (verified against ``arq.worker.Worker.run_job``, arq 0.28). This builder
    reproduces those four keys under their production names and adds the
    queue-execution metadata the Mongo backend owns:

    * ``max_tries`` - NOT provided by ARQ. ``crawl_website`` reads
      ``ctx.get("max_tries", 3)`` and therefore always sees its literal
      fallback today; supplying it here makes the Mongo path explicit. The
      default is held at 3 so the observed value does not change.
    * ``timeout`` - the function-level timeout actually applied.
    * ``function``/``queue_name`` - diagnostics.

    The tenant is NOT injected into the context here: production jobs derive
    their own tenant from the authoritative domain row
    (``crawl_website`` sets ``tenant_id_var`` from the crawl job document).
    Overwriting that with the queue row's copy would be a *less* trusted
    value, so the queue row's ``tenant_id`` is carried for observability and
    enforcement only (``MongoQueueAdapter`` requires it to be non-empty) and is
    never used as the job's authority.

    ``queue`` is Phase 17B's child-enqueue handoff: when a loop executes a job
    it passes the very :class:`WorkerQueue` it is running on, so a job that
    enqueues children routes them back onto the SAME backend instead of
    hard-wiring Redis (see :mod:`backend.queue.child`). It is omitted entirely
    when ``None``, which is the case for every real ARQ execution - ARQ owns
    consumption there and the job's children are already ARQ jobs.
    """
    context: dict[str, Any] = {
        "job_id": job.id,
        "job_try": job.job_try,
        "enqueue_time": job.enqueue_time,
        "score": job.score,
        "max_tries": job.max_tries,
        "timeout": timeout,
        "function": job.function,
        "queue_name": queue_name,
    }
    if queue is not None:
        from backend.queue.child import CTX_QUEUE_KEY, CTX_QUEUE_TENANT_KEY

        context[CTX_QUEUE_KEY] = queue
        # Attributability for child rows only; see CTX_QUEUE_TENANT_KEY.
        context[CTX_QUEUE_TENANT_KEY] = job.tenant_id
    return context


@runtime_checkable
class WorkerQueue(Protocol):
    """The queue contract both adapters implement.

    ``enqueue`` validates the function name and payload, so an unknown job is
    rejected at the producer boundary on every backend, and a job's tenant
    travels with it from enqueue through execution.
    """

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
    ) -> str: ...

    async def claim(self, worker_id: str) -> QueueJob | None: ...

    async def heartbeat(
        self, job_id: str, worker_id: str, *, execution_version: int | None = None
    ) -> bool: ...

    async def complete(
        self,
        job_id: str,
        worker_id: str,
        *,
        execution_version: int,
        result: Any = None,
    ) -> bool: ...

    async def fail(
        self,
        job_id: str,
        worker_id: str,
        *,
        execution_version: int,
        error: str,
        retry: bool = True,
    ) -> str: ...

    async def retire_expired(self) -> int: ...

    async def ping(self) -> bool: ...


__all__ = ["QueueJob", "WorkerQueue", "job_context"]
