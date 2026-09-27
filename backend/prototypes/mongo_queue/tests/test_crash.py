"""Worker crash-point matrix (§19).

Simulates process termination at six defined points and records, for each:
expected state, recovery behaviour, duplicate risk, and whether extra
side-effect idempotency is required. All side effects are MOCK (email).
"""

from __future__ import annotations

from datetime import timedelta

from backend.prototypes.mongo_queue import (
    STATUS_COMPLETED,
    STATUS_DEAD,
    STATUS_PENDING,
    STATUS_RUNNING,
    MongoQueue,
)
from backend.prototypes.mongo_queue.ids import utcnow
from backend.prototypes.mongo_queue.models import Job
from backend.prototypes.mongo_queue.sim_jobs import MockMailProvider, send_email_handler
from backend.prototypes.mongo_queue.worker import JobContext

PAYLOAD = {"to": "u@mail.dev", "subject": "s", "body": "b", "idempotency_key": None}


def _ctx(job: Job, worker: str) -> JobContext:
    return JobContext(
        job_id=job.id,
        function="send_email",
        tenant_id="tenant-a",
        worker_id=worker,
        job_try=job.attempts,
        execution_version=job.execution_version,
        claimed_at=job.started_at or utcnow(),
    )


# crash point -> (physical state reached, duplicate side-effect risk on recovery)
CRASH_TABLE: dict[str, tuple[str, bool]] = {
    "A. before claim": ("never_claimed", False),
    "B. after claim": ("claimed_no_effect", False),
    "C. during execution": ("claimed_effect_no_complete", True),
    "D. after external side effect": ("claimed_effect_no_complete", True),
    "E. before completion write": ("claimed_effect_no_complete", True),
    "F. after completion write": ("completed_with_effect", False),
}

# Final physical emails delivered after crash + recovery, per physical state.
EXPECTED_SENDS: dict[str, int] = {
    "never_claimed": 1,
    "claimed_no_effect": 1,
    "claimed_effect_no_complete": 2,  # the duplicate-delivery cell
    "completed_with_effect": 1,
}


async def _drive(queue: MongoQueue, state: str, job_id: str) -> MockMailProvider:
    """Drive the pre-enqueued ``job_id`` to the requested physical state."""
    provider = MockMailProvider()
    if state == "never_claimed":
        return provider
    claimed = await queue.claim("worker-a")
    assert claimed is not None and claimed.id == job_id
    if state == "claimed_no_effect":
        return provider
    await send_email_handler(PAYLOAD, _ctx(claimed, "worker-a"), provider=provider)
    if state == "completed_with_effect":
        assert await queue.complete_job(
            claimed.id, "worker-a", execution_version=claimed.execution_version
        )
    return provider


async def test_crash_point_matrix(queue: MongoQueue) -> None:
    """Every crash point: expected state, recovery, duplicate risk, and the
    side-effect count that results from at-least-once recovery."""
    for point, (state, dup_risk) in CRASH_TABLE.items():
        await queue.delete_all()
        base = utcnow()
        job_id = await queue.enqueue(
            function="send_email", payload=PAYLOAD, tenant_id="tenant-a", now=base
        )
        provider = await _drive(queue, state, job_id)

        # 1) Expected state immediately after the crash at `point`.
        restored = await queue.get(job_id)
        assert restored is not None
        if state == "never_claimed":
            assert restored.status == STATUS_PENDING
        elif state == "completed_with_effect":
            assert restored.status == STATUS_COMPLETED
        else:
            assert restored.status == STATUS_RUNNING

        # 2) Recovery behaviour.
        if state == "completed_with_effect":
            # Terminal: nothing to recover; a late claim finds nothing.
            assert await queue.claim("worker-b", now=base + timedelta(days=1)) is None
        else:
            recovered = await queue.claim(
                "worker-b", now=base + timedelta(seconds=queue.lease_seconds + 1)
            )
            assert recovered is not None, f"{point}: job was permanently stuck"
            assert recovered.id == job_id
            assert recovered.attempts == (1 if state == "never_claimed" else 2)
            # Recovery re-runs the handler (the at-least-once behaviour).
            await send_email_handler(PAYLOAD, _ctx(recovered, "worker-b"), provider=provider)
            assert (
                await queue.complete_job(
                    recovered.id, "worker-b", execution_version=recovered.execution_version
                )
                is True
            )

        # 3) Duplicate risk: only the 'sent-then-crashed' states duplicate.
        assert provider.sent_count == EXPECTED_SENDS[state], point
        assert dup_risk == (state == "claimed_effect_no_complete")

    # 4) None of the points left a permanently stuck (running, unexpired) job.
    assert await queue.count_documents(status=STATUS_RUNNING) == 0
    assert await queue.count_documents(status=STATUS_DEAD) == 0


async def test_never_claimed_job_is_recoverable_and_terminal_once(queue: MongoQueue) -> None:
    base = utcnow()
    job_id = await queue.enqueue(
        function="send_email", payload=PAYLOAD, tenant_id="tenant-a", now=base
    )
    # worker-a never claimed it (crashed before claim). No side effect yet.
    provider = MockMailProvider()
    recovered = await queue.claim("worker-b", now=base + timedelta(seconds=5))
    assert recovered is not None and recovered.id == job_id
    await send_email_handler(PAYLOAD, _ctx(recovered, "worker-b"), provider=provider)
    assert (
        await queue.complete_job(job_id, "worker-b", execution_version=recovered.execution_version)
        is True
    )
    assert provider.sent_count == 1
    final = await queue.get(job_id)
    assert final is not None and final.status == STATUS_COMPLETED
    # Terminal state is durable and not re-runnable.
    assert await queue.claim("worker-c", now=base + timedelta(days=1)) is None
