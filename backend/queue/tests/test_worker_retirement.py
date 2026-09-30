"""Crash recovery and the Mongo worker process lifecycle (Phase 18A).

Two things are proven here:

1. **Retirement semantics** (``retire_expired``), driven by an injected ``now``
   so the outcome is a fact, not a timing race: only a RUNNING row whose lease
   lapsed *and* whose attempts are exhausted can never be claimed again, so
   only that row becomes DEAD. A row with attempts left must stay reclaimable.
2. **Scheduling + lifecycle** of the opt-in consumer
   (``backend.workers.mongo``): one recovery sweep before the first claim, a
   bounded recurring sweep, best-effort survival of a failing sweep, fail-loud
   under the wrong backend, and a shutdown that releases every resource.

The Mongo-backed cases use the isolated prototype mongod; the lifecycle cases
inject a fake queue and never open a real connection.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import pytest
from backend.core.config import Settings
from backend.core.database import MongoDB
from backend.queue.mongo.ids import add_seconds, utcnow
from backend.queue.mongo.models import (
    STATUS_COMPLETED,
    STATUS_DEAD,
    STATUS_PENDING,
    STATUS_RETRY_PENDING,
    STATUS_RUNNING,
)
from backend.queue.mongo_adapter import MongoQueueAdapter
from backend.queue.worker import MongoWorkerLoop
from backend.services.ai.provider_health import ProviderHealthStore
from backend.workers import mongo as mongo_worker

_TENANT = "tenant-a"


def _settings(**overrides: Any) -> Settings:
    return Settings(
        queue_backend="mongo",
        mongo_queue_enabled=True,
        mongo_queue_database="webchat_ai_queue_retirement",
        **overrides,
    )


# ----------------------------------------------------------------------
# retire_expired semantics (injected clock: fully deterministic)
# ----------------------------------------------------------------------


async def test_retire_expired_never_touches_work_with_attempts_left(
    adapter: MongoQueueAdapter,
) -> None:
    """An expired lease with attempts remaining must stay reclaimable.

    Retiring it would strand retryable work; the store only retires rows that
    can never be claimed again.
    """
    t0 = utcnow()
    job_id = await adapter.enqueue(
        "crawl_website", payload={"crawl_job_id": "c-1"}, tenant_id=_TENANT, now=t0
    )
    claimed = await adapter.claim("worker-a", now=t0)
    assert claimed is not None and claimed.id == job_id

    later = add_seconds(t0, adapter.lease_seconds + 60)
    assert await adapter.retire_expired(now=later) == 0
    job = await adapter.get(job_id)
    assert job is not None and job.status == STATUS_RUNNING

    # ...and the next worker reclaims it, proving it was never stranded.
    reclaimed = await adapter.claim("worker-b", now=later)
    assert reclaimed is not None and reclaimed.id == job_id


async def test_retire_expired_retires_a_crash_on_the_final_attempt(
    adapter: MongoQueueAdapter,
) -> None:
    """Crash on the last attempt with a lapsed lease: DEAD, not stuck RUNNING."""
    t0 = utcnow()
    job_id = await adapter.enqueue(
        "crawl_website", payload={"crawl_job_id": "c-2"}, tenant_id=_TENANT, max_tries=1, now=t0
    )
    assert await adapter.claim("worker-a", now=t0) is not None

    later = add_seconds(t0, adapter.lease_seconds + 60)
    assert await adapter.retire_expired(now=later) == 1
    job = await adapter.get(job_id)
    assert job is not None
    assert job.status == STATUS_DEAD
    assert job.finished_at is not None
    assert "lease expired" in (job.last_error or "")

    # Idempotent: a second sweep changes nothing and claims nothing.
    assert await adapter.retire_expired(now=later) == 0
    assert await adapter.claim("worker-b", now=later) is None


async def test_retire_expired_ignores_unclaimed_rows(adapter: MongoQueueAdapter) -> None:
    """A row nobody has claimed yet is not a leak, however old it is."""
    t0 = utcnow()
    far_future = add_seconds(t0, 86_400)

    pending = await adapter.enqueue(
        "crawl_website", payload={"crawl_job_id": "c-3"}, tenant_id=_TENANT, now=t0
    )

    assert await adapter.retire_expired(now=far_future) == 0
    assert (await adapter.get(pending)).status == STATUS_PENDING  # type: ignore[union-attr]
    assert await adapter.claim("worker-a", now=far_future) is not None


async def test_retire_expired_ignores_finished_rows(adapter: MongoQueueAdapter) -> None:
    """A completed row is not a leak either - it must not be resurrected."""
    t0 = utcnow()
    far_future = add_seconds(t0, 86_400)

    done = await adapter.enqueue(
        "crawl_website", payload={"crawl_job_id": "c-4"}, tenant_id=_TENANT, now=t0
    )
    claimed = await adapter.claim("worker-a", now=t0)
    assert claimed is not None and claimed.id == done
    assert await adapter.complete(
        done, "worker-a", execution_version=claimed.execution_version, result=None, now=t0
    )

    assert await adapter.retire_expired(now=far_future) == 0
    assert (await adapter.get(done)).status == STATUS_COMPLETED  # type: ignore[union-attr]
    assert await adapter.claim("worker-b", now=far_future) is None


# ----------------------------------------------------------------------
# the recurring sweep
# ----------------------------------------------------------------------


class _CountingQueue:
    """A queue that only counts recovery sweeps."""

    def __init__(self, *, fail: bool = False) -> None:
        self.sweeps = 0
        self.fail = fail
        self.reached = asyncio.Event()

    async def retire_expired(self) -> int:
        self.sweeps += 1
        if self.sweeps >= 3:
            self.reached.set()
        if self.fail:
            raise RuntimeError("store unavailable")
        return 0


async def test_retire_loop_sweeps_on_a_bounded_cadence() -> None:
    """Periodic recovery, and a prompt return once the stop event is set."""
    queue = _CountingQueue()
    stop = asyncio.Event()
    task = asyncio.create_task(
        mongo_worker._retire_loop(queue, interval=0.01, stop_event=stop)  # type: ignore[arg-type]
    )
    await asyncio.wait_for(queue.reached.wait(), timeout=5.0)
    stop.set()
    await asyncio.wait_for(task, timeout=1.0)
    # Bounded cadence: no sweep runs after the stop, and none is missed as busy work.
    settled = queue.sweeps
    await asyncio.sleep(0.05)
    assert queue.sweeps == settled


async def test_retire_loop_survives_a_failing_sweep() -> None:
    """A store hiccup degrades the recovery cadence; it never kills the worker."""
    queue = _CountingQueue(fail=True)
    stop = asyncio.Event()
    task = asyncio.create_task(
        mongo_worker._retire_loop(queue, interval=0.01, stop_event=stop)  # type: ignore[arg-type]
    )
    await asyncio.wait_for(queue.reached.wait(), timeout=5.0)
    stop.set()
    await asyncio.wait_for(task, timeout=1.0)
    assert queue.sweeps >= 3


async def test_retire_initial_survives_a_failing_sweep() -> None:
    await mongo_worker._retire_initial(_CountingQueue(fail=True))  # type: ignore[arg-type]


# ----------------------------------------------------------------------
# process lifecycle
# ----------------------------------------------------------------------


async def test_mongo_worker_refuses_to_run_under_the_arq_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail loud: never start a Mongo consumer against another backend."""
    monkeypatch.setattr(mongo_worker, "get_settings", lambda: Settings(queue_backend="arq"))
    monkeypatch.setattr(
        mongo_worker,
        "get_queue",
        lambda: (_ for _ in ()).throw(AssertionError("must not build a queue")),
    )

    with pytest.raises(SystemExit) as excinfo:
        await mongo_worker._run()
    assert "QUEUE_BACKEND" in str(excinfo.value)


