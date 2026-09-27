"""ARQ-parity retry policy: the measured contract, encoded as tests.

How the table below was obtained: a real ``arq.worker.Worker`` was run against
an isolated Redis (``127.0.0.1:27029``) with the production ``WorkerSettings``
shape (``max_tries=3``, ``job_timeout=600``, ``retry_jobs=True``), enqueueing
one job per outcome class and counting executions. Results (arq 0.28.0):

=======================================  ==========  ========================
raised inside the job                    executions  outcome
=======================================  ==========  ========================
success                                     1        completed
ordinary exception (``ValueError``)         1        dead
``asyncio.wait_for`` timeout                1        dead (builtin TimeoutError)
``arq.worker.Retry`` / ``RetryJob``         3        dead after max_tries
job-raised ``asyncio.CancelledError``       3        dead after max_tries
=======================================  ==========  ========================

The counter-intuitive rows are the middle two: ``max_tries=3`` is *unreachable*
for an ordinary exception or for a timeout, so retrying them in the Mongo
backend would silently change production crawl/quota behaviour. ARQ also applies
no backoff to its own retry paths - the 5/30/180 s schedule in ``QueueConfig``
is the knowledge-domain schedule, not an ARQ behaviour.

``test_arq_worker_agrees_with_the_mongo_mapping`` re-runs the ARQ side of the
comparison live so the table cannot silently drift from the installed arq
version. It is skipped when the isolated Redis is absent.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import pathlib
import sys
from collections.abc import Callable
from typing import Any

import pytest
from backend.queue.errors import JobTimeoutError
from backend.queue.mongo.ids import utcnow
from backend.queue.mongo.models import STATUS_DEAD
from backend.queue.mongo_adapter import MongoQueueAdapter
from backend.queue.worker import MongoWorkerLoop

_TENANT = "tenant-a"
_ARQ_REDIS = os.environ.get("QUEUE_TEST_ARQ_REDIS_URL", "redis://127.0.0.1:27029")


async def _enqueue_document(adapter: MongoQueueAdapter, **kwargs: Any) -> str:
    return await adapter.enqueue(
        "process_document",
        payload={"document_id": "d1", "run_id": None},
        tenant_id=_TENANT,
        **kwargs,
    )


# ----------------------------------------------------------------------
# the mapping, through the real worker loop and a real Mongo store
# ----------------------------------------------------------------------


async def _ok(_ctx: dict[str, Any], *_: Any) -> dict[str, Any]:
    return {"ok": True}


def _raise(exc: BaseException) -> Callable[..., Any]:
    async def handler(*_args: Any, **_kwargs: Any) -> Any:
        raise exc

    return handler


class _OrdinaryFailure(Exception):
    """A plain exception, i.e. the class ARQ dead-letters immediately."""


@pytest.mark.parametrize(
    ("label", "handler", "expected_status"),
    [
        ("success", _ok, "completed"),
        # ARQ dead-letters an ordinary exception on attempt one.
        ("ordinary exception", _raise(ValueError("boom")), STATUS_DEAD),
        # ... and a job timeout is terminal too.
        ("wait_for timeout", _raise(TimeoutError("timed out")), STATUS_DEAD),
        ("explicit JobTimeoutError", _raise(JobTimeoutError("timed out")), STATUS_DEAD),
    ],
)
async def test_terminal_outcomes_stay_terminal(
    adapter: MongoQueueAdapter,
    label: str,
    handler: Callable[..., Any],
    expected_status: str,
) -> None:
    """The rows that carry real production traffic: success, failure, timeout.

    Each must execute exactly once and then be terminal, so a second poll finds
    nothing. Retrying any of them would change production behaviour.
    """
    runs: list[int] = []

    async def counting(ctx: dict[str, Any], *args: Any) -> Any:
        runs.append(1)
        return await handler(ctx, *args)

    await _enqueue_document(adapter)
    loop = MongoWorkerLoop(adapter, handlers={"process_document": counting}, worker_id="w")
    outcome = await loop.work_once()
    assert outcome is not None, label
    assert outcome.status == expected_status, label
    assert len(runs) == 1, label
    assert await loop.work_once() is None, label


async def test_cancelled_error_is_retried_up_to_max_tries(adapter: MongoQueueAdapter) -> None:
    """ARQ parity: a job-raised CancelledError DOES consume the budget."""
    runs: list[int] = []

    async def cancelled(_ctx: dict[str, Any], *_: Any) -> Any:
        runs.append(1)
        raise asyncio.CancelledError()

    job_id = await _enqueue_document(adapter)
    loop = MongoWorkerLoop(adapter, handlers={"process_document": cancelled}, worker_id="w")

    statuses: list[str] = []
    for _ in range(3):
        # Clear the backoff window so the next attempt is immediately claimable.
        await adapter.queue.collection.update_one({"_id": job_id}, {"$set": {"run_at": utcnow()}})
        outcome = await loop.work_once()
        assert outcome is not None
        statuses.append(outcome.status)

    assert statuses == ["retry_pending", "retry_pending", STATUS_DEAD]
    assert len(runs) == 3, "three attempts then dead - same as ARQ max_tries=3"
    assert await loop.work_once() is None


async def test_retry_backoff_is_the_configured_schedule_not_an_arq_one(
    adapter: MongoQueueAdapter,
) -> None:
    """5/30/180 s is the knowledge-domain table; ARQ itself applies no backoff."""
    # max_tries=5 so the third backoff step is observable; on the default budget
    # the third failure dead-letters and schedules no third delay.
    job_id = await _enqueue_document(adapter, max_tries=5)
    observed: list[float] = []
    for _ in range(3):
        await adapter.queue.collection.update_one({"_id": job_id}, {"$set": {"run_at": utcnow()}})
        job = await adapter.claim("w")
        assert job is not None
        base = utcnow()
        await adapter.fail(
            job.id, "w", execution_version=job.execution_version, error="x",
            retry=True, now=base,
        )
        stored = await adapter.get(job_id)
        assert stored is not None
        observed.append((stored.run_at - base).total_seconds())
    assert [round(value) for value in observed] == [5, 30, 180]


async def test_no_production_job_raises_an_arq_retry_exception() -> None:
    """Why the "Retry -> re-queue" row has no production job behind it.

    Nothing in the production worker raises ``arq.worker.Retry`` or
    ``RetryJob``; deferred document processing is scheduled *inside* the job by
    ``enqueue_process_document_deferred``. So the rows that matter are success,
    ordinary exception and timeout.
    """
    import inspect

    from backend.workers.jobs import crawl, email, knowledge

    for module in (crawl, email, knowledge):
        source = inspect.getsource(module)
        assert "RetryJob" not in source, f"{module.__name__} raises RetryJob"
        assert "worker.Retry" not in source, f"{module.__name__} raises Retry"
        assert "raise Retry" not in source, f"{module.__name__} raises Retry"


def _probe_script() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[3] / "scripts" / "queue_arq_probe.py"


async def _arq_available(redis_url: str) -> bool:
    try:
        import redis.asyncio as aioredis
    except ImportError:  # pragma: no cover
        return False
    client = aioredis.from_url(  # type: ignore[no-untyped-call]
        redis_url, socket_connect_timeout=1
    )
    try:
        await client.ping()
    except Exception:  # noqa: BLE001
        return False
    finally:
        with contextlib.suppress(Exception):
            await client.aclose()
    return True


async def test_arq_worker_agrees_with_the_mongo_mapping() -> None:
    """Re-measure ARQ live and assert the Mongo mapping still matches.

    Runs ``scripts/queue_arq_probe.py`` in a **subprocess** and compares its
    measured execution counts against the Mongo backend's outcomes. A separate
    process is required, not merely convenient: ``arq.worker.Worker`` owns its
    event loop and its shutdown path, so driving it inside the test's loop is
    unreliable - and the script is the reproducible evidence the Phase 17A
    report quotes.

    ``ordinary`` must execute exactly once (Mongo: terminal on attempt 1),
    ``cancelled`` must reach three (Mongo: retry, retry, dead) and a timeout
    must execute exactly once (Mongo: terminal).
    """
    pytest.importorskip("arq")
    if not await _arq_available(_ARQ_REDIS):
        pytest.skip(f"isolated ARQ redis unreachable at {_ARQ_REDIS}")

    script = _probe_script()
    assert script.is_file(), f"missing ARQ probe script: {script}"
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        str(script),
        "--redis-url", _ARQ_REDIS,
        "--json",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
    assert proc.returncode == 0, f"probe failed: {stderr.decode(errors='replace')[-2000:]}"

    measured = json.loads(stdout.decode())["results"]
    assert measured["ordinary"] == 1, "ARQ must dead-letter an ordinary exception on attempt 1"
    assert measured["cancelled"] == 3, "ARQ must retry a job-raised CancelledError to max_tries=3"
    assert measured["timeout"] == 1, "ARQ must not retry a job timeout"
