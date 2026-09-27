"""Basic lifecycle tests: enqueue, claim, delayed, completion, retry, dead-
letter, lease renewal, tenant hand-off, result storage."""

from __future__ import annotations

from datetime import timedelta

from backend.prototypes.mongo_queue import (
    STATUS_COMPLETED,
    STATUS_DEAD,
    STATUS_PENDING,
    STATUS_RETRY_PENDING,
    STATUS_RUNNING,
    MongoQueue,
)
from backend.prototypes.mongo_queue.config import QueueConfig
from backend.prototypes.mongo_queue.ids import utcnow
from backend.prototypes.mongo_queue.models import Job
from backend.prototypes.mongo_queue.sim_jobs import MockMailProvider, send_email_handler


def _assert_not_none(job: Job | None) -> Job:
    assert job is not None
    return job


async def test_enqueue_creates_a_pending_job(queue: MongoQueue) -> None:
    job_id = await queue.enqueue(
        function="send_email",
        payload={"to": "x@example.com"},
        tenant_id="tenant-a",
    )
    job = await queue.get(job_id)
    assert job is not None
    assert job.id == job_id
    assert job.function == "send_email"
    assert job.status == STATUS_PENDING
    assert job.attempts == 0
    assert job.execution_version == 0
    assert job.max_tries == 3
    assert job.tenant_id == "tenant-a"
    assert job.locked_by is None
    assert job.dedup_key is None


async def test_claim_marks_running_and_increments_attempts(queue: MongoQueue) -> None:
    job_id = await queue.enqueue(function="job", payload={}, tenant_id="t")
    claimed = await queue.claim("worker-a")
    assert claimed is not None
    assert claimed.id == job_id
    assert claimed.status == STATUS_RUNNING
    assert claimed.locked_by == "worker-a"
    assert claimed.attempts == 1
    assert claimed.execution_version == 1
    assert claimed.started_at is not None
    # Second claim sees no eligible job (single claim).
    assert await queue.claim("worker-b") is None


async def test_delayed_job_not_claimable_early_then_claimable(queue: MongoQueue) -> None:
    base = utcnow()
    job_id = await queue.enqueue(
        function="job", payload={}, tenant_id="t", run_at=base + timedelta(seconds=60)
    )
    assert await queue.claim("w", now=base) is None
    assert await queue.claim("w", now=base + timedelta(seconds=59)) is None
    claimed = await queue.claim("w", now=base + timedelta(seconds=61))
    assert claimed is not None and claimed.id == job_id


async def test_completion_requires_ownership(queue: MongoQueue) -> None:
    job_id = await queue.enqueue(function="job", payload={}, tenant_id="t")
    claimed = _assert_not_none(await queue.claim("worker-a"))
    # A different worker cannot complete it.
    assert (
        await queue.complete_job(job_id, "worker-b", execution_version=claimed.execution_version)
        is False
    )
    # The owner with the correct fencing token can.
    assert (
        await queue.complete_job(job_id, "worker-a", execution_version=claimed.execution_version)
        is True
    )
    job = await queue.get(job_id)
    assert job is not None and job.status == STATUS_COMPLETED
    assert job.finished_at is not None
    assert job.lease_expires_at is None


async def test_stale_worker_completion_rejected_by_fencing_token(queue: MongoQueue) -> None:
    """§16 §20: after a reclaim, the old execution_version no longer works."""
    base = utcnow()
    job_id = await queue.enqueue(function="job", payload={}, tenant_id="t", now=base)
    first = _assert_not_none(await queue.claim("worker-a", now=base))
    # worker-a's lease expires; worker-b reclaims the same job.
    reclaimed = _assert_not_none(
        await queue.claim("worker-b", now=base + timedelta(seconds=queue.lease_seconds + 1))
    )
    assert reclaimed.execution_version == first.execution_version + 1
    assert reclaimed.attempts == 2
    # Worker-a (stale) cannot complete OR fail the new execution.
    assert (
        await queue.complete_job(job_id, "worker-a", execution_version=first.execution_version)
        is False
    )
    assert (
        await queue.fail_job(job_id, "worker-a", "late", execution_version=first.execution_version)
        == "not_owned"
    )
    # Worker-b owns it now and completes.
    assert (
        await queue.complete_job(job_id, "worker-b", execution_version=reclaimed.execution_version)
        is True
    )


async def test_weak_completion_path_without_fencing_is_possible(queue: MongoQueue) -> None:
    """Documents the API: passing ``execution_version=None`` weakens fencing.

    The prototype worker always passes the version; the weak path exists only
    for experiments and MUST NOT be used in a production port.
    """
    job_id = await queue.enqueue(function="job", payload={}, tenant_id="t")
    await queue.claim("worker-a")
    assert await queue.complete_job(job_id, "worker-a", execution_version=None) is True


async def test_failure_schedules_retry_with_backoff(queue: MongoQueue) -> None:
    base = utcnow()
    job_id = await queue.enqueue(function="job", payload={}, tenant_id="t", now=base)
    claimed = _assert_not_none(await queue.claim("w", now=base))
    result = await queue.fail_job(
        job_id, "w", "boom", execution_version=claimed.execution_version, now=base
    )
    assert result == STATUS_RETRY_PENDING
    job = await queue.get(job_id)
    assert job is not None and job.status == STATUS_RETRY_PENDING
    assert job.last_error == "boom"
    # Mongo stores datetimes at millisecond precision; tolerate sub-ms drift.
    assert abs((job.run_at - (base + timedelta(seconds=5))).total_seconds()) < 0.01
    # Not claimable until backoff elapses.
    assert await queue.claim("w", now=base + timedelta(seconds=4)) is None
    again = _assert_not_none(await queue.claim("w", now=base + timedelta(seconds=6)))
    assert again.attempts == 2


async def test_failure_exhausts_max_tries_to_dead(queue: MongoQueue) -> None:
    base = utcnow()
    job_id = await queue.enqueue(function="flaky", payload={}, tenant_id="t", now=base)
    for attempt in (1, 2, 3):
        claimed = await queue.claim("w", now=base)
        assert claimed is not None and claimed.attempts == attempt
        outcome = await queue.fail_job(
            job_id, "w", f"fail-{attempt}", execution_version=claimed.execution_version, now=base
        )
        if attempt < 3:
            assert outcome == STATUS_RETRY_PENDING
            base = base + timedelta(seconds=600)  # advance past the backoff
        else:
            assert outcome == STATUS_DEAD
    job = await queue.get(job_id)
    assert job is not None and job.status == STATUS_DEAD
    assert job.last_error == "fail-3"


async def test_dead_job_never_claimed_again(queue: MongoQueue) -> None:
    base = utcnow()
    job_id = await queue.enqueue(function="flaky", payload={}, tenant_id="t", now=base)
    for _ in range(3):
        claimed = await queue.claim("w", now=base)
        assert claimed is not None
        await queue.fail_job(
            job_id, "w", "x", execution_version=claimed.execution_version, now=base
        )
        base = base + timedelta(seconds=600)
    assert await queue.claim("w", now=base + timedelta(days=1)) is None


async def test_retry_false_dead_letters_on_first_failure(queue: MongoQueue) -> None:
    """Phase 17A retry parity: ``retry=False`` must dead-letter immediately.

    ARQ 0.28 dead-letters an ordinary (non-Retry / non-CancelledError)
    exception on the first attempt; the Mongo adapter maps that to
    ``fail_job(retry=False)`` so the two backends have identical semantics.
    With retries available (attempts < max_tries) the same failure would
    normally schedule a backoff instead.
    """
    base = utcnow()
    job_id = await queue.enqueue(function="boom", payload={}, tenant_id="t", now=base)
    claimed = _assert_not_none(await queue.claim("w", now=base))
    outcome = await queue.fail_job(
        job_id,
        "w",
        "ordinary failure",
        execution_version=claimed.execution_version,
        retry=False,
        now=base,
    )
    assert outcome == STATUS_DEAD
    job = await queue.get(job_id)
    assert job is not None and job.status == STATUS_DEAD
    assert job.last_error == "ordinary failure"
    # Even after the backoff window the job can never be claimed again.
    assert await queue.claim("w", now=base + timedelta(days=1)) is None


async def test_lease_renewal_enforces_ownership(queue: MongoQueue) -> None:
    base = utcnow()
    job_id = await queue.enqueue(function="job", payload={}, tenant_id="t", now=base)
    await queue.claim("worker-a", now=base)
    # Owner renews: OK.
    assert await queue.renew_lease(job_id, "worker-a", now=base + timedelta(seconds=60)) is True
    # Non-owner renews: refused.
    assert await queue.renew_lease(job_id, "worker-b", now=base + timedelta(seconds=60)) is False
    # Renewing an expired-or-unknown lease: refused.
    assert await queue.renew_lease("no-such-job", "worker-a", now=base) is False


async def test_tenant_id_attached_and_scoped_reads(queue: MongoQueue) -> None:
    job_id = await queue.enqueue(function="job", payload={}, tenant_id="tenant-a")
    claimed = await queue.claim("w")
    assert claimed is not None and claimed.tenant_id == "tenant-a"
    # Tenant-scoped read: cross-tenant lookup returns nothing (no leakage).
    assert await queue.find_for_tenant("tenant-b", job_id) is None
    assert await queue.find_for_tenant("tenant-a", job_id) is not None


async def test_result_stored_and_oversize_result_guarded(queue: MongoQueue) -> None:
    job_id = await queue.enqueue(function="job", payload={}, tenant_id="t")
    claimed = await queue.claim("w")
    assert claimed is not None
    await queue.complete_job(
        job_id, "w", execution_version=claimed.execution_version, result={"ok": 42}
    )
    finished = await queue.get(job_id)
    assert finished is not None and finished.result == {"ok": 42}

    job_id2 = await queue.enqueue(function="job", payload={}, tenant_id="t")
    claimed2 = await queue.claim("w")
    assert claimed2 is not None
    huge = {"blob": "x" * 100_000}
    await queue.complete_job(
        job_id2, "w", execution_version=claimed2.execution_version, result=huge
    )
    finished2 = await queue.get(job_id2)
    assert finished2 is not None and finished2.result["__truncated__"] is True


async def test_worker_executes_registered_handler_and_completes(queue: MongoQueue) -> None:
    from backend.prototypes.mongo_queue.worker import PrototypeWorker

    provider = MockMailProvider()
    worker = PrototypeWorker(
        queue,
        QueueConfig(),
        worker_id="worker-a",
        handlers={
            "send_email": lambda p, ctx: send_email_handler(p, ctx, provider=provider),
        },
    )
    job_id = await queue.enqueue(
        function="send_email",
        payload={"to": "a@b.c", "subject": "s", "body": "b"},
        tenant_id="tenant-a",
    )
    outcome = await worker.work_once()
    assert outcome is not None and outcome.status == STATUS_COMPLETED
    assert provider.sent_count == 1
    job = await queue.get(job_id)
    assert job is not None and job.status == STATUS_COMPLETED