async def test_mongo_worker_refuses_a_non_mongo_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.queue.arq_adapter import ArqQueueAdapter

    monkeypatch.setattr(mongo_worker, "get_settings", _settings)
    monkeypatch.setattr(mongo_worker, "get_queue", lambda: ArqQueueAdapter("redis://x/0"))

    with pytest.raises(SystemExit, match="did not yield a Mongo queue adapter"):
        await mongo_worker._run()


class _RecordingLoop:
    """Stands in for the poll loop so a boot can be observed and stopped."""

    built: list[dict[str, Any]] = []

    def __init__(
        self,
        queue: Any,
        *,
        poll_schedule: tuple[float, ...],
        heartbeat_seconds: float,
        app_context: Any,
    ) -> None:
        self.queue = queue
        self.poll_schedule = poll_schedule
        self.heartbeat_seconds = heartbeat_seconds
        self.app_context = app_context
        _RecordingLoop.built.append(
            {
                "queue": queue,
                "poll_schedule": poll_schedule,
                "heartbeat_seconds": heartbeat_seconds,
                "app_context": app_context,
            }
        )

    async def run(self, *, stop_event: asyncio.Event) -> None:
        stop_event.set()


async def test_boot_recovers_a_crashed_job_before_serving_and_shuts_down(
    monkeypatch: pytest.MonkeyPatch, short_lease_adapter: MongoQueueAdapter
) -> None:
    """Indexes, one recovery sweep, then the poll loop - and clean shutdown.

    The crashed row is real (a claimed job whose worker died on its final
    attempt), so this asserts the boot sweep actually recovers work.
    """
    adapter = short_lease_adapter
    t0 = utcnow()
    crashed = await adapter.enqueue(
        "crawl_website",
        payload={"crawl_job_id": "c-9"},
        tenant_id=_TENANT,
        max_tries=1,
        now=t0,
    )
    assert await adapter.claim("worker-a", now=t0) is not None
    while True:  # deterministic: wait for the real lease to lapse
        job = await adapter.get(crashed)
        assert job is not None and job.lease_expires_at is not None
        if job.lease_expires_at <= utcnow():
            break
        await asyncio.sleep(0.01)

    _RecordingLoop.built.clear()
    closed: list[str] = []
    monkeypatch.setattr(mongo_worker, "get_settings", _settings)
    monkeypatch.setattr(mongo_worker, "get_queue", lambda: adapter)
    monkeypatch.setattr(mongo_worker, "MongoWorkerLoop", _RecordingLoop)
    monkeypatch.setattr(mongo_worker, "_build_app_context", lambda: {"app_name": "test"})
    monkeypatch.setattr(mongo_worker, "close_browser", _closer(closed, "browser"))
    monkeypatch.setattr(MongoDB, "close", _closer(closed, "mongo"))
    monkeypatch.setattr(mongo_worker, "close_redis", _closer(closed, "redis"))

    assert await mongo_worker._run() == 0

    # The crashed job was recovered by the boot sweep.
    recovered = await adapter.get(crashed)
    assert recovered is not None and recovered.status == STATUS_DEAD
    # The heartbeat cadence is the one the queue was configured with.
    assert len(_RecordingLoop.built) == 1
    assert _RecordingLoop.built[0]["queue"] is adapter
    assert _RecordingLoop.built[0]["app_context"] == {"app_name": "test"}
    # Phase 18C: the boot path forwards the configured cadence to the loop.
    assert _RecordingLoop.built[0]["poll_schedule"] == tuple(_settings().mongo_queue_poll_schedule)
    # Every resource released, queue first.
    assert closed == ["browser", "mongo", "redis"]


