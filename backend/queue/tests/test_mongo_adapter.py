"""Mongo adapter behaviour against the ISOLATED prototype mongod.

These tests exercise the real store: atomic claim, the ownership fence,
crash recovery, retry/backoff and tenant scoping. Nothing here sends mail,
crawls a site or calls a provider - only queue documents are written to a
throwaway database.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from backend.queue.errors import InvalidPayloadError, QueueError, UnknownFunctionError
from backend.queue.mongo.ids import utcnow
from backend.queue.mongo.models import (
    STATUS_COMPLETED,
    STATUS_DEAD,
    STATUS_PENDING,
    STATUS_RETRY_PENDING,
    STATUS_RUNNING,
)
from backend.queue.mongo_adapter import (
    RESULT_POLICY_FULL,
    RESULT_POLICY_STATUS,
    RETENTION_INDEX_NAME,
    RETENTION_PARTIAL_FILTER,
    MissingTenantError,
    MongoQueueAdapter,
    _index_key,
)
from motor.motor_asyncio import AsyncIOMotorDatabase

_TENANT = "tenant-a"


async def _enqueue(
    adapter: MongoQueueAdapter,
    function: str = "process_document",
    **kwargs: Any,
) -> str:
    payload: dict[str, Any] = kwargs.pop("payload", {"document_id": "d1", "run_id": None})
    tenant: str = kwargs.pop("tenant_id", _TENANT)
    return await adapter.enqueue(function, payload=payload, tenant_id=tenant, **kwargs)


# ----------------------------------------------------------------------
# connectivity + indexes
# ----------------------------------------------------------------------


async def test_ping_reports_the_isolated_server(adapter: MongoQueueAdapter) -> None:
    assert await adapter.ping() is True


async def test_ping_is_false_when_the_server_is_unreachable() -> None:
    """A probe reports availability; it must never raise at a caller."""
    from motor.motor_asyncio import AsyncIOMotorClient

    unreachable: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        "mongodb://127.0.0.1:1", serverSelectionTimeoutMS=500
    )
    try:
        dead = MongoQueueAdapter(unreachable["queue_probe_db"], collection_name="worker_jobs")
        assert await dead.ping() is False
    finally:
        unreachable.close()


async def test_core_indexes_are_created(adapter: MongoQueueAdapter) -> None:
    names = set(await adapter.queue.collection.index_information())
    assert {"status_1_run_at_1", "status_1_lease_expires_at_1", "dedup_key_1"} <= names


async def test_retention_ttl_index_is_absent_by_default(adapter: MongoQueueAdapter) -> None:
    """Phase 16 left retention UNDECIDED, so no TTL may be installed silently."""
    assert adapter.retention_days == 0.0
    assert RETENTION_INDEX_NAME not in await adapter.queue.collection.index_information()


async def test_retention_ttl_index_is_created_when_configured(
    retention_adapter: MongoQueueAdapter,
) -> None:
    assert retention_adapter.retention_days == 7.0
    info = await retention_adapter.queue.collection.index_information()
    assert RETENTION_INDEX_NAME in info
    assert info[RETENTION_INDEX_NAME]["expireAfterSeconds"] == 7 * 86_400


async def test_ensure_indexes_is_idempotent(adapter: MongoQueueAdapter) -> None:
    await adapter.ensure_indexes()
    await adapter.ensure_indexes()
    names = list(await adapter.queue.collection.index_information())
    assert len(names) == len(set(names))


# ----------------------------------------------------------------------
# retention: terminal-only safety (Phase 17C.1)
# ----------------------------------------------------------------------


async def test_retention_ttl_index_is_restricted_to_terminal_states(
    retention_adapter: MongoQueueAdapter,
) -> None:
    """The TTL index must carry a partial filter limited to terminal states.

    This is the whole safety argument for retention, so it is asserted on the
    installed index rather than on the helper that builds it: a TTL monitor
    only ever considers documents present in its index, so a partial filter
    over terminal states makes deletion of a non-terminal row impossible
    instead of merely unlikely.
    """
    info = await retention_adapter.queue.collection.index_information()
    assert info[RETENTION_INDEX_NAME]["partialFilterExpression"] == RETENTION_PARTIAL_FILTER
    assert _index_key(info[RETENTION_INDEX_NAME]["key"]) == (("finished_at", 1),)


@pytest.mark.parametrize(
    ("state", "expected_deleteable"),
    [
        (STATUS_PENDING, False),
        (STATUS_RETRY_PENDING, False),
        (STATUS_RUNNING, False),
        (STATUS_COMPLETED, True),
        (STATUS_DEAD, True),
    ],
)
async def test_retention_partial_filter_classifies_every_job_state(
    retention_adapter: MongoQueueAdapter,
    state: str,
    expected_deleteable: bool,
) -> None:
    """Only terminal states are inside the TTL index; every other state is out.

    A TTL monitor selects its victims by index membership, and index membership
    for a partial index is exactly "matches the partial filter". So this asserts
    the per-state deletion decision the server will make, for a job carrying a
    long-elapsed ``finished_at`` - the worst case, and the case an invariant
    bug would produce.
    """
    now = utcnow()
    await retention_adapter.queue.collection.insert_one(
        {
            "_id": f"probe-{state}",
            "function": "process_document",
            "payload": {"document_id": "d1", "run_id": None},
            "tenant_id": _TENANT,
            "status": state,
            # Deliberately far in the past: a stale finished_at on a live row is
            # exactly the state the partial filter has to reject.
            "run_at": now - timedelta(days=365),
            "attempts": 0,
            "max_tries": 3,
            "execution_version": 0,
            "created_at": now - timedelta(days=365),
            "started_at": None,
            "lease_expires_at": None,
            "locked_by": None,
            "last_error": None,
            "result": None,
            "finished_at": now - timedelta(days=365),
        }
    )
    inside = await retention_adapter.queue.collection.count_documents(RETENTION_PARTIAL_FILTER)
    assert inside == (1 if expected_deleteable else 0)


async def test_retention_never_reaches_a_job_scheduled_in_the_future(
    retention_adapter: MongoQueueAdapter,
) -> None:
    """A pending job far in the future is not 'stale' and must survive."""
    now = utcnow()
    await retention_adapter.queue.collection.insert_one(
        {
            "_id": "future-pending",
            "function": "process_document",
            "payload": {},
            "tenant_id": _TENANT,
            "status": STATUS_PENDING,
            "run_at": now + timedelta(days=30),
            "attempts": 0,
            "max_tries": 3,
            "execution_version": 0,
            "created_at": now,
            "finished_at": None,
        }
    )
    assert await retention_adapter.queue.collection.count_documents(RETENTION_PARTIAL_FILTER) == 0


async def test_retention_never_reaches_a_live_lease_even_if_lease_looks_stale(
    retention_adapter: MongoQueueAdapter,
) -> None:
    """A running job is excluded regardless of its lease timestamp.

    An expired lease does not make a job's state unambiguous: the previous owner
    may still be alive and about to report. That ambiguity is the reason
    'running' is outside the retention filter entirely.
    """
    now = utcnow()
    await retention_adapter.queue.collection.insert_one(
        {
            "_id": "stale-lease-running",
            "function": "process_document",
            "payload": {},
            "tenant_id": _TENANT,
            "status": STATUS_RUNNING,
            "run_at": now - timedelta(days=1),
            "attempts": 1,
            "max_tries": 3,
            "execution_version": 1,
            "created_at": now - timedelta(days=1),
            "locked_by": "worker-1",
            # Far past: the server cannot tell this apart from a dead worker.
            "lease_expires_at": now - timedelta(days=365),
            "finished_at": None,
        }
    )
    assert await retention_adapter.queue.collection.count_documents(RETENTION_PARTIAL_FILTER) == 0


async def test_retention_repairs_a_stale_index_definition(
    queue_db: AsyncIOMotorDatabase[dict[str, Any]],
) -> None:
    """A changed retention window must actually take effect.

    The previous implementation created the index only when the name was
    absent, so re-deploying with a different window silently kept the old one -
    a window can be shortened in config and never shrink in the database.
    """
    collection = "worker_jobs_retention_repair"
    await queue_db.drop_collection(collection)
    wide = MongoQueueAdapter(queue_db, collection_name=collection, retention_days=30.0)
    await wide.ensure_indexes()
    info = await wide.queue.collection.index_information()
    assert info[RETENTION_INDEX_NAME]["expireAfterSeconds"] == 30 * 86_400

    narrow = MongoQueueAdapter(queue_db, collection_name=collection, retention_days=1.0)
    created = await narrow.ensure_indexes()
    assert RETENTION_INDEX_NAME in created
    info = await narrow.queue.collection.index_information()
    assert info[RETENTION_INDEX_NAME]["expireAfterSeconds"] == 86_400
    await queue_db.drop_collection(collection)


async def test_retention_repairs_an_index_without_the_terminal_guard(
    queue_db: AsyncIOMotorDatabase[dict[str, Any]],
) -> None:
    """An unfiltered TTL index from an older build is not accepted as-is.

    Without the partial filter the index contains every row, so a row that
    somehow carried a ``finished_at`` while still active would be collected.
    That definition is rebuilt rather than kept.
    """
    collection = "worker_jobs_retention_unfiltered"
    await queue_db.drop_collection(collection)
    legacy = MongoQueueAdapter(queue_db, collection_name=collection, retention_days=7.0)
    # Recreate the pre-17C.1 shape directly, bypassing the new builder.
    await legacy.ensure_indexes()
    await legacy.queue.collection.drop_index(RETENTION_INDEX_NAME)
    await legacy.queue.collection.create_index(
        "finished_at", expireAfterSeconds=7 * 86_400, name=RETENTION_INDEX_NAME
    )
    info = await legacy.queue.collection.index_information()
    assert "partialFilterExpression" not in info[RETENTION_INDEX_NAME]

    created = await legacy.ensure_indexes()
    assert RETENTION_INDEX_NAME in created
    info = await legacy.queue.collection.index_information()
    assert info[RETENTION_INDEX_NAME]["partialFilterExpression"] == RETENTION_PARTIAL_FILTER
    await queue_db.drop_collection(collection)


async def test_retention_ensure_indexes_is_idempotent_when_already_correct(
    queue_db: AsyncIOMotorDatabase[dict[str, Any]],
) -> None:
    """A second ensure must not rebuild an already-correct retention index.

    Rebuilding on every start-up would drop and recreate the index each deploy,
    which is both wasteful and a window where the TTL guard is absent. This
    asserts the definition-matcher recognises the index it just installed -
    the case that silently failed when the driver reported the index key as a
    list of pairs rather than a dict.
    """
    collection = "worker_jobs_retention_idempotent"
    await queue_db.drop_collection(collection)
    adapter = MongoQueueAdapter(queue_db, collection_name=collection, retention_days=7.0)
    first = await adapter.ensure_indexes()
    assert RETENTION_INDEX_NAME in first

    second = await adapter.ensure_indexes()
    assert RETENTION_INDEX_NAME not in second
    names = list(await adapter.queue.collection.index_information())
    assert len(names) == len(set(names))
    await queue_db.drop_collection(collection)


async def test_retention_stays_off_by_default_with_a_partial_filter_present(
    queue_db: AsyncIOMotorDatabase[dict[str, Any]],
) -> None:
    """The guard does not switch retention on: default stays 0.0.

    Hardening the mechanism must not quietly change the deployment posture
    Phase 16 left UNDECIDED. Enabling retention stays an explicit choice.
    """
    collection = "worker_jobs_retention_off"
    await queue_db.drop_collection(collection)
    off = MongoQueueAdapter(queue_db, collection_name=collection)
    await off.ensure_indexes()
    assert off.retention_days == 0.0
    assert RETENTION_INDEX_NAME not in await off.queue.collection.index_information()
    await queue_db.drop_collection(collection)


# ----------------------------------------------------------------------
# enqueue
# ----------------------------------------------------------------------


async def test_enqueue_returns_a_job_id_and_stores_pending(adapter: MongoQueueAdapter) -> None:
    job_id = await _enqueue(adapter)
    job = await adapter.get(job_id)
    assert job is not None
    assert job.status == "pending"
    assert job.tenant_id == _TENANT
    assert job.attempts == 0
    assert job.max_tries == 3


async def test_enqueue_rejects_an_unknown_function(adapter: MongoQueueAdapter) -> None:
    with pytest.raises(UnknownFunctionError):
        await _enqueue(adapter, "os.system", payload={})


async def test_enqueue_rejects_an_invalid_payload(adapter: MongoQueueAdapter) -> None:
    with pytest.raises(InvalidPayloadError):
        await _enqueue(adapter, payload={"document_id": ""})


async def test_enqueue_requires_a_tenant(adapter: MongoQueueAdapter) -> None:
    """An unowned queue row is unobservable work; reject it at the boundary."""
    with pytest.raises(MissingTenantError):
        await _enqueue(adapter, tenant_id="")
    with pytest.raises(MissingTenantError):
        await _enqueue(adapter, tenant_id="   ")


async def test_missing_tenant_error_is_a_queue_error(adapter: MongoQueueAdapter) -> None:
    with pytest.raises(QueueError):
        await _enqueue(adapter, tenant_id="")


async def test_enqueue_never_stores_a_row_without_a_tenant(adapter: MongoQueueAdapter) -> None:
    with pytest.raises(MissingTenantError):
        await _enqueue(adapter, tenant_id="")
    assert await adapter.count_documents() == 0


async def test_dedup_key_collapses_duplicate_submissions(adapter: MongoQueueAdapter) -> None:
    first = await _enqueue(adapter, dedup_key="doc:d1")
    second = await _enqueue(adapter, dedup_key="doc:d1")
    assert first == second
    assert await adapter.count_documents() == 1


async def test_job_id_maps_to_the_same_dedup_slot(adapter: MongoQueueAdapter) -> None:
    """`job_id` is ARQ's `_job_id`; on Mongo it is the dedup key."""
    first = await _enqueue(adapter, job_id="crawl:cj-1")
    second = await _enqueue(adapter, job_id="crawl:cj-1")
    assert first == second
    assert await adapter.count_documents() == 1


async def test_different_dedup_keys_create_distinct_jobs(adapter: MongoQueueAdapter) -> None:
    first = await _enqueue(adapter, dedup_key="doc:d1")
    second = await _enqueue(adapter, dedup_key="doc:d2")
    assert first != second
    assert await adapter.count_documents() == 2


async def test_jobs_without_a_dedup_key_never_collide(adapter: MongoQueueAdapter) -> None:
    """The unique index is partial, so key-less jobs are all distinct."""
    a = await _enqueue(adapter)
    b = await _enqueue(adapter)
    assert a != b
    assert await adapter.count_documents() == 2


async def test_defer_by_schedules_run_at_in_the_future(adapter: MongoQueueAdapter) -> None:
    job_id = await _enqueue(adapter, defer_by=30)
    job = await adapter.get(job_id)
    assert job is not None
    assert job.run_at > utcnow() + timedelta(seconds=25)


async def test_defer_by_zero_is_immediate(adapter: MongoQueueAdapter) -> None:
    """ARQ treats `_defer_by=0` as falsy; Mongo must match."""
    now = utcnow()
    job_id = await _enqueue(adapter, defer_by=0, now=now)
    job = await adapter.get(job_id)
    assert job is not None
    # BSON stores datetimes at millisecond resolution.
    assert abs((job.run_at - now).total_seconds()) < 0.001


# ----------------------------------------------------------------------
# claim
# ----------------------------------------------------------------------


async def test_claim_returns_none_on_an_empty_queue(adapter: MongoQueueAdapter) -> None:
    assert await adapter.claim("worker-1") is None


async def test_claim_marks_running_and_increments_attempts(adapter: MongoQueueAdapter) -> None:
    job_id = await _enqueue(adapter)
    job = await adapter.claim("worker-1")
    assert job is not None
    assert job.id == job_id
    assert job.job_try == 1
    assert job.execution_version == 1
    assert job.tenant_id == _TENANT
    # The claimed row itself is `running`, owned by this worker.
    stored = await adapter.get(job_id)
    assert stored is not None
    assert stored.status == STATUS_RUNNING
    assert stored.locked_by == "worker-1"


async def test_a_claimed_job_is_not_claimable_again(adapter: MongoQueueAdapter) -> None:
    """The lease is what stops a second worker, not the status alone."""
    await _enqueue(adapter)
    assert await adapter.claim("worker-1") is not None
    assert await adapter.claim("worker-2") is None


async def test_two_workers_never_claim_the_same_job(adapter: MongoQueueAdapter) -> None:
    await _enqueue(adapter)
    a = await adapter.claim("worker-1")
    b = await adapter.claim("worker-2")
    assert a is not None
    assert b is None


