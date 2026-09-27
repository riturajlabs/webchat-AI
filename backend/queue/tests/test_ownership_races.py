"""Queue ownership and lease races (Phase 17B), 100 iterations each.

A Mongo queue migration is only safe if a worker that has lost its lease can
never terminate or extend the execution that replaced it. This suite drives the
real :class:`MongoQueueAdapter` on the isolated prototype mongod and counts
exactly what the brief requires:

    stale completion successes : 0
    stale failure successes    : 0
    stale heartbeat successes  : 0

Determinism (§13): the store accepts an injected ``now`` on every operation, so
lease expiry and boundary conditions are driven by an explicit clock rather than
by sleeping and hoping. No test here depends on scheduling luck, and none of
them wait on wall-clock time to reach a race.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from backend.prototypes.mongo_queue.config import DEFAULT_MONGO_URI
from backend.queue.mongo_adapter import MongoQueueAdapter
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

ITERATIONS = 100
LEASE = 30.0
T0 = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
async def queue() -> AsyncIterator[MongoQueueAdapter]:
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        DEFAULT_MONGO_URI, serverSelectionTimeoutMS=3000, tz_aware=True
    )
    try:
        await client.admin.command("ping")
    except Exception as exc:  # noqa: BLE001 - environment guard
        client.close()
        pytest.skip(f"isolated prototype mongod unreachable: {exc}")
    db: AsyncIOMotorDatabase[dict[str, Any]] = client["webchat_ai_queue_test_ownership"]
    adapter = MongoQueueAdapter(
        db,
        collection_name="worker_jobs",
        lease_seconds=LEASE,
        heartbeat_seconds=5.0,
        max_tries=3,
    )
    await adapter.ensure_indexes()
    yield adapter
    for name in await db.list_collection_names():
        await db.drop_collection(name)
    client.close()


async def _one_race(queue: MongoQueueAdapter, index: int, *, winner: str) -> dict[str, int]:
    """One full ownership race, driven by an explicit clock.

    ``winner`` selects whether the current owner B terminates by completing or
    by failing, so both terminal paths are exercised across the iterations.
    """
    store = queue.queue
    base = T0 + timedelta(seconds=index * 3600)  # disjoint time window per race
    job_id = await queue.enqueue(
        "process_document",
        payload={"document_id": f"doc-{index}", "run_id": None},
        tenant_id="tenant-race",
        now=base,
    )

    # A claims at t0 and holds execution_version N.
    attempt_a = await store.claim("worker-A", now=base)
    assert attempt_a is not None
    version_a = attempt_a.execution_version

    # A's lease expires; B reclaims. The version advances - this is the fence.
    after_expiry = base + timedelta(seconds=LEASE + 1)
    attempt_b = await store.claim("worker-B", now=after_expiry)
    assert attempt_b is not None
    assert attempt_b.execution_version == version_a + 1

    stale_completion = 0
    stale_failure = 0
    stale_heartbeat = 0

    # Every stale operation A can now attempt, all at the same instant.
    if await store.complete_job(job_id, "worker-A", execution_version=version_a, now=after_expiry):
        stale_completion += 1
    if (
        await store.fail_job(
            job_id, "worker-A", "boom", execution_version=version_a, retry=False, now=after_expiry
        )
        != "not_owned"
    ):
        stale_failure += 1
    if await store.renew_lease(job_id, "worker-A", now=after_expiry):
        stale_heartbeat += 1

    # The current owner still holds every right.
    assert await store.renew_lease(job_id, "worker-B", now=after_expiry) is True
    if winner == "complete":
        assert await store.complete_job(
            job_id, "worker-B", execution_version=attempt_b.execution_version, now=after_expiry
        )
    else:
        status = await store.fail_job(
            job_id,
            "worker-B",
            "boom",
            execution_version=attempt_b.execution_version,
            retry=False,
            now=after_expiry,
        )
        assert status == "dead"

    row = await store.get(job_id)
    assert row is not None
    assert row.locked_by == "worker-B"
    return {
        "stale_completion": stale_completion,
        "stale_failure": stale_failure,
        "stale_heartbeat": stale_heartbeat,
    }


@pytest.mark.parametrize("winner", ["complete", "fail"])
async def test_a_stale_owner_can_never_terminate_or_extend_a_reclaimed_job(
    queue: MongoQueueAdapter, winner: str
) -> None:
    """§12: 100 iterations, both terminal outcomes, required result 0/0/0."""
    totals = {"stale_completion": 0, "stale_failure": 0, "stale_heartbeat": 0}
    for index in range(ITERATIONS):
        outcome = await _one_race(queue, index, winner=winner)
        for key, value in outcome.items():
            totals[key] += value

    assert totals == {"stale_completion": 0, "stale_failure": 0, "stale_heartbeat": 0}, totals


async def test_a_stale_owner_cannot_win_with_a_reused_version_number(
    queue: MongoQueueAdapter,
) -> None:
    """Version fencing is on the exact value, not merely 'newer'.

    Replaying A's *own* version must fail even when nothing else changed, so a
    buggy caller that recomputes or caches the version cannot slip through.
    """
    store = queue.queue
    job_id = await queue.enqueue(
        "process_document", payload={"document_id": "d", "run_id": None}, tenant_id="t", now=T0
    )
    attempt_a = await store.claim("worker-A", now=T0)
    assert attempt_a is not None

    # A completes legitimately; a second attempt with the same version is refused.
    assert await store.complete_job(
        job_id, "worker-A", execution_version=attempt_a.execution_version, now=T0
    )
    assert not await store.complete_job(
        job_id, "worker-A", execution_version=attempt_a.execution_version, now=T0
    )


async def test_ownership_requires_both_the_worker_and_the_version(
    queue: MongoQueueAdapter,
) -> None:
    """Right version but wrong worker, and right worker but wrong version, fail."""
    store = queue.queue
    job_id = await queue.enqueue(
        "process_document", payload={"document_id": "d", "run_id": None}, tenant_id="t", now=T0
    )
    attempt = await store.claim("worker-A", now=T0)
    assert attempt is not None

    assert not await store.complete_job(
        job_id, "worker-B", execution_version=attempt.execution_version, now=T0
    )
    assert not await store.complete_job(
        job_id, "worker-A", execution_version=attempt.execution_version + 7, now=T0
    )
    assert not await store.renew_lease(job_id, "worker-B", now=T0)
    # And the genuine owner is still fine.
    assert await store.complete_job(
        job_id, "worker-A", execution_version=attempt.execution_version, now=T0
    )


# ----------------------------------------------------------------------
# §13 Heartbeat / reclaim races, on an explicit clock
# ----------------------------------------------------------------------


async def test_a_heartbeat_just_before_expiry_keeps_the_lease(queue: MongoQueueAdapter) -> None:
    """Heartbeat with 1 s of lease left succeeds and extends the lease."""
    store = queue.queue
    await queue.enqueue(
        "process_document", payload={"document_id": "d", "run_id": None}, tenant_id="t", now=T0
    )
    attempt = await store.claim("worker-A", now=T0)
    assert attempt is not None

    just_before = T0 + timedelta(seconds=LEASE - 1)
    assert await store.renew_lease("PLACEHOLDER", "worker-A", now=just_before) is False
    row_id = (await store.list_jobs(limit=1))[0].id
    assert await store.renew_lease(row_id, "worker-A", now=just_before) is True

    # The extension moved the deadline, so the original expiry no longer frees it.
    assert await store.claim("worker-B", now=T0 + timedelta(seconds=LEASE + 1)) is None
    assert await store.claim("worker-B", now=T0 + timedelta(seconds=LEASE + 30)) is not None


async def test_a_heartbeat_at_the_expiry_boundary_is_refused(queue: MongoQueueAdapter) -> None:
    """At exactly ``lease_expires_at`` the lease is over: heartbeat is refused."""
    store = queue.queue
    await queue.enqueue(
        "process_document", payload={"document_id": "d", "run_id": None}, tenant_id="t", now=T0
    )
    attempt = await store.claim("worker-A", now=T0)
    assert attempt is not None
    job_id = attempt.id

    boundary = T0 + timedelta(seconds=LEASE)
    assert await store.renew_lease(job_id, "worker-A", now=boundary) is False
    # One microsecond earlier it would have been legal - the boundary is exact.
    assert (
        await store.renew_lease(job_id, "worker-A", now=boundary - timedelta(microseconds=1))
        is True
    )


async def test_a_heartbeat_after_a_reclaim_is_refused(queue: MongoQueueAdapter) -> None:
    """Once B owns the execution, A's heartbeat cannot extend anything."""
    store = queue.queue
    await queue.enqueue(
        "process_document", payload={"document_id": "d", "run_id": None}, tenant_id="t", now=T0
    )
    attempt_a = await store.claim("worker-A", now=T0)
    assert attempt_a is not None

    after = T0 + timedelta(seconds=LEASE + 1)
    attempt_b = await store.claim("worker-B", now=after)
    assert attempt_b is not None

    assert await store.renew_lease(attempt_a.id, "worker-A", now=after) is False
    assert await store.renew_lease(attempt_b.id, "worker-B", now=after) is True


async def test_completion_racing_a_heartbeat_has_one_winner(queue: MongoQueueAdapter) -> None:
    """Heartbeat and completion from the owner: completion wins, then heartbeat fails."""
    store = queue.queue
    await queue.enqueue(
        "process_document", payload={"document_id": "d", "run_id": None}, tenant_id="t", now=T0
    )
    attempt = await store.claim("worker-A", now=T0)
    assert attempt is not None

    assert await store.complete_job(
        attempt.id, "worker-A", execution_version=attempt.execution_version, now=T0
    )
    # The job is terminal; no lease exists to extend.
    assert await store.renew_lease(attempt.id, "worker-A", now=T0) is False


async def test_failure_racing_a_heartbeat_has_one_winner(queue: MongoQueueAdapter) -> None:
    store = queue.queue
    await queue.enqueue(
        "process_document", payload={"document_id": "d", "run_id": None}, tenant_id="t", now=T0
    )
    attempt = await store.claim("worker-A", now=T0)
    assert attempt is not None

    status = await store.fail_job(
        attempt.id,
        "worker-A",
        "boom",
        execution_version=attempt.execution_version,
        retry=False,
        now=T0,
    )
    assert status == "dead"
    assert await store.renew_lease(attempt.id, "worker-A", now=T0) is False


async def test_a_reclaim_racing_a_heartbeat_never_double_claims(
    queue: MongoQueueAdapter,
) -> None:
    """§13: reclaim vs heartbeat - exactly one worker owns the execution.

    Run under ``asyncio.gather`` so the two operations genuinely interleave at
    the database, then assert the invariant rather than the interleaving.
    """
    import asyncio

    store = queue.queue
    for index in range(25):
        await queue.enqueue(
            "process_document",
            payload={"document_id": f"d{index}", "run_id": None},
            tenant_id="t",
            now=T0,
        )

    expiry = T0 + timedelta(seconds=LEASE + 1)

    async def renew() -> int:
        count = 0
        for job in await store.list_jobs(limit=100):
            if await store.renew_lease(job.id, "worker-A", now=T0):
                count += 1
        return count

    # B tries to reclaim everything at the instant the lease has expired, while
    # A concurrently tries to extend. Exactly one side may win each job.
    async def reclaim() -> int:
        count = 0
        while True:
            job = await store.claim("worker-B", now=expiry)
            if job is None:
                return count
            count += 1

    reclaimed, _ = await asyncio.gather(reclaim(), renew())
    assert reclaimed == 25, "a job escaped both claim and reclaim accounting"
    rows = await store.list_jobs(limit=100)
    # Exactly one owner per job, and A's concurrent renewals changed nothing:
    # A never held a lease, so every one of its 25 renewal attempts failed and
    # B's single claim is the only version bump.
    assert all(row.locked_by == "worker-B" for row in rows)
    assert all(row.execution_version == 1 for row in rows)
    assert all(row.attempts == 1 for row in rows), "a job was claimed twice"