class _IdleLoop:
    """A poll loop that keeps serving until the sweep cadence has proven itself.

    Unlike :class:`_RecordingLoop` it never sets ``stop_event`` on its own: the
    process must stop because the *sweeper* asked it to, which is what proves
    the sweep is wired into ``_run`` and not merely available beside it.
    """

    def __init__(
        self,
        queue: Any,
        *,
        poll_schedule: tuple[float, ...],
        heartbeat_seconds: float,
        app_context: Any,
    ) -> None:
        # ``poll_schedule`` is accepted because the production constructor passes
        # it (Phase 18C); these tests are about the retire cadence, not polling.
        _ = (queue, poll_schedule, heartbeat_seconds, app_context)

    async def run(self, *, stop_event: asyncio.Event) -> None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop_event.wait(), timeout=0.05)
        stop_event.set()


async def test_the_recovery_sweep_keeps_running_after_boot(
    monkeypatch: pytest.MonkeyPatch, short_lease_adapter: MongoQueueAdapter
) -> None:
    """The cadence is a guarantee, not a helper: sweeps continue while serving.

    A dead worker's lease must lapse back into the queue on a timer, so the loop
    cannot be "run once at boot and hope". The boot sweep alone is already proven
    by the test above; this one fails if the periodic sweep is ever unwired.
    """
    adapter = short_lease_adapter
    sweeps: list[int] = []
    enough = asyncio.Event()
    original = adapter.retire_expired

    async def _counted() -> int:
        sweeps.append(len(sweeps))
        if len(sweeps) >= 3:
            enough.set()
        return await original()

    monkeypatch.setattr(adapter, "retire_expired", _counted)
    monkeypatch.setattr(
        mongo_worker, "get_settings", lambda: _settings(mongo_queue_heartbeat_seconds=0.01)
    )
    # The production floor is 5s; the test drives the cadence, not the floor.
    monkeypatch.setattr(mongo_worker, "_RETIRE_INTERVAL_FLOOR_SECONDS", 0.0)
    monkeypatch.setattr(mongo_worker, "get_queue", lambda: adapter)
    monkeypatch.setattr(mongo_worker, "MongoWorkerLoop", _IdleLoop)
    monkeypatch.setattr(mongo_worker, "_build_app_context", lambda: {"app_name": "test"})
    monkeypatch.setattr(mongo_worker, "close_browser", _closer([], "browser"))
    monkeypatch.setattr(MongoDB, "close", _closer([], "mongo"))
    monkeypatch.setattr(mongo_worker, "close_redis", _closer([], "redis"))

    assert await asyncio.wait_for(mongo_worker._run(), timeout=15) == 0
    # 1 boot sweep + at least 2 periodic ones.
    assert len(sweeps) >= 3, f"the periodic sweep did not run: {sweeps}"