async def test_claim_skips_a_future_scheduled_job(adapter: MongoQueueAdapter) -> None:
    await _enqueue(adapter, defer_by=3600)
    assert await adapter.claim("worker-1") is None


async def test_claim_reclaims_an_expired_lease(adapter: MongoQueueAdapter) -> None:
    """Crash recovery: an expired running row is claimable again."""
    await _enqueue(adapter)
    first = await adapter.claim("worker-1")
    assert first is not None
    # Move the lease into the past to simulate a crashed worker's lease lapsing.
    await adapter.queue.collection.update_one(
        {"_id": first.id}, {"$set": {"lease_expires_at": utcnow() - timedelta(seconds=1)}}
    )
    second = await adapter.claim("worker-2")
    assert second is not None
    assert second.id == first.id
    assert second.execution_version == first.execution_version + 1
    assert second.job_try == first.job_try + 1


async def test_claim_stops_at_the_attempt_budget(adapter: MongoQueueAdapter) -> None:
    """`attempts < max_tries` is enforced inside the claim filter."""
    await _enqueue(adapter)
    for expected in (1, 2, 3):
        job = await adapter.claim("worker-1")
        assert job is not None
        assert job.job_try == expected
        await adapter.queue.collection.update_one(
            {"_id": job.id}, {"$set": {"lease_expires_at": utcnow() - timedelta(seconds=1)}}
        )
    assert await adapter.claim("worker-1") is None