async def test_a_stolen_lease_cannot_be_completed_even_with_the_right_version(
    queue: MongoQueueAdapter,
) -> None:
    """The owner filter requires the version AND the current lock holder."""
    store = queue.queue
    await queue.enqueue(
        "process_document", payload={"document_id": "d", "run_id": None}, tenant_id="t", now=T0
    )
    attempt_a = await store.claim("worker-A", now=T0)
    assert attempt_a is not None
    attempt_b = await store.claim("worker-B", now=T0 + timedelta(seconds=LEASE + 1))
    assert attempt_b is not None

    # A replays B's version but keeps its own identity: still refused.
    assert not await store.complete_job(
        attempt_a.id, "worker-A", execution_version=attempt_b.execution_version, now=T0
    )
    # B replays A's version with B's identity: still refused.
    assert not await store.complete_job(
        attempt_b.id, "worker-B", execution_version=attempt_a.execution_version, now=T0
    )
    assert await store.complete_job(
        attempt_b.id, "worker-B", execution_version=attempt_b.execution_version, now=T0
    )


async def test_retire_expired_does_not_touch_a_live_lease(queue: MongoQueueAdapter) -> None:
    """``retire_expired`` (the ops sweep) must respect a live lease."""
    store = queue.queue
    await queue.enqueue(
        "process_document", payload={"document_id": "d", "run_id": None}, tenant_id="t", now=T0
    )
    attempt = await store.claim("worker-A", now=T0)
    assert attempt is not None

    # Sweeping at the claim instant must not retire anything.
    assert await store.retire_expired(now=T0) == 0
    row = await store.get(attempt.id)
    assert row is not None and row.status == "running"


# ----------------------------------------------------------------------
# §12 the identity-only heartbeat hole
# ----------------------------------------------------------------------


async def test_a_stale_execution_cannot_renew_after_a_same_worker_reclaim(
    queue: MongoQueueAdapter,
) -> None:
    """A worker that reclaims its OWN expired job fences out its stale execution.

    This is the case identity alone cannot catch. ``locked_by`` is unchanged -
    it is the same worker id before and after the reclaim - so a filter on
    identity alone would let the stale execution keep extending the *new*
    execution's lease. Since that stale execution can no longer complete (its
    version is stale), the job would sit with a live lease that no owner can
    ever finish: a permanent stall.

    The fencing token is what makes the renewal refuse.
    """
    store = queue.queue
    await queue.enqueue(
        "process_document", payload={"document_id": "d", "run_id": None}, tenant_id="t", now=T0
    )

    # Execution 1, by worker-A. The handler stalls past its lease.
    first = await store.claim("worker-A", now=T0)
    assert first is not None
    assert first.execution_version == 1

    # The same worker id reclaims the job: execution 2.
    after_expiry = T0 + timedelta(seconds=LEASE + 1)
    second = await store.claim("worker-A", now=after_expiry)
    assert second is not None
    assert second.execution_version == 2
    assert second.id == first.id

    # The stalled execution 1 wakes up and tries to extend its lease. It holds
    # the right worker id, so only the version can stop it.
    assert (
        await store.renew_lease(
            first.id, "worker-A", execution_version=first.execution_version, now=after_expiry
        )
        is False
    )

    # Execution 2, the real owner, renews fine and can still finish the job.
    assert (
        await store.renew_lease(
            second.id, "worker-A", execution_version=second.execution_version, now=after_expiry
        )
        is True
    )
    assert await store.complete_job(
        second.id, "worker-A", execution_version=second.execution_version, now=after_expiry
    )

    row = await store.get(second.id)
    assert row is not None and row.status == "completed"


async def test_a_stale_execution_cannot_extend_the_new_lease_forever(
    queue: MongoQueueAdapter,
) -> None:
    """The stall itself: 100 stale renewals must not push the deadline out.

    Without the version in the filter, each of these renewals would move
    ``lease_expires_at`` forward and the job could never be reclaimed again.
    """
    store = queue.queue
    await queue.enqueue(
        "process_document", payload={"document_id": "d", "run_id": None}, tenant_id="t", now=T0
    )
    first = await store.claim("worker-A", now=T0)
    assert first is not None

    after_expiry = T0 + timedelta(seconds=LEASE + 1)
    second = await store.claim("worker-A", now=after_expiry)
    assert second is not None

    row_before = await store.get(second.id)
    assert row_before is not None
    deadline_before = row_before.lease_expires_at
    assert deadline_before is not None

    # The stalled execution hammers the heartbeat, once per lease period.
    stale_renewals = 0
    for step in range(ITERATIONS):
        moment = after_expiry + timedelta(seconds=step * (LEASE + 1))
        if await store.renew_lease(
            first.id, "worker-A", execution_version=first.execution_version, now=moment
        ):
            stale_renewals += 1

    assert stale_renewals == 0, f"a stale execution renewed its lease {stale_renewals} time(s)"

    # The deadline never moved, so the job stays reclaimable.
    row_after = await store.get(second.id)
    assert row_after is not None
    deadline_after = row_after.lease_expires_at
    assert deadline_after == deadline_before
    # ...and it is in fact still reclaimable by a different worker.
    third = await store.claim("worker-B", now=deadline_after)
    assert third is not None
    assert third.execution_version == 3


async def test_concurrent_workers_never_claim_the_same_job_twice(
    queue: MongoQueueAdapter,
) -> None:
    """Duplicate ownership stays 0 under a real concurrent drain.

    The races above drive one deliberate loser per iteration. This one removes
    the orchestration entirely: 120 jobs, 8 workers all calling ``claim`` in a
    tight loop through ``asyncio.gather``, so the contention is whatever the
    event loop and the server produce. The assertion is the invariant, not the
    interleaving:

        duplicate claims : 0
        lost jobs        : 0

    Every job must be claimed exactly once, and the number of claims must equal
    the number of jobs. A claim that silently returns the same job to two
    workers is the failure this guards, so it is counted per worker rather than
    inferred from the total.
    """
    import asyncio

    jobs = ITERATIONS + 20
    workers = 8
    store = queue.queue
    for index in range(jobs):
        await queue.enqueue(
            "process_document",
            payload={"document_id": f"d{index}", "run_id": None},
            tenant_id="t",
            now=T0,
        )

    async def drain(worker_id: str) -> list[str]:
        taken: list[str] = []
        while True:
            job = await store.claim(worker_id, now=T0)
            if job is None:
                return taken
            taken.append(job.id)

    per_worker = await asyncio.gather(*(drain(f"worker-{i}") for i in range(workers)))
    claimed = [job_id for batch in per_worker for job_id in batch]

    assert len(claimed) == len(set(claimed)), "a job was claimed by more than one worker"
    assert len(claimed) == jobs, f"expected {jobs} claims, saw {len(claimed)}"

    # Every claim took a fresh execution version 1, so nothing was re-claimed.
    versions = [
        (await store.get(job_id)).execution_version  # type: ignore[union-attr]
        for job_id in claimed
    ]
    assert set(versions) == {1}, versions


async def test_a_reclaimed_job_bumps_execution_version_under_concurrency(
    queue: MongoQueueAdapter,
) -> None:
    """Reclaim must advance the fencing token every time, under contention.

    The version is what makes a stale write harmless, so a reclaim that reused a
    version would re-open the whole stale-owner hole. 20 jobs, 6 workers all
    trying to reclaim the same expired batch at the same instant: each job must
    end up with exactly one owner and a strictly increasing version per claim.
    """
    import asyncio

    jobs = 20
    store = queue.queue
    for index in range(jobs):
        await queue.enqueue(
            "process_document",
            payload={"document_id": f"d{index}", "run_id": None},
            tenant_id="t",
            now=T0,
        )
    expiry = T0 + timedelta(seconds=LEASE + 1)
    first_pass = [await store.claim(f"seed-{i}", now=T0) for i in range(jobs)]
    assert all(job is not None for job in first_pass)

    async def reclaim(worker_id: str) -> list[tuple[str, int]]:
        taken: list[tuple[str, int]] = []
        while True:
            job = await store.claim(worker_id, now=expiry)
            if job is None:
                return taken
            taken.append((job.id, job.execution_version))

    per_worker = await asyncio.gather(*(reclaim(f"worker-{i}") for i in range(6)))
    reclaimed = [item for batch in per_worker for item in batch]

    assert len({job_id for job_id, _ in reclaimed}) == len(reclaimed), "double reclaim"
    assert len(reclaimed) == jobs
    # Seed claims took version 1, so every reclaim must land on version 2.
    assert {version for _, version in reclaimed} == {2}, sorted({v for _, v in reclaimed})
