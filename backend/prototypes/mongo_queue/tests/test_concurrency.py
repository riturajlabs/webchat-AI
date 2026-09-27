"""Concurrency tests: 100 claim races, concurrent dedup, lease reclaim,
execution-version fencing, and the honest dual-execution risk demonstration."""

from __future__ import annotations

import asyncio
from datetime import timedelta

from backend.prototypes.mongo_queue import (
    STATUS_DEAD,
    MongoQueue,
)
from backend.prototypes.mongo_queue.ids import utcnow
from backend.prototypes.mongo_queue.models import Job
from backend.prototypes.mongo_queue.sim_jobs import CrawlFence, crawl_handler
from backend.prototypes.mongo_queue.worker import JobContext

WORKERS = ("worker-a", "worker-b", "worker-c", "worker-d")


def _ctx(job: Job, worker: str, tenant: str) -> JobContext:
    return JobContext(
        job_id=job.id,
        function=job.function,
        tenant_id=tenant,
        worker_id=worker,
        job_try=job.attempts,
        execution_version=job.execution_version,
        claimed_at=job.started_at or utcnow(),
    )


async def test_atomic_claim_single_winner_across_100_races(queue: MongoQueue) -> None:
    """§10: concurrent claims race; exactly ONE obtains the lease per job.

    Run 100 separate races with 4 workers each; zero duplicate claims
    expected. No sleeps: purely event-loop + server-level atomicity.
    """
    duplicates = 0
    for _race in range(100):
        await queue.delete_all()
        job_id = await queue.enqueue(function="race", payload={}, tenant_id="t-race")
        results = await asyncio.gather(*(queue.claim(worker) for worker in WORKERS))
        winners = [claim for claim in results if claim is not None]
        assert len(winners) == 1, f"race produced {len(winners)} winners"
        assert winners[0].id == job_id
        duplicates += len(winners) - 1
    assert duplicates == 0


async def test_atomic_claim_100_concurrent_workers_single_winner(
    queue: MongoQueue,
) -> None:
    """§10 literal: ONE job, ONE hundred workers racing claim -> one winner."""
    await queue.delete_all()
    job_id = await queue.enqueue(function="race", payload={}, tenant_id="t-race")
    results = await asyncio.gather(*(queue.claim(f"w{i:03d}") for i in range(100)))
    claimants = [claim for claim in results if claim is not None]
    assert len(claimants) == 1
    assert claimants[0].id == job_id


async def test_concurrent_dedup_enqueue_collapses_to_one_job(queue: MongoQueue) -> None:
    """§13: 100 racing submissions with the same dedup_key -> one job."""
    submissions = await asyncio.gather(
        *(
            queue.enqueue(
                function="crawl",
                payload={"site": "x"},
                tenant_id="t",
                dedup_key="crawl:abc123",
            )
            for _ in range(100)
        )
    )
    assert len(set(submissions)) == 1
    assert await queue.count_documents() == 1
    job = await queue.get(submissions[0])
    assert job is not None and job.function == "crawl"


async def test_distinct_dedup_keys_create_distinct_jobs(queue: MongoQueue) -> None:
    a = await queue.enqueue(function="crawl", payload={}, tenant_id="t", dedup_key="k-a")
    b = await queue.enqueue(function="crawl", payload={}, tenant_id="t", dedup_key="k-b")
    assert a != b
    assert await queue.count_documents() == 2


async def test_lease_expired_running_job_is_reclaimable(queue: MongoQueue) -> None:
    """§9 §16: worker-a stops without completing; after lease expiry worker-b
    reclaims, attempts increment correctly, and stale completion fails."""
    base = utcnow()
    job_id = await queue.enqueue(function="job", payload={}, tenant_id="t", now=base)
    first = await queue.claim("worker-a", now=base)
    assert first is not None and first.attempts == 1
    # Still owned: not claimable while lease is live.
    assert await queue.claim("worker-b", now=base + timedelta(seconds=30)) is None
    # Lease expired: reclaimable.
    reclaimed = await queue.claim(
        "worker-b", now=base + timedelta(seconds=queue.lease_seconds + 1)
    )
    assert reclaimed is not None
    assert reclaimed.attempts == 2
    assert reclaimed.execution_version == 2
    assert reclaimed.locked_by == "worker-b"
    # Worker-a's stale completion is refused by both ownership and fencing.
    assert (
        await queue.complete_job(job_id, "worker-a", execution_version=first.execution_version)
        is False
    )
    # Worker-b completes.
    assert (
        await queue.complete_job(job_id, "worker-b", execution_version=reclaimed.execution_version)
        is True
    )