# ----------------------------------------------------------------------
# heartbeat
# ----------------------------------------------------------------------


async def test_heartbeat_renews_the_owners_lease(adapter: MongoQueueAdapter) -> None:
    await _enqueue(adapter)
    job = await adapter.claim("worker-1")
    assert job is not None
    assert await adapter.heartbeat(job.id, "worker-1") is True


async def test_heartbeat_is_refused_for_a_different_worker(adapter: MongoQueueAdapter) -> None:
    await _enqueue(adapter)
    job = await adapter.claim("worker-1")
    assert job is not None
    assert await adapter.heartbeat(job.id, "worker-2") is False


async def test_heartbeat_is_refused_once_the_lease_lapsed(adapter: MongoQueueAdapter) -> None:
    await _enqueue(adapter)
    job = await adapter.claim("worker-1")
    assert job is not None
    await adapter.queue.collection.update_one(
        {"_id": job.id}, {"$set": {"lease_expires_at": utcnow() - timedelta(seconds=1)}}
    )
    assert await adapter.heartbeat(job.id, "worker-1") is False


# ----------------------------------------------------------------------
# complete
# ----------------------------------------------------------------------


async def test_complete_succeeds_for_the_owner(adapter: MongoQueueAdapter) -> None:
    job_id = await _enqueue(adapter)
    job = await adapter.claim("worker-1")
    assert job is not None
    assert (
        await adapter.complete(job.id, "worker-1", execution_version=job.execution_version) is True
    )
    stored = await adapter.get(job_id)
    assert stored is not None
    assert stored.status == "completed"
    assert stored.finished_at is not None


async def test_complete_is_refused_for_another_worker(adapter: MongoQueueAdapter) -> None:
    await _enqueue(adapter)
    job = await adapter.claim("worker-1")
    assert job is not None
    assert (
        await adapter.complete(job.id, "worker-2", execution_version=job.execution_version) is False
    )


async def test_complete_is_refused_for_a_stale_execution_version(
    adapter: MongoQueueAdapter,
) -> None:
    """THE fencing test: a worker whose execution was reclaimed cannot write."""
    job_id = await _enqueue(adapter)
    stale = await adapter.claim("worker-1")
    assert stale is not None
    await adapter.queue.collection.update_one(
        {"_id": job_id}, {"$set": {"lease_expires_at": utcnow() - timedelta(seconds=1)}}
    )
    fresh = await adapter.claim("worker-2")
    assert fresh is not None
    assert fresh.execution_version > stale.execution_version

    # The original, fenced-out worker now finishes and tries to complete.
    assert (
        await adapter.complete(job_id, "worker-1", execution_version=stale.execution_version)
        is False
    )
    stored = await adapter.get(job_id)
    assert stored is not None
    assert stored.status == STATUS_RUNNING, "a fenced worker must not change the row"


async def test_complete_cannot_resurrect_a_dead_job(adapter: MongoQueueAdapter) -> None:
    job_id = await _enqueue(adapter)
    job = await adapter.claim("worker-1")
    assert job is not None
    await adapter.fail(
        job.id, "worker-1", execution_version=job.execution_version, error="boom", retry=False
    )
    assert (
        await adapter.complete(job_id, "worker-1", execution_version=job.execution_version) is False
    )


# ----------------------------------------------------------------------
# result policy
# ----------------------------------------------------------------------


async def test_status_policy_drops_the_result_body(adapter: MongoQueueAdapter) -> None:
    """Default policy stores no result: nothing in the repo reads one."""
    assert adapter.result_policy == RESULT_POLICY_STATUS
    job_id = await _enqueue(adapter)
    job = await adapter.claim("worker-1")
    assert job is not None
    await adapter.complete(
        job.id, "worker-1", execution_version=job.execution_version, result={"big": "body"}
    )
    stored = await adapter.get(job_id)
    assert stored is not None
    assert stored.result is None


async def test_full_policy_stores_the_result(
    queue_db: AsyncIOMotorDatabase[dict[str, Any]],
) -> None:
    adapter = MongoQueueAdapter(
        queue_db, collection_name="worker_jobs_full", result_policy=RESULT_POLICY_FULL
    )
    await adapter.ensure_indexes()
    job_id = await _enqueue(adapter)
    job = await adapter.claim("worker-1")
    assert job is not None
    await adapter.complete(
        job.id, "worker-1", execution_version=job.execution_version, result={"answer": 42}
    )
    stored = await adapter.get(job_id)
    assert stored is not None
    assert stored.result == {"answer": 42}
    await queue_db.drop_collection("worker_jobs_full")


async def test_full_policy_clamps_an_oversized_result(
    queue_db: AsyncIOMotorDatabase[dict[str, Any]],
) -> None:
    adapter = MongoQueueAdapter(
        queue_db,
        collection_name="worker_jobs_clamp",
        result_policy=RESULT_POLICY_FULL,
        max_result_bytes=128,
    )
    await adapter.ensure_indexes()
    job_id = await _enqueue(adapter)
    job = await adapter.claim("worker-1")
    assert job is not None
    await adapter.complete(
        job.id, "worker-1", execution_version=job.execution_version, result={"blob": "x" * 4096}
    )
    stored = await adapter.get(job_id)
    assert stored is not None
    assert stored.result["__truncated__"] is True
    await queue_db.drop_collection("worker_jobs_clamp")


async def test_unknown_result_policy_is_rejected(
    queue_db: AsyncIOMotorDatabase[dict[str, Any]],
) -> None:
    adapter = MongoQueueAdapter(
        queue_db, collection_name="worker_jobs_bad_policy", result_policy="everything"
    )
    with pytest.raises(QueueError):
        await _enqueue(adapter)


# ----------------------------------------------------------------------
# fail / retry / dead-letter
# ----------------------------------------------------------------------


