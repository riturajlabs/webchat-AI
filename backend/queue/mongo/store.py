"""MongoDB-backed durable worker queue (production storage engine).

Promoted from the validated Phase 15/16 prototype
(``backend/prototypes/mongo_queue/queue.py``) with ONE behavioural change,
called out in ``fail_job`` below: every state transition is a single
conditional write guarded by the ownership fence. The prototype performed a
read-then-write for the ``dead``/``retry_pending`` transitions, which left a
window in which a worker that had already been fenced out could still mark a
reclaimed job terminal. Production execution must not have that window, so the
read and the write now share one filter.

Execution semantics are **at-least-once**. Exactly-once is NOT provided: a job
whose lease expires can be reclaimed and re-run while the original worker is
still alive. Safety therefore rests on (a) this module's ownership fence and
(b) the domain fences already in ``crawl_website`` / ``KnowledgeProcessor``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from backend.queue.mongo.config import QueueConfig
from backend.queue.mongo.ids import add_seconds, utcnow
from backend.queue.mongo.models import (
    CLAIMABLE_PENDING,
    STATUS_COMPLETED,
    STATUS_DEAD,
    STATUS_PENDING,
    STATUS_RETRY_PENDING,
    STATUS_RUNNING,
    Job,
)

T = dict[str, Any]


def _now(value: datetime | None) -> datetime:
    return value if value is not None else utcnow()


class MongoQueue:
    """Mongo-backed durable queue with atomic claim, leases and fencing.

    - The payload is stored inline (the real jobs carry small id-only payloads):
      no second collection, no indirection.
    - Claim is ONE atomic ``find_one_and_update`` (update pipeline) that selects
      an eligible job, increments ``attempts``/``execution_version`` and sets the
      lease in the same server round-trip. There is no find-then-update window.
    - ``attempts < max_tries`` is enforced inside the claim filter via ``$expr``
      so an exhausted job can never be reclaimed.
    - ``execution_version`` is the fencing token: complete/fail must match it.
    - Deduplication is index-level: a ``dedup_key`` unique partial index means
      racing submissions collapse to one logical job.
    """

    def __init__(
        self,
        db: AsyncIOMotorDatabase[Any],
        config: QueueConfig,
    ) -> None:
        self._config = config
        self._collection: AsyncIOMotorCollection[T] = db[config.collection_name]
        self._ops = 0

    # ------------------------------------------------------------------
    # stats / connectivity
    # ------------------------------------------------------------------

    @property
    def collection(self) -> AsyncIOMotorCollection[T]:
        return self._collection

    @property
    def config(self) -> QueueConfig:
        return self._config

    @property
    def ops(self) -> int:
        """Number of queue-level operations issued since construction/reset."""
        return self._ops

    @property
    def lease_seconds(self) -> float:
        return self._config.lease_seconds

    def reset_ops(self) -> None:
        self._ops = 0

    def _op(self) -> None:
        self._ops += 1

    async def ping(self) -> bool:
        try:
            await self._collection.database.command("ping")
            return True
        except Exception:  # noqa: BLE001 - probe must never raise
            return False

    # ------------------------------------------------------------------
    # indexes
    # ------------------------------------------------------------------

    async def ensure_indexes(self) -> list[str]:
        """Create the minimal index set; document why each one exists.

        1. ``{status:1, run_at:1}`` -> claim: pending/retry_pending by run_at
           (the hot path; also serves delayed jobs).
        2. ``{status:1, lease_expires_at:1}`` -> claim + retire: lease-expired
           ``running`` rows (crash recovery).
        3. ``dedup_key`` unique, partial on string values -> atomic collapse of
           submissions carrying the same dedup key. Partial so jobs without a
           key never collide with each other.
        """
        existing = await self._collection.index_information()
        created: list[str] = []
        if "status_1_run_at_1" not in existing:
            await self._collection.create_index([("status", 1), ("run_at", 1)])
            created.append("status_1_run_at_1")
        if "status_1_lease_expires_at_1" not in existing:
            await self._collection.create_index([("status", 1), ("lease_expires_at", 1)])
            created.append("status_1_lease_expires_at_1")
        if "dedup_key_1" not in existing:
            await self._collection.create_index(
                "dedup_key",
                unique=True,
                partialFilterExpression={"dedup_key": {"$type": "string"}},
            )
            created.append("dedup_key_1")
        return created

    # ------------------------------------------------------------------
    # enqueue
    # ------------------------------------------------------------------

    async def enqueue(
        self,
        *,
        function: str,
        payload: dict[str, Any] | None = None,
        tenant_id: str = "",
        run_at: datetime | None = None,
        dedup_key: str | None = None,
        max_tries: int | None = None,
        now: datetime | None = None,
    ) -> str:
        """Insert a job and return its id.

        With a ``dedup_key`` the insert is deduplicated by the unique partial
        index: a concurrent duplicate submission collapses to one logical job
        and this returns the *existing* id.
        """
        now = _now(now)
        job = Job(
            function=function,
            payload=payload or {},
            tenant_id=tenant_id,
            status=STATUS_PENDING,
            run_at=run_at if run_at is not None else now,
            max_tries=max_tries or self._config.max_tries,
            created_at=now,
        )
        doc = job.to_doc()
        if dedup_key is not None:
            doc["dedup_key"] = dedup_key
        try:
            self._op()
            await self._collection.insert_one(doc)
            return job.id
        except DuplicateKeyError:
            # Deduplicated: the race loser re-reads the canonical id rather
            # than inserting a second logical job.
            existing = await self._collection.find_one({"dedup_key": dedup_key})
            self._op()
            if existing is None:
                raise
            return str(existing["_id"])

    # ------------------------------------------------------------------
    # atomic claim
    # ------------------------------------------------------------------

    async def claim(self, worker_id: str, *, now: datetime | None = None) -> Job | None:
        """Atomically claim exactly one eligible job for ``worker_id``.

        A job is eligible when:

        - ``status in {pending, retry_pending}`` and ``run_at <= now``, or
        - ``status == running`` and ``lease_expires_at <= now``,

        and ``attempts < max_tries``. Two workers can never receive the same
        job in the same instant.
        """
        now = _now(now)
        filter_doc: dict[str, Any] = {
            "$expr": {"$lt": ["$attempts", "$max_tries"]},
            "$or": [
                {
                    "status": {"$in": sorted(CLAIMABLE_PENDING)},
                    "run_at": {"$lte": now},
                },
                {
                    "status": STATUS_RUNNING,
                    "lease_expires_at": {"$lte": now},
                },
            ],
        }
        update_pipeline: list[dict[str, Any]] = [
            {
                "$set": {
                    "status": STATUS_RUNNING,
                    "locked_by": worker_id,
                    "started_at": now,
                    "lease_expires_at": add_seconds(now, self._config.lease_seconds),
                    # An update pipeline has no `$inc` stage; arithmetic `$set`
                    # is the documented equivalent and stays atomic with claim.
                    "attempts": {"$add": ["$attempts", 1]},
                    "execution_version": {"$add": ["$execution_version", 1]},
                }
            }
        ]
        self._op()
        doc = await self._collection.find_one_and_update(
            filter_doc,
            update_pipeline,
            sort=[("run_at", 1), ("_id", 1)],
            return_document=ReturnDocument.AFTER,
        )
        return Job.from_doc(doc)

    # ------------------------------------------------------------------
    # lease + heartbeat
    # ------------------------------------------------------------------

    def _owner_filter(self, job_id: str, worker_id: str, execution_version: int | None) -> T:
        """The ownership fence: identity + live lease-holder + fencing token.

        Every terminal write is filtered on exactly this document, so a worker
        whose execution was reclaimed (its ``execution_version`` was bumped and
        ``locked_by`` replaced by the new claim) matches nothing and can never
        write.
        """
        filter_doc: T = {
            "_id": job_id,
            "status": STATUS_RUNNING,
            "locked_by": worker_id,
        }
        if execution_version is not None:
            filter_doc["execution_version"] = execution_version
        return filter_doc

    async def renew_lease(
        self,
        job_id: str,
        worker_id: str,
        *,
        execution_version: int | None = None,
        now: datetime | None = None,
    ) -> bool:
        """Renew the lease iff the caller still owns the execution.

        Ownership is ``locked_by == worker_id``, ``status == running`` and the
        lease must still be in force. Worker A can never renew worker B's lease.

        When ``execution_version`` is supplied it is part of the fence, exactly
        as in :meth:`_owner_filter`. Worker identity alone is not sufficient: a
        worker that reclaims its own expired job under the same id would
        otherwise let the *stale* execution extend the new execution's lease
        indefinitely, and since the stale execution can no longer complete, the
        job would stall with a live lease and no owner able to finish it.
        """
        now = _now(now)
        self._op()
        filter_doc: dict[str, Any] = {
            "_id": job_id,
            "status": STATUS_RUNNING,
            "locked_by": worker_id,
            "lease_expires_at": {"$gt": now},
        }
        if execution_version is not None:
            filter_doc["execution_version"] = execution_version
        result = await self._collection.update_one(
            filter_doc,
            {"$set": {"lease_expires_at": add_seconds(now, self._config.lease_seconds)}},
        )
        return result.matched_count == 1

    # ------------------------------------------------------------------
    # completion (ownership + fencing token enforced)
    # ------------------------------------------------------------------

    async def complete_job(
        self,
        job_id: str,
        worker_id: str,
        *,
        execution_version: int | None,
        result: Any = None,
        now: datetime | None = None,
    ) -> bool:
        """Complete the job iff the caller owns this exact execution.

        Matches ``_id`` + ``status == running`` + ``locked_by == worker_id`` +
        ``execution_version``. A stale worker (lease reclaimed, version bumped)
        or a different worker can never complete someone else's execution.
        """
        now = _now(now)
        update: T = {
            "$set": {
                "status": STATUS_COMPLETED,
                "finished_at": now,
                "lease_expires_at": None,
            }
        }
        if result is not None:
            update["$set"]["result"] = self._encode_result(result)
        self._op()
        outcome = await self._collection.update_one(
            self._owner_filter(job_id, worker_id, execution_version), update
        )
        return outcome.matched_count == 1

    # ------------------------------------------------------------------
    # failure + retry/dead-letter
    # ------------------------------------------------------------------

    async def fail_job(
        self,
        job_id: str,
        worker_id: str,
        error: str,
        *,
        execution_version: int | None,
        retry: bool = True,
        now: datetime | None = None,
    ) -> str:
        """Record a failure, returning the resulting status.

        Returns ``"dead"`` when ``retry=False`` or the attempt budget is spent,
        otherwise ``"retry_pending"`` with ``run_at = now + backoff(attempts)``.
        Returns ``"not_owned"`` when the caller has been fenced out.

        The read that decides retry-vs-dead and the write that applies it share
        ONE filter (the ownership fence). The prototype read the job
        unconditionally and then wrote on ``{"_id": ...}`` alone, so a worker
        that lost its lease between the read and the write could still mark a
        live, reclaimed job terminal. Here the terminal write simply matches
        nothing for a fenced worker.
        """
        now = _now(now)
        fence = self._owner_filter(job_id, worker_id, execution_version)
        job = await self.get(job_id, fence)
        if job is None:
            return "not_found" if await self.get(job_id) is None else "not_owned"
        exhausted = job.attempts >= job.max_tries
        if not retry or exhausted:
            update: T = {
                "$set": {
                    "status": STATUS_DEAD,
                    "finished_at": now,
                    "last_error": error,
                    "lease_expires_at": None,
                }
            }
            target = STATUS_DEAD
        else:
            update = {
                "$set": {
                    "status": STATUS_RETRY_PENDING,
                    "run_at": add_seconds(now, self._backoff_seconds(job.attempts)),
                    "last_error": error,
                    "lease_expires_at": None,
                }
            }
            target = STATUS_RETRY_PENDING
        self._op()
        result = await self._collection.update_one(fence, update)
        return target if result.matched_count == 1 else "not_owned"

    def _backoff_seconds(self, attempts: int) -> float:
        index = max(0, min(attempts - 1, len(self._config.backoff_seconds) - 1))
        return self._config.backoff_seconds[index]

    # ------------------------------------------------------------------
    # operational utilities
    # ------------------------------------------------------------------

    async def get(self, job_id: str, filter_extra: dict[str, Any] | None = None) -> Job | None:
        """Read one job, optionally under an extra filter (used to read under
        the ownership fence)."""
        query: T = {"_id": job_id}
        if filter_extra:
            query.update(filter_extra)
        self._op()
        doc = await self._collection.find_one(query)
        return Job.from_doc(doc)

    async def find_for_tenant(self, tenant_id: str, job_id: str) -> Job | None:
        """Tenant-scoped read: a tenant can never observe another's job.

        Mirrors the repository rule "every query is scoped by tenant_id".
        """
        self._op()
        doc = await self._collection.find_one({"_id": job_id, "tenant_id": tenant_id})
        return Job.from_doc(doc)

    async def list_jobs(self, status: str | None = None, limit: int = 50) -> list[Job]:
        query: dict[str, Any] = {}
        if status is not None:
            query["status"] = status
        cursor = self._collection.find(query).sort("created_at", -1).limit(limit)
        self._op()
        return [job for doc in await cursor.to_list(length=limit) if (job := Job.from_doc(doc))]

    async def retire_expired(self, *, now: datetime | None = None) -> int:
        """Move crashed-and-exhausted RUNNING rows to DEAD.

        A running row whose lease expired AND whose attempts already reached
        max_tries can never be claimed again; it would stick forever. This marks
        those rows dead (crash on the final attempt). Idempotent.
        """
        now = _now(now)
        self._op()
        result = await self._collection.update_many(
            {
                "status": STATUS_RUNNING,
                "lease_expires_at": {"$lte": now},
                "$expr": {"$gte": ["$attempts", "$max_tries"]},
            },
            {
                "$set": {
                    "status": STATUS_DEAD,
                    "finished_at": now,
                    "last_error": "lease expired on final attempt (worker crashed)",
                }
            },
        )
        return result.modified_count

    async def delete_all(self) -> None:
        await self._collection.delete_many({})

    def _encode_result(self, result: Any) -> Any:
        """Clamp oversized results so queue documents stay small (M0 storage).

        Result *retention* is a separate, still-open policy question (Phase 16
        left it UNDECIDED); this only bounds the size of a result that was
        chosen to be stored at all.
        """
        encoded = result
        try:
            import json

            size = len(json.dumps(encoded, default=str).encode("utf-8"))
        except Exception:  # noqa: BLE001 - unencodable result is simply unbounded
            size = 0
        if size > self._config.max_result_bytes:
            return {"__truncated__": True, "bytes": size}
        return encoded

    async def count_documents(self, status: str | None = None) -> int:
        query: dict[str, Any] = {}
        if status is not None:
            query["status"] = status
        self._op()
        return await self._collection.count_documents(query)
