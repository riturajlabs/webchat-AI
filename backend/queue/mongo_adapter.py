"""MongoDB queue adapter (Phase 17A, opt-in).

A ``WorkerQueue`` adapter over the production Mongo store
(:mod:`backend.queue.mongo.store`), adding the consumer-side operations ARQ
keeps internal: atomic claim with a lease and an ``execution_version`` fencing
token, ownership-checked completion/failure, lease heartbeats, retry /
dead-lettering under the measured ARQ retry policy, and crash recovery via
``retire_expired``.

Connection policy: the adapter receives an ``AsyncIOMotorDatabase`` from the
caller. ``get_queue`` builds it from the application's existing ``MongoDB``
client (never a second unmanaged client) but targets an explicit queue
database, so queue rows never land beside tenant data in the application
database.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import OperationFailure

from backend.queue.errors import QueueError
from backend.queue.mongo.config import QueueConfig
from backend.queue.mongo.ids import add_seconds, utcnow
from backend.queue.mongo.models import TERMINAL_STATUSES, Job
from backend.queue.mongo.store import MongoQueue
from backend.queue.protocol import QueueJob
from backend.queue.registry import args_from_payload, validate_function, validate_payload

RETENTION_INDEX_NAME = "finished_at_ttl"

#: The safety property that makes terminal retention safe.
#:
#: A TTL index only ever considers documents that its partial index contains, so
#: restricting the index to terminal states makes retention *structurally*
#: incapable of deleting an active row. That matters because a non-terminal row
#: must never be deleted even in the ambiguous cases: a pending job scheduled far
#: in the future, a job whose lease expired but whose owner may still be alive,
#: a retryable row waiting on backoff, and any row whose state is uncertain
#: because a worker died mid-write.
#:
#: The invariant that ``finished_at`` is written only on a terminal transition
#: already holds (``complete_job``, the dead branch of ``fail_job`` and
#: ``retire_expired`` are the only writers). Expressing the guard as a partial
#: filter rather than relying on that invariant means a future bug that
#: populates ``finished_at`` early cannot start deleting live work.
RETENTION_PARTIAL_FILTER: dict[str, Any] = {"status": {"$in": sorted(TERMINAL_STATUSES)}}

#: Result-storage policy for the queue collection. Phase 16 left this UNDECIDED;
#: see the Phase 17A report section 20. Nothing in the repository reads an ARQ
#: job result (measured: no `JobResult` / `arq:result` consumer anywhere), so
#: the default keeps status/reference semantics and stores no result body.
RESULT_POLICY_STATUS = "status"
RESULT_POLICY_FULL = "full"

#: Every result policy the adapter accepts. ``Settings`` enforces the same set
#: at boot (``MONGO_QUEUE_RESULT_POLICY``), so a typo fails at start-up rather
#: than silently degrading to "store nothing".
RESULT_POLICIES = frozenset({RESULT_POLICY_STATUS, RESULT_POLICY_FULL})


def _retention_index_matches(found: dict[str, Any], expire_after_seconds: int) -> bool:
    """Whether an installed retention index is exactly the one we intend.

    All three parts are checked. A missing ``partialFilterExpression`` means an
    index from a build that predates the terminal-only guard, which must not be
    accepted as "already there".
    """
    if _index_key(found.get("key")) != (("finished_at", 1),):
        return False
    if found.get("expireAfterSeconds") != expire_after_seconds:
        return False
    return found.get("partialFilterExpression") == RETENTION_PARTIAL_FILTER


def _index_key(key: Any) -> tuple[tuple[str, Any], ...]:
    """Normalise an index key pattern to comparable tuples.

    ``index_information()`` reports the key as a list of ``(field, direction)``
    pairs on some driver versions and as a dict on others, and comparing the raw
    value would reject our own freshly created index and rebuild it on every
    start-up.
    """
    if isinstance(key, dict):
        return tuple(key.items())
    return tuple((field, direction) for field, direction in key or ())


class MissingTenantError(QueueError):
    """Raised when a Mongo job is submitted without a tenant identity.

    The brief is explicit that every Mongo queue job must carry a tenant. An
    empty ``tenant_id`` would produce a queue row that no tenant-scoped read can
    ever see, which is how orphaned work accumulates silently - so it is
    rejected at the producer boundary instead.
    """


class MongoQueueAdapter:
    """``WorkerQueue`` adapter over the MongoDB-backed queue."""

    def __init__(
        self,
        db: AsyncIOMotorDatabase[Any],
        *,
        collection_name: str = "worker_jobs",
        lease_seconds: float = 120.0,
        heartbeat_seconds: float = 30.0,
        max_tries: int = 3,
        backoff_seconds: tuple[float, ...] = (5.0, 30.0, 180.0),
        poll_schedule: tuple[float, ...] = (1.0, 2.0, 5.0, 10.0, 30.0),
        max_result_bytes: int = 16_384,
        retention_days: float = 0.0,
        result_policy: str = RESULT_POLICY_STATUS,
    ) -> None:
        self._queue_name = f"{db.name}.{collection_name}"
        self._retention_days = retention_days
        self._result_policy = result_policy
        self._queue = MongoQueue(
            db,
            QueueConfig(
                db_name=db.name,
                collection_name=collection_name,
                lease_seconds=lease_seconds,
                heartbeat_interval_seconds=heartbeat_seconds,
                max_tries=max_tries,
                backoff_seconds=tuple(backoff_seconds),
                poll_schedule=tuple(poll_schedule),
                max_result_bytes=max_result_bytes,
            ),
        )

    @property
    def queue(self) -> MongoQueue:
        """The underlying store (ops diagnostics / advanced use)."""
        return self._queue

    @property
    def queue_name(self) -> str:
        return self._queue_name

    @property
    def lease_seconds(self) -> float:
        return self._queue.lease_seconds

    @property
    def retention_days(self) -> float:
        return self._retention_days

    @property
    def result_policy(self) -> str:
        return self._result_policy

    # ------------------------------------------------------------------
    # indexes / retention
    # ------------------------------------------------------------------

    async def ensure_indexes(self) -> list[str]:
        """Create the core queue indexes plus the optional retention TTL.

        Retention is OFF unless ``retention_days > 0``: Phase 16 deliberately
        left the production retention policy UNDECIDED, so this phase makes it
        configurable and never installs a TTL index implicitly. Phase 17C.1
        kept that default; enabling retention remains an explicit deployment
        decision.
        """
        created = await self._queue.ensure_indexes()
        if self._retention_days > 0 and await self._ensure_retention_index():
            created.append(RETENTION_INDEX_NAME)
        return created

    async def _ensure_retention_index(self) -> bool:
        """Install the terminal-only TTL index, repairing a stale definition.

        Returns whether a (re)build happened. The index is *converged* on the
        intended definition rather than merely created-if-absent: an index left
        over from an older release, or one built for a different configured
        window, would otherwise be kept forever. That failure is silent and
        directional - shrinking the window would do nothing while an
        unbounded TTL stayed in place.
        """
        expire_after_seconds = int(self._retention_days * 86_400)
        existing = await self._queue.collection.index_information()
        found = existing.get(RETENTION_INDEX_NAME)
        if found is not None and _retention_index_matches(found, expire_after_seconds):
            return False
        if found is not None:
            # Tolerate a concurrent starter having dropped it already.
            try:
                await self._queue.collection.drop_index(RETENTION_INDEX_NAME)
            except OperationFailure:
                # A concurrent starter dropped it first; the rebuild below is
                # then a no-op that recreates the same definition.
                pass
        await self._queue.collection.create_index(
            "finished_at",
            expireAfterSeconds=expire_after_seconds,
            name=RETENTION_INDEX_NAME,
            partialFilterExpression=RETENTION_PARTIAL_FILTER,
        )
        return True

    # ------------------------------------------------------------------
    # producer
    # ------------------------------------------------------------------

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
        now: datetime | None = None,
    ) -> str:
        """Insert a job and return its id.

        ``job_id``/``dedup_key`` map to the store's unique ``dedup_key``:
        a duplicate submission collapses to the existing job id (this backend
        signals the *existing* id rather than raising, matching the prototype
        and differing from ARQ, which signals suppression with ``None``).
        ``defer_by`` schedules ``run_at`` in the future, mirroring ARQ's
        ``_defer_by``. ``now`` exists for deterministic tests only.

        ``tenant_id`` is required: a job row with no tenant could never be read
        back through a tenant-scoped query, so it would be unowned work nobody
        can observe or cancel. Note this is stricter than the ``WorkerQueue``
        protocol's default of ``""`` - the ARQ adapter keeps the protocol's
        laxer default because ARQ has no tenant-scoped read path to protect.
        """
        validate_function(function)
        validate_payload(function, payload or {})
        if self._result_policy not in RESULT_POLICIES:
            raise QueueError(
                f"Unknown result policy {self._result_policy!r}; "
                f"expected one of {sorted(RESULT_POLICIES)}."
            )
        if not (tenant_id or "").strip():
            raise MissingTenantError(
                f"Mongo queue job {function!r} requires a non-empty tenant_id; "
                "the authoritative tenant is the domain row's, but the queue row "
                "must be attributable too."
            )
        run_at: datetime | None = None
        if defer_by is not None and defer_by > 0:
            run_at = add_seconds(utcnow() if now is None else now, defer_by)
        # ARQ's `_job_id` is its idempotency handle; Mongo enforces idempotency
        # on `dedup_key`, so either interface knob lands here.
        key = job_id if job_id is not None else dedup_key
        return await self._queue.enqueue(
            function=function,
            payload=dict(payload or {}),
            tenant_id=tenant_id,
            run_at=run_at,
            dedup_key=key,
            max_tries=max_tries,
            now=now,
        )

    # ------------------------------------------------------------------
    # consumer
    # ------------------------------------------------------------------

    async def claim(self, worker_id: str, *, now: datetime | None = None) -> QueueJob | None:
        """Atomically claim one eligible job for ``worker_id``."""
        job = await self._queue.claim(worker_id, now=now)
        return None if job is None else self._to_queue_job(job)

    async def heartbeat(
        self,
        job_id: str,
        worker_id: str,
        *,
        execution_version: int | None = None,
        now: datetime | None = None,
    ) -> bool:
        """Renew this execution's lease; ``False`` once the worker is fenced out."""
        return await self._queue.renew_lease(
            job_id, worker_id, execution_version=execution_version, now=now
        )

    async def complete(
        self,
        job_id: str,
        worker_id: str,
        *,
        execution_version: int,
        result: Any = None,
        now: datetime | None = None,
    ) -> bool:
        """Complete the job iff the caller owns this exact execution.

        ``result`` is stored only under the ``full`` result policy. Under the
        default ``status`` policy the result is dropped: Phase 16 measured that
        nothing in the repository reads an ARQ job result, so persisting the
        body would grow every queue document (and widen the blast radius of a
        queue-collection exposure) for no consumer. The ``full`` policy exists
        for an operator who explicitly wants ARQ ``keep_result`` parity.
        """
        stored = result if self._result_policy == RESULT_POLICY_FULL else None
        return await self._queue.complete_job(
            job_id,
            worker_id,
            execution_version=execution_version,
            result=stored,
            now=now,
        )

    async def fail(
        self,
        job_id: str,
        worker_id: str,
        *,
        execution_version: int,
        error: str,
        retry: bool = True,
        now: datetime | None = None,
    ) -> str:
        """Record a failure; returns the resulting status string.

        ``retry=True`` maps to ARQ's retried paths (``Retry`` / ``RetryJob`` /
        job-raised ``asyncio.CancelledError``): re-queued with backoff until
        ``max_tries``. ``retry=False`` maps to ARQ's *ordinary exception* and
        *job timeout* paths, which dead-letter immediately - measured on arq
        0.28, both are terminal and are NOT retried despite ``max_tries=3``.
        """
        return await self._queue.fail_job(
            job_id,
            worker_id,
            error,
            execution_version=execution_version,
            retry=retry,
            now=now,
        )

    async def retire_expired(self, *, now: datetime | None = None) -> int:
        return await self._queue.retire_expired(now=now)

    async def ping(self) -> bool:
        return await self._queue.ping()

    # ------------------------------------------------------------------
    # dispatch plumbing
    # ------------------------------------------------------------------

    async def job_args(self, job: QueueJob) -> tuple[Any, ...]:
        """Positional args to pass to the registered job coroutine."""
        return args_from_payload(job.function, dict(job.payload))

    # ------------------------------------------------------------------
    # ops diagnostics
    # ------------------------------------------------------------------

    async def get(self, job_id: str) -> Job | None:
        return await self._queue.get(job_id)

    async def get_for_tenant(self, tenant_id: str, job_id: str) -> Job | None:
        """Tenant-scoped read: returns ``None`` for another tenant's job."""
        return await self._queue.find_for_tenant(tenant_id, job_id)

    async def list_jobs(self, status: str | None = None, limit: int = 50) -> list[Job]:
        return await self._queue.list_jobs(status=status, limit=limit)

    async def count_documents(self, status: str | None = None) -> int:
        return await self._queue.count_documents(status)

    async def delete_all(self) -> None:
        await self._queue.delete_all()

    @staticmethod
    def _to_queue_job(job: Job) -> QueueJob:
        return QueueJob(
            id=job.id,
            function=job.function,
            payload=dict(job.payload),
            tenant_id=job.tenant_id,
            job_try=job.attempts,
            max_tries=job.max_tries,
            execution_version=job.execution_version,
            enqueue_time=job.created_at,
            score=job.run_at,
        )


__all__ = [
    "RETENTION_INDEX_NAME",
    "RETENTION_PARTIAL_FILTER",
    "RESULT_POLICIES",
    "RESULT_POLICY_FULL",
    "RESULT_POLICY_STATUS",
    "MissingTenantError",
    "MongoQueueAdapter",
]