async def test_fail_without_retry_dead_letters_immediately(adapter: MongoQueueAdapter) -> None:
    """ARQ parity: an ordinary exception is terminal on the FIRST attempt."""
    job_id = await _enqueue(adapter)
    job = await adapter.claim("worker-1")
    assert job is not None
    status = await adapter.fail(
        job.id,
        "worker-1",
        execution_version=job.execution_version,
        error="ValueError: boom",
        retry=False,
    )
    assert status == STATUS_DEAD
    stored = await adapter.get(job_id)
    assert stored is not None
    assert stored.status == STATUS_DEAD
    assert stored.attempts == 1, "a dead-lettered job must not consume further attempts"
    assert stored.last_error == "ValueError: boom"


async def test_fail_with_retry_schedules_backoff(adapter: MongoQueueAdapter) -> None:
    job_id = await _enqueue(adapter)
    job = await adapter.claim("worker-1")
    assert job is not None
    status = await adapter.fail(
        job.id, "worker-1", execution_version=job.execution_version, error="transient", retry=True
    )
    assert status == "retry_pending"
    stored = await adapter.get(job_id)
    assert stored is not None
    # First backoff step is 5 s (matches the production knowledge retry table).
    assert stored.run_at > utcnow() + timedelta(seconds=3)


async def test_retry_backoff_follows_the_configured_table(adapter: MongoQueueAdapter) -> None:
    # max_tries=5 so all three backoff steps are observable: on the default
    # budget the third failure dead-letters and never schedules a third delay.
    job_id = await _enqueue(adapter, max_tries=5)
    observed: list[float] = []
    for _ in range(3):
        job = await adapter.claim("worker-1")
        assert job is not None
        await adapter.fail(
            job.id, "worker-1", execution_version=job.execution_version, error="x", retry=True
        )
        stored = await adapter.get(job_id)
        assert stored is not None
        observed.append((stored.run_at - utcnow()).total_seconds())
        await adapter.queue.collection.update_one(
            {"_id": job_id}, {"$set": {"run_at": utcnow() - timedelta(seconds=1)}}
        )
    # 5, 30, 180 - the sequence Phase 15 measured.
    assert [round(v) for v in observed] == [5, 30, 180]


async def test_retry_dead_letters_when_the_budget_is_spent(adapter: MongoQueueAdapter) -> None:
    job_id = await _enqueue(adapter)
    for expected in (1, 2, 3):
        job = await adapter.claim("worker-1")
        assert job is not None
        assert job.job_try == expected
        await adapter.fail(
            job.id, "worker-1", execution_version=job.execution_version, error="x", retry=True
        )
        await adapter.queue.collection.update_one(
            {"_id": job_id}, {"$set": {"run_at": utcnow() - timedelta(seconds=1)}}
        )
    stored = await adapter.get(job_id)
    assert stored is not None
    assert stored.status == STATUS_DEAD
    assert await adapter.claim("worker-1") is None


async def test_fail_is_refused_for_a_fenced_worker_and_leaves_the_row_alone(
    adapter: MongoQueueAdapter,
) -> None:
    """The prototype bug this port fixed: a fenced worker must not dead-letter.

    The prototype read the job unconditionally and then wrote on ``_id`` alone,
    so a worker that lost its lease between the read and the write could mark a
    live, reclaimed job dead. Here the read and the write share one fence.
    """
    job_id = await _enqueue(adapter)
    stale = await adapter.claim("worker-1")
    assert stale is not None
    await adapter.queue.collection.update_one(
        {"_id": job_id}, {"$set": {"lease_expires_at": utcnow() - timedelta(seconds=1)}}
    )
    fresh = await adapter.claim("worker-2")
    assert fresh is not None

    status = await adapter.fail(
        job_id,
        "worker-1",
        execution_version=stale.execution_version,
        error="stale worker died",
        retry=False,
    )
    assert status == "not_owned"
    stored = await adapter.get(job_id)
    assert stored is not None
    assert stored.status == STATUS_RUNNING, "the live worker's row must survive"
    assert stored.last_error is None


async def test_fail_reports_not_found_for_an_unknown_job(adapter: MongoQueueAdapter) -> None:
    assert await adapter.fail("nope", "worker-1", execution_version=1, error="x") == "not_found"