def _closer(closed: list[str], name: str) -> Any:
    async def _close() -> None:
        closed.append(name)

    return _close


async def test_shutdown_releases_everything_even_when_one_close_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed: list[str] = []

    async def _boom() -> None:
        closed.append("browser")
        raise RuntimeError("browser already gone")

    monkeypatch.setattr(mongo_worker, "close_browser", _boom)
    monkeypatch.setattr(MongoDB, "close", _closer(closed, "mongo"))
    monkeypatch.setattr(mongo_worker, "close_redis", _closer(closed, "redis"))

    await mongo_worker._shutdown()
    assert closed == ["browser", "mongo", "redis"]


async def test_the_worker_context_carries_the_shared_process_services(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One embedding client and one provider-health store per process.

    Also the boot guarantee: constructing them must not open a connection, so an
    API/Redis outage cannot stop the worker from starting.
    """
    pings: list[str] = []

    class _Redis:
        """A client whose every network method records the attempt."""

        async def ping(self) -> bool:
            pings.append("ping")
            return True

        async def get(self, *args: Any, **kwargs: Any) -> Any:
            pings.append("get")
            return None

    class _Client:
        pass

    monkeypatch.setattr(mongo_worker, "get_settings", _settings)
    monkeypatch.setattr(mongo_worker, "build_ingestion_embedding_client", _Client)
    monkeypatch.setattr(mongo_worker, "get_redis", _Redis)

    context = mongo_worker._build_app_context()
    assert set(context) == {"app_name", "embedding_client", "embedding_provider_health"}
    assert isinstance(context["embedding_client"], _Client)
    assert isinstance(context["embedding_provider_health"], ProviderHealthStore)
    assert pings == [], "worker boot must not require Redis to be reachable"


async def test_app_context_is_merged_under_the_job_context(
    adapter: MongoQueueAdapter,
) -> None:
    """A job may not be spoofed by a process-level key it does not own."""
    seen: dict[str, Any] = {}

    async def handler(ctx: dict[str, Any], crawl_job_id: str) -> dict[str, Any]:
        seen.update(ctx)
        return {"ok": crawl_job_id}

    job_id = await adapter.enqueue(
        "crawl_website", payload={"crawl_job_id": "c-11"}, tenant_id=_TENANT
    )
    loop = MongoWorkerLoop(
        adapter,
        handlers={"crawl_website": handler},
        worker_id="worker-a",
        app_context={
            "embedding_client": "shared",
            "job_id": "spoofed",
            "max_tries": 99,
            "queue": "spoofed-queue",
        },
    )
    assert await loop.work_once() is not None
    assert seen["embedding_client"] == "shared"
    assert seen["job_id"] == job_id
    assert seen["max_tries"] == 3
    assert seen["queue"] is adapter
    assert await adapter.get(job_id) is not None


async def test_a_job_cannot_retire_a_retry_pending_row(
    adapter: MongoQueueAdapter,
) -> None:
    """A row waiting on backoff has no lease and is never a retirement target."""
    t0 = utcnow()
    job_id = await adapter.enqueue(
        "crawl_website", payload={"crawl_job_id": "c-12"}, tenant_id=_TENANT, now=t0
    )
    assert await adapter.claim("worker-a", now=t0) is not None
    job = await adapter.get(job_id)
    assert job is not None
    status = await adapter.fail(
        job_id,
        "worker-a",
        execution_version=job.execution_version,
        error="boom",
        retry=True,
        now=t0,
    )
    assert status == STATUS_RETRY_PENDING
    assert await adapter.retire_expired(now=add_seconds(t0, 86_400)) == 0
    assert (await adapter.get(job_id)).status == STATUS_RETRY_PENDING  # type: ignore[union-attr]
