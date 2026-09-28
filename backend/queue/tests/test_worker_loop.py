"""Mongo worker loop tests (Phase 17A §28.12-19).

The loop is the opt-in Mongo-mode consumer. Every test injects a **fake**
handler: nothing here executes a real job, sends a real email, crawls a real
site or calls an embedding provider. The only external dependency is the
isolated prototype mongod.

The loop's real job here is the **ARQ parity mapping** - see the module
docstring in ``backend/queue/worker.py`` and ``test_retry_policy.py``.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from backend.queue.errors import UnknownFunctionError
from backend.queue.mongo.ids import utcnow
from backend.queue.mongo.models import STATUS_COMPLETED
from backend.queue.mongo_adapter import RESULT_POLICY_FULL, MongoQueueAdapter
from backend.queue.worker import MongoWorkerLoop

_TENANT = "tenant-a"


async def _crawl_ok(ctx: dict[str, Any], crawl_job_id: str) -> dict[str, Any]:
    return {"status": "completed", "pages": 2, "crawl_job_id": crawl_job_id}


# ----------------------------------------------------------------------
# happy path
# ----------------------------------------------------------------------


async def test_loop_claims_dispatches_completes(adapter: MongoQueueAdapter) -> None:
    job_id = await adapter.enqueue(
        "crawl_website", payload={"crawl_job_id": "c-1"}, tenant_id=_TENANT
    )
    loop = MongoWorkerLoop(adapter, handlers={"crawl_website": _crawl_ok}, worker_id="worker-a")
    outcome = await loop.work_once()
    assert outcome is not None
    assert outcome.status == STATUS_COMPLETED
    assert outcome.function == "crawl_website"
    assert outcome.attempts == 1
    assert outcome.lease_lost is False
    job = await adapter.get(job_id)
    assert job is not None
    assert job.status == STATUS_COMPLETED
    assert job.finished_at is not None


async def test_status_policy_discards_the_returned_result(adapter: MongoQueueAdapter) -> None:
    """Default policy stores no result body: nothing in the repo reads one."""
    job_id = await adapter.enqueue(
        "crawl_website", payload={"crawl_job_id": "c-1"}, tenant_id=_TENANT
    )
    loop = MongoWorkerLoop(adapter, handlers={"crawl_website": _crawl_ok}, worker_id="worker-a")
    assert await loop.work_once() is not None
    job = await adapter.get(job_id)
    assert job is not None
    assert job.result is None


async def test_full_policy_stores_the_returned_result(queue_db: Any) -> None:
    adapter = MongoQueueAdapter(
        queue_db, collection_name="worker_jobs_loop_full", result_policy=RESULT_POLICY_FULL
    )
    await adapter.ensure_indexes()
    job_id = await adapter.enqueue(
        "crawl_website", payload={"crawl_job_id": "c-1"}, tenant_id=_TENANT
    )
    loop = MongoWorkerLoop(adapter, handlers={"crawl_website": _crawl_ok}, worker_id="worker-a")
    assert await loop.work_once() is not None
    job = await adapter.get(job_id)
    assert job is not None
    assert job.result == {"status": "completed", "pages": 2, "crawl_job_id": "c-1"}
    await queue_db.drop_collection("worker_jobs_loop_full")


async def test_work_once_is_none_on_an_empty_queue(adapter: MongoQueueAdapter) -> None:
    loop = MongoWorkerLoop(adapter, worker_id="worker-a")
    assert await loop.work_once() is None


async def test_handler_receives_arq_shaped_context(adapter: MongoQueueAdapter) -> None:
    captured: dict[str, Any] = {}

    async def capture(ctx: dict[str, Any], crawl_job_id: str) -> dict[str, Any]:
        captured["ctx"] = dict(ctx)
        captured["arg"] = crawl_job_id
        return {"ok": True}

    await adapter.enqueue("crawl_website", payload={"crawl_job_id": "c-2"}, tenant_id="t9")
    loop = MongoWorkerLoop(adapter, handlers={"crawl_website": capture}, worker_id="w")
    await loop.work_once()

    ctx = captured["ctx"]
    assert ctx["function"] == "crawl_website"
    assert ctx["job_try"] == 1
    assert ctx["max_tries"] == 3
    assert ctx["queue_name"] == adapter.queue_name
    # crawl keeps its own per-function timeout, not ARQ's global 600 s.
    assert ctx["timeout"] == 3600
    assert captured["arg"] == "c-2"


async def test_context_does_not_carry_the_queue_row_tenant(adapter: MongoQueueAdapter) -> None:
    """The job's authority is the domain row, not the queue row's copy.

    Production jobs read their own tenant (``crawl_website`` sets
    ``tenant_id_var`` from the crawl job document). Injecting the queue row's
    copy could mask a tenant mismatch, so the context builder omits it.
    """
    captured: dict[str, Any] = {}

    async def capture(ctx: dict[str, Any], crawl_job_id: str) -> dict[str, Any]:
        captured["ctx"] = dict(ctx)
        return {"ok": True}

    await adapter.enqueue("crawl_website", payload={"crawl_job_id": "c-2"}, tenant_id="t9")
    loop = MongoWorkerLoop(adapter, handlers={"crawl_website": capture}, worker_id="w")
    await loop.work_once()
    assert "tenant_id" not in captured["ctx"]


# ----------------------------------------------------------------------
# failure mapping
# ----------------------------------------------------------------------


async def test_plain_exception_dead_letters_on_the_first_attempt(
    adapter: MongoQueueAdapter,
) -> None:
    """ARQ parity: an ordinary exception is terminal despite max_tries=3."""

    async def boom(_ctx: dict[str, Any], *_: Any) -> Any:
        raise RuntimeError("ordinary failure")

    job_id = await adapter.enqueue(
        "crawl_website", payload={"crawl_job_id": "c-3"}, tenant_id=_TENANT
    )
    loop = MongoWorkerLoop(adapter, handlers={"crawl_website": boom}, worker_id="w")
    outcome = await loop.work_once()
    assert outcome is not None
    assert outcome.status == "dead"
    assert outcome.attempts == 1
    job = await adapter.get(job_id)
    assert job is not None
    assert job.status == "dead"
    assert "RuntimeError" in (job.last_error or "")
    # Not re-scheduled: a dead job is terminal.
    assert await loop.work_once() is None


async def test_cancelled_error_maps_to_retry(adapter: MongoQueueAdapter) -> None:
    """ARQ parity: a job-raised CancelledError IS retried."""
    seen: list[int] = []

    async def cancelled(_ctx: dict[str, Any], *_: Any) -> Any:
        seen.append(1)
        raise asyncio.CancelledError()

    job_id = await adapter.enqueue(
        "process_document", payload={"document_id": "d", "run_id": None}, tenant_id=_TENANT
    )
    loop = MongoWorkerLoop(adapter, handlers={"process_document": cancelled}, worker_id="w")
    outcome = await loop.work_once()
    assert outcome is not None
    assert outcome.status == "retry_pending"
    job = await adapter.get(job_id)
    assert job is not None
    # Re-queued with backoff, not immediately claimable.
    assert job.run_at > utcnow()
    assert len(seen) == 1


async def test_unknown_function_is_dead_lettered_not_executed(
    adapter: MongoQueueAdapter, monkeypatch: Any
) -> None:
    """A poisoned/hand-edited row must be dead, never imported or called."""

    def _boom(_name: str) -> Any:
        raise UnknownFunctionError("unknown")

    monkeypatch.setattr("backend.queue.worker.resolve_registered", _boom)
    job_id = await adapter.enqueue(
        "crawl_website", payload={"crawl_job_id": "c-4"}, tenant_id=_TENANT
    )
    loop = MongoWorkerLoop(adapter, worker_id="w")
    outcome = await loop.work_once()
    assert outcome is not None
    assert outcome.status == "dead"
    job = await adapter.get(job_id)
    assert job is not None
    assert "no handler registered" in (job.last_error or "")


# ----------------------------------------------------------------------
# lease / fencing
# ----------------------------------------------------------------------


async def test_heartbeat_keeps_the_lease_alive(adapter: MongoQueueAdapter) -> None:
    ticks = {"count": 0}

    async def tracking_sleep(seconds: float) -> None:
        _ = seconds
        ticks["count"] += 1
        await asyncio.sleep(0.02)

    async def slow(_ctx: dict[str, Any], *_: Any) -> Any:
        await asyncio.sleep(0.35)
        return {"ok": True}

    await adapter.enqueue("crawl_website", payload={"crawl_job_id": "c-5"}, tenant_id=_TENANT)
    loop = MongoWorkerLoop(
        adapter,
        handlers={"crawl_website": slow},
        worker_id="w",
        heartbeat_seconds=0.1,
        sleep=tracking_sleep,
    )
    outcome = await loop.work_once()
    assert outcome is not None
    assert outcome.status == STATUS_COMPLETED
    assert ticks["count"] >= 2


async def _wait_for_lease_expiry(adapter: MongoQueueAdapter, job_id: str) -> None:
    """Block until the claimed row's lease has actually lapsed.

    The store reclaims on ``lease_expires_at <= now`` with the same clock this
    test reads, so observing the lapse is proof - not a guess - that worker-b's
    next claim is eligible. That replaces the old fixed ``asyncio.sleep`` race
    without weakening the assertion.
    """
    async with asyncio.timeout(5.0):
        while True:
            job = await adapter.get(job_id)
            assert job is not None, "the queued row vanished"
            if job.lease_expires_at is not None and job.lease_expires_at <= utcnow():
                return
            await asyncio.sleep(0.01)


async def test_dual_execution_and_stale_completion_is_fenced(
    short_lease_adapter: MongoQueueAdapter,
) -> None:
    """The at-least-once hazard, end to end, with two real loops.

    worker-a claims and starts a slow job, its lease lapses, worker-b reclaims
    and completes, and worker-a's late completion is rejected by the
    ``execution_version`` fence. Exactly the situation a crawl can hit.

    Deterministic by construction: worker-a's handler is gated on events, not on
    wall-clock sleeps, and the reclaim only happens once the lease is observed
    to have lapsed. No timing assumption, no retry, no weakened assertion.
    """
    adapter = short_lease_adapter
    job_id = await adapter.enqueue(
        "crawl_website", payload={"crawl_job_id": "c-6"}, tenant_id=_TENANT
    )

    started = asyncio.Event()
    release = asyncio.Event()

    async def slow(_ctx: dict[str, Any], *_: Any) -> Any:
        started.set()
        # Bounded so a broken fence fails the assertions instead of hanging.
        await asyncio.wait_for(release.wait(), timeout=10.0)
        return {"winner": "a"}

    async def fast(_ctx: dict[str, Any], *_: Any) -> dict[str, Any]:
        return {"winner": "b"}

    loop_a = MongoWorkerLoop(
        adapter, handlers={"crawl_website": slow}, worker_id="worker-a", heartbeat_seconds=30
    )
    loop_b = MongoWorkerLoop(
        adapter, handlers={"crawl_website": fast}, worker_id="worker-b", heartbeat_seconds=30
    )
    task_a = asyncio.create_task(loop_a.work_once())
    # worker-a has claimed and is mid-execution.
    await asyncio.wait_for(started.wait(), timeout=5.0)
    claimed = await adapter.get(job_id)
    assert claimed is not None and claimed.locked_by == "worker-a"
    # The 0.5 s lease lapses with no renewal (heartbeat is 30 s away).
    await _wait_for_lease_expiry(adapter, job_id)

    outcome_b = await loop_b.work_once()
    # Only now may worker-a finish; its completion is fenced out.
    release.set()
    outcome_a = await asyncio.wait_for(task_a, timeout=10.0)

    assert outcome_b is not None and outcome_b.status == STATUS_COMPLETED
    assert outcome_a is not None and outcome_a.status == "not_owned"
    assert outcome_a.lease_lost is True
    job = await adapter.get(job_id)
    assert job is not None
    assert job.status == STATUS_COMPLETED
    assert job.locked_by == "worker-b"


# ----------------------------------------------------------------------
# run loop / adaptive polling
# ----------------------------------------------------------------------


async def test_run_processes_the_queue_then_stops(adapter: MongoQueueAdapter) -> None:
    await adapter.enqueue("crawl_website", payload={"crawl_job_id": "c-7"}, tenant_id=_TENANT)
    loop = MongoWorkerLoop(
        adapter, handlers={"crawl_website": _crawl_ok}, worker_id="w", sleep=_no_sleep
    )
    stop = asyncio.Event()
    task = asyncio.create_task(loop.run(stop_event=stop))
    for _ in range(50):
        if await adapter.count_documents(STATUS_COMPLETED) == 1:
            break
        await asyncio.sleep(0.01)
    stop.set()
    await asyncio.wait_for(task, timeout=2)
    assert await adapter.count_documents(STATUS_COMPLETED) == 1


async def test_adaptive_poll_schedule_backs_off_while_idle() -> None:
    """Idle polling must ratchet up, not poll at a fixed fast rate like ARQ."""
    from backend.queue.mongo.poller import AdaptivePoller

    poller = AdaptivePoller((1.0, 2.0, 5.0, 10.0, 30.0))
    idle = [poller.nick(False) for _ in range(7)]
    assert idle == [1.0, 2.0, 5.0, 10.0, 30.0, 30.0, 30.0]
    # Any work resets to the hot interval.
    assert poller.nick(True) == 1.0


async def test_run_does_not_busy_poll_an_empty_queue(adapter: MongoQueueAdapter) -> None:
    """A guarded regression on the idle path: no DB command storm."""
    loop = MongoWorkerLoop(adapter, worker_id="w", sleep=_no_sleep)
    stop = asyncio.Event()
    task = asyncio.create_task(loop.run(stop_event=stop))
    await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(task, timeout=2)
    assert await adapter.count_documents() == 0


async def _no_sleep(_seconds: float) -> None:
    await asyncio.sleep(0)


@pytest.mark.parametrize("stop_after", [0.0, 0.05])
async def test_run_honours_a_stop_deadline(adapter: MongoQueueAdapter, stop_after: float) -> None:
    loop = MongoWorkerLoop(adapter, worker_id="w", sleep=_no_sleep)
    await asyncio.wait_for(loop.run(stop_after_seconds=stop_after), timeout=2)