async def test_fail_is_refused_for_a_different_worker(adapter: MongoQueueAdapter) -> None:
    await _enqueue(adapter)
    job = await adapter.claim("worker-1")
    assert job is not None
    assert (
        await adapter.fail(
            job.id, "worker-2", execution_version=job.execution_version, error="x", retry=False
        )
        == "not_owned"
    )


# ----------------------------------------------------------------------
# crash recovery
# ----------------------------------------------------------------------


async def test_retire_expired_dead_letters_an_exhausted_lease(adapter: MongoQueueAdapter) -> None:
    """A crash on the final attempt would otherwise stick forever."""
    job_id = await _enqueue(adapter)
    for _ in range(3):
        job = await adapter.claim("worker-1")
        assert job is not None
        await adapter.queue.collection.update_one(
            {"_id": job.id}, {"$set": {"lease_expires_at": utcnow() - timedelta(seconds=1)}}
        )
    assert await adapter.claim("worker-1") is None
    assert await adapter.retire_expired() == 1
    stored = await adapter.get(job_id)
    assert stored is not None
    assert stored.status == STATUS_DEAD
    assert "lease expired" in (stored.last_error or "")


async def test_retire_expired_leaves_a_recoverable_lease_alone(
    adapter: MongoQueueAdapter,
) -> None:
    """Below the attempt budget the job must stay claimable, not be retired."""
    await _enqueue(adapter)
    job = await adapter.claim("worker-1")
    assert job is not None
    await adapter.queue.collection.update_one(
        {"_id": job.id}, {"$set": {"lease_expires_at": utcnow() - timedelta(seconds=1)}}
    )
    assert await adapter.retire_expired() == 0
    assert await adapter.claim("worker-2") is not None


async def test_retire_expired_is_idempotent(adapter: MongoQueueAdapter) -> None:
    assert await adapter.retire_expired() == 0
    assert await adapter.retire_expired() == 0


# ----------------------------------------------------------------------
# tenant scoping
# ----------------------------------------------------------------------


async def test_get_for_tenant_scopes_the_read(adapter: MongoQueueAdapter) -> None:
    job_id = await _enqueue(adapter, tenant_id="tenant-a")
    assert await adapter.get_for_tenant("tenant-a", job_id) is not None
    assert await adapter.get_for_tenant("tenant-b", job_id) is None


async def test_claim_returns_the_owner_tenant_not_a_payload_tenant(
    adapter: MongoQueueAdapter,
) -> None:
    """The queue row's tenant is the submission's, never what a payload asserts."""
    await _enqueue(
        adapter,
        function="send_email",
        payload={
            "to": "a@b.c",
            "subject": "s",
            "text": "t",
            "html": "<p>h</p>",
            "tenant_id": "tenant-evil",
        },
    )
    job = await adapter.claim("worker-1")
    assert job is not None
    assert job.tenant_id == _TENANT


# ----------------------------------------------------------------------
# dispatch plumbing + diagnostics
# ----------------------------------------------------------------------


async def test_job_args_returns_positional_args(adapter: MongoQueueAdapter) -> None:
    await _enqueue(adapter)
    job = await adapter.claim("worker-1")
    assert job is not None
    assert await adapter.job_args(job) == ("d1", None)


async def test_list_jobs_filters_by_status(adapter: MongoQueueAdapter) -> None:
    await _enqueue(adapter, dedup_key="a")
    await _enqueue(adapter, dedup_key="b")
    job = await adapter.claim("worker-1")
    assert job is not None
    await adapter.complete(job.id, "worker-1", execution_version=job.execution_version)
    assert await adapter.count_documents() == 2
    assert await adapter.count_documents("completed") == 1
    assert len(await adapter.list_jobs("completed")) == 1
    assert len(await adapter.list_jobs("pending")) == 1


async def test_claim_does_not_mutate_the_stored_payload(adapter: MongoQueueAdapter) -> None:
    payload = {"document_id": "d1", "run_id": None}
    job_id = await _enqueue(adapter, payload=payload)
    job = await adapter.claim("worker-1")
    assert job is not None
    job.payload["document_id"] = "tampered"
    stored = await adapter.get(job_id)
    assert stored is not None
    assert stored.payload == {"document_id": "d1", "run_id": None}