async def test_execution_version_fencing_demonstration(queue: MongoQueue) -> None:
    """§20: each claim bumps execution_version; the version is the fencing
    token that keeps an old execution from mutating the current one."""
    base = utcnow()
    job_id = await queue.enqueue(function="job", payload={}, tenant_id="t", now=base)
    v1 = await queue.claim("worker-a", now=base)
    assert v1 is not None and v1.execution_version == 1
    # worker-a dies; lease expires; worker-b claims -> version 2.
    v2 = await queue.claim(
        "worker-b", now=base + timedelta(seconds=queue.lease_seconds + 1)
    )
    assert v2 is not None and v2.execution_version == 2
    # worker-a tries to fail the execution it *thinks* it still owns.
    outcome = await queue.fail_job(
        job_id, "worker-a", "late", execution_version=v1.execution_version
    )
    assert outcome == "not_owned"
    # worker-b finishes cleanly.
    assert (
        await queue.complete_job(job_id, "worker-b", execution_version=v2.execution_version)
        is True
    )


async def test_dual_execution_residual_risk_highlighted(queue: MongoQueue) -> None:
    """§20 (honest demonstration): lease expiry can produce TWO concurrent
    executions of the same job. The queue cannot prevent BOTH running; it can
    only fence the terminal write. Side-effect idempotency is the real cure.

    Scenario: worker-a owns the job and is still alive but slow. Its lease
    expires. worker-b reclaims the same job while worker-a then continues
    executing. Both call the handler; the terminal write is single.
    """
    base = utcnow()
    job_id = await queue.enqueue(
        function="crawl", payload={"crawl_job_id": "c1"}, tenant_id="t", now=base
    )
    fence = CrawlFence()
    await fence.mark_active("c1")

    v_a = await queue.claim("worker-a", now=base)
    assert v_a is not None
    await fence.crawl_side_effect("c1", "home")  # worker-a partial work

    v_b = await queue.claim(
        "worker-b", now=base + timedelta(seconds=queue.lease_seconds + 10)
    )
    assert v_b is not None
    result_b = await crawl_handler({"crawl_job_id": "c1"}, _ctx(v_b, "worker-b", "t"), fence=fence)
    # worker-a resumes and ALSO runs the handler (dual execution, real risk).
    result_a = await crawl_handler({"crawl_job_id": "c1"}, _ctx(v_a, "worker-a", "t"), fence=fence)

    assert {result_b["winner"], result_a["winner"]} == {True, False}
    assert fence.is_active("c1") is False

    # The loser's queue-level completion is refused by fencing.
    assert (
        await queue.complete_job(job_id, "worker-a", execution_version=v_a.execution_version)
        is False
    )
    winner_worker = "worker-b" if result_b["winner"] else "worker-a"
    winner_version = v_b.execution_version if result_b["winner"] else v_a.execution_version
    assert await queue.complete_job(job_id, winner_worker, execution_version=winner_version) is True

    # Both executions produced partial side-effect work (the honest cost):
    # worker-a's pre-stall page, worker-b's run, worker-a's resumed run.
    assert len([e for e in fence.events if e.endswith(":home")]) == 3


async def test_retire_expired_flags_exhausted_stuck_running(queue: MongoQueue) -> None:
    """§12: a job that crashed on its FINAL attempt (running + attempts ==
    max_tries + lease expired) can never be claimed; retire marks it dead."""
    base = utcnow()
    job_id = await queue.enqueue(function="flaky", payload={}, tenant_id="t", now=base)
    for _ in range(3):
        claimed = await queue.claim("w", now=base)
        assert claimed is not None
        base = base + timedelta(seconds=600)  # expire lease between claims
    stuck = await queue.get(job_id)
    assert stuck is not None and stuck.status == "running" and stuck.attempts == 3
    assert await queue.claim("w", now=base + timedelta(days=1)) is None
    retired = await queue.retire_expired(now=base + timedelta(days=1))
    assert retired == 1
    after = await queue.get(job_id)
    assert after is not None and after.status == STATUS_DEAD