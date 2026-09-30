"""Phase 18C - ``backend/workers/mongo.py`` production lifecycle.

Two production-shaped regressions, both of which are invisible to the unit tests
of the loop itself because they live in the *construction* path:

1. **Poll schedule wiring.** ``_run()`` built ``MongoWorkerLoop`` without passing
   ``settings.mongo_queue_poll_schedule``, so the configured cadence was ignored
   and the loop's own ``(1.0, 2.0, 5.0, 10.0, 30.0)`` default ran in production.
   The test drives the real ``Settings`` -> ``_run`` -> constructor chain, so it
   fails if that argument is ever dropped again.

2. **Task lifecycle.** The two loops were gathered without ``return_exceptions``
   and nothing set ``stop_event`` on the error path, so a failure in the poll
   loop orphaned the retire loop onto a Mongo client that ``_shutdown()`` was
   concurrently closing.

The Mongo queue, the embedding provider and the network are all stubbed: this
module never opens a socket, never enqueues real work, and never contacts
production.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from backend.core.config import Settings
from backend.workers import mongo as mongo_worker

# Imported at module scope, before the fixture swaps the module attribute, so the
# lifecycle tests below exercise the REAL retire loop and not the stub.
from backend.workers.mongo import _retire_loop as _real_retire_loop

_DEFAULT_SCHEDULE = [1.0, 2.0, 5.0, 10.0, 30.0]


# ----------------------------------------------------------------------
# stubs
# ----------------------------------------------------------------------


class _StubAdapter:
    """Stands in for ``MongoQueueAdapter`` - records the boot-time calls."""

    def __init__(self) -> None:
        self.index_calls = 0
        self.retire_calls = 0

    async def ensure_indexes(self) -> None:
        self.index_calls += 1

    async def retire_expired(self) -> int:
        self.retire_calls += 1
        return 0

    async def ping(self) -> bool:
        return True


class _FakeWorkerLoop:
    """Records the kwargs ``_run()`` used, then ends the run immediately."""

    captured: list[dict[str, Any]] = []
    run_error: BaseException | None = None
    #: set when the poll loop is entered, so the retire loop provably overlaps it
    entered: asyncio.Event | None = None
    #: set when the poll loop is released, so the retire loop can be observed live
    release: asyncio.Event | None = None
    #: set the stop_event on release - i.e. model a real SIGTERM/SIGINT
    stop_on_release: bool = False

    def __init__(self, queue: Any, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.queue = queue
        type(self).captured.append(kwargs)

    async def run(self, *, stop_event: asyncio.Event | None = None, **_kw: Any) -> None:
        if type(self).entered is not None:
            type(self).entered.set()
        if type(self).release is not None:
            await type(self).release.wait()
        if type(self).stop_on_release and stop_event is not None:
            stop_event.set()
        if type(self).run_error is not None:
            raise type(self).run_error

    async def retire_expired(self) -> int:
        return 0


@pytest.fixture
def _stub_loop() -> Any:
    """Reset the recording loop and install it as the production constructor."""
    _FakeWorkerLoop.captured = []
    _FakeWorkerLoop.run_error = None
    _FakeWorkerLoop.entered = None
    _FakeWorkerLoop.release = None
    _FakeWorkerLoop.stop_on_release = False
    original_loop = mongo_worker.MongoWorkerLoop
    original_adapter = mongo_worker.MongoQueueAdapter
    original_queue = mongo_worker.get_queue
    original_context = mongo_worker._build_app_context
    original_shutdown = mongo_worker._shutdown
    original_retire = mongo_worker._retire_loop
    mongo_worker.MongoWorkerLoop = _FakeWorkerLoop  # type: ignore[misc]
    mongo_worker.MongoQueueAdapter = _StubAdapter  # type: ignore[misc]
    mongo_worker.get_queue = lambda: _StubAdapter()  # type: ignore[assignment]
    mongo_worker._build_app_context = lambda: {}  # type: ignore[assignment]

    async def _instant_retire_loop(
        queue: Any, *, interval: float, stop_event: asyncio.Event
    ) -> None:
        # The default stand-in so constructor-focused tests settle at once. The
        # lifecycle tests below install the REAL loop explicitly, because parking
        # on the stop event is the behaviour under test.
        return None

    async def _noop_shutdown() -> None:
        return None

    mongo_worker._retire_loop = _instant_retire_loop  # type: ignore[assignment]
    mongo_worker._shutdown = _noop_shutdown  # type: ignore[assignment]
    try:
        yield _FakeWorkerLoop
    finally:
        mongo_worker.MongoWorkerLoop = original_loop  # type: ignore[misc]
        mongo_worker.MongoQueueAdapter = original_adapter  # type: ignore[misc]
        mongo_worker.get_queue = original_queue  # type: ignore[assignment]
        mongo_worker._build_app_context = original_context  # type: ignore[assignment]
        mongo_worker._shutdown = original_shutdown  # type: ignore[assignment]
        mongo_worker._retire_loop = original_retire  # type: ignore[assignment]


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "queue_backend": "mongo",
        "mongo_queue_enabled": True,
        "mongo_queue_heartbeat_seconds": 4.0,
        "mongo_queue_lease_seconds": 12.0,
        "jwt_secret": "p18c-test-secret",
    }
    base.update(overrides)
    return Settings(**base)


# ----------------------------------------------------------------------
# 8. the configured poll schedule reaches the loop
# ----------------------------------------------------------------------


async def test_the_configured_poll_schedule_reaches_the_worker_loop(
    _stub_loop: Any,
) -> None:
    """``MONGO_QUEUE_POLL_SCHEDULE`` -> Settings -> ``_run`` -> ``MongoWorkerLoop``.

    Fails if ``_run()`` ever stops forwarding the setting, which is exactly the
    Phase 18B blocker.
    """
    settings = _settings(mongo_queue_poll_schedule="7,9,11")
    mongo_worker.get_settings = lambda: settings  # type: ignore[assignment]

    assert await mongo_worker._run() == 0

    assert len(_stub_loop.captured) == 1
    assert _stub_loop.captured[0].get("poll_schedule") == (7.0, 9.0, 11.0)


async def test_a_json_array_poll_schedule_also_reaches_the_worker_loop(
    _stub_loop: Any,
) -> None:
    """The documented JSON form must behave identically to the CSV form."""
    settings = _settings(mongo_queue_poll_schedule="[2.5, 4.5]")
    mongo_worker.get_settings = lambda: settings  # type: ignore[assignment]

    assert await mongo_worker._run() == 0

    assert _stub_loop.captured[0].get("poll_schedule") == (2.5, 4.5)


async def test_the_default_schedule_is_passed_through_unchanged(_stub_loop: Any) -> None:
    """With no override, the value equals the documented default.

    ``_run`` forwards whatever Settings resolved, so the default still reaches
    the loop explicitly rather than falling through to the constructor's own
    default - the two can no longer drift apart silently.
    """
    settings = _settings()
    mongo_worker.get_settings = lambda: settings  # type: ignore[assignment]

    assert await mongo_worker._run() == 0

    assert _stub_loop.captured[0].get("poll_schedule") == tuple(_DEFAULT_SCHEDULE)


async def test_the_schedule_type_is_compatible_with_the_loop_signature(
    _stub_loop: Any,
) -> None:
    """Settings yields ``list[float]``; the loop annotates ``tuple[float, ...]``.

    The conversion has to happen at the call site or mypy rejects it, and the
    values themselves must survive the ``AdaptivePoller`` copy unchanged.
    """
    from backend.queue.mongo.poller import AdaptivePoller

    settings = _settings(mongo_queue_poll_schedule="3,6")
    assert isinstance(settings.mongo_queue_poll_schedule, list)

    mongo_worker.get_settings = lambda: settings  # type: ignore[assignment]
    assert await mongo_worker._run() == 0

    forwarded = _stub_loop.captured[0].get("poll_schedule")
    assert isinstance(forwarded, tuple)
    assert all(isinstance(v, float) for v in forwarded)
    assert AdaptivePoller(forwarded)._schedule == (3.0, 6.0)


def test_settings_rejects_an_unusable_poll_schedule() -> None:
    """The single authoritative parser must keep rejecting bad values."""
    with pytest.raises(ValueError):
        _settings(mongo_queue_poll_schedule="")
    with pytest.raises(ValueError):
        _settings(mongo_queue_poll_schedule="0,5")


# ----------------------------------------------------------------------
# 9. neither loop is orphaned when the other fails
# ----------------------------------------------------------------------


async def test_a_failing_poll_loop_does_not_orphan_the_retire_loop(
    _stub_loop: Any,
) -> None:
    """A poll-loop failure must not leave the retire loop running.

    ``asyncio.gather`` without ``return_exceptions`` propagates the first
    exception immediately and leaves the sibling task running. On the old code
    nothing set ``stop_event`` on this path, so the retire loop kept issuing
    ``retire_expired()`` while ``_shutdown()`` closed the very client it used.
    """
    boom = RuntimeError("mongo went away mid-claim")
    _stub_loop.run_error = boom
    _stub_loop.release = asyncio.Event()
    _stub_loop.release.set()  # let the poll loop fail immediately

    retire_calls: list[int] = []

    async def _tracking_retire_loop(
        queue: Any, *, interval: float, stop_event: asyncio.Event
    ) -> None:
        try:
            await _real_retire_loop(queue, interval=interval, stop_event=stop_event)
        finally:
            retire_calls.append(1)

    mongo_worker._retire_loop = _tracking_retire_loop  # type: ignore[assignment]
    settings = _settings()
    mongo_worker.get_settings = lambda: settings  # type: ignore[assignment]
    try:
        with pytest.raises(RuntimeError) as excinfo:
            await mongo_worker._run()
    finally:
        mongo_worker._retire_loop = _real_retire_loop  # type: ignore[assignment]

    assert excinfo.value is boom, "the original failure must still propagate, not be hidden"
    assert retire_calls == [1], "the retire loop must be finished before shutdown runs"


async def test_both_loops_are_settled_before_shutdown_closes_resources(
    _stub_loop: Any,
) -> None:
    """Ordering proof: the retire loop is no longer running when close starts.

    Without the fix, ``_shutdown()`` could run while ``_retire_loop`` was still
    live on the shared Mongo client.
    """
    _stub_loop.run_error = RuntimeError("boom")
    _stub_loop.release = asyncio.Event()
    _stub_loop.release.set()

    live_during_shutdown: list[bool] = []
    retire_running = False

    async def _watching_retire_loop(
        queue: Any, *, interval: float, stop_event: asyncio.Event
    ) -> None:
        nonlocal retire_running
        retire_running = True
        try:
            await asyncio.sleep(0)
            await _real_retire_loop(queue, interval=interval, stop_event=stop_event)
        finally:
            retire_running = False

    async def _recording_shutdown() -> None:
        live_during_shutdown.append(retire_running)

    mongo_worker._retire_loop = _watching_retire_loop  # type: ignore[assignment]
    mongo_worker._shutdown = _recording_shutdown  # type: ignore[assignment]
    settings = _settings()
    mongo_worker.get_settings = lambda: settings  # type: ignore[assignment]
    try:
        with pytest.raises(RuntimeError):
            await mongo_worker._run()
    finally:
        pass

    assert live_during_shutdown == [False], "the retire loop outlived the shutdown barrier"


async def test_the_normal_stop_path_still_closes_after_both_loops_exit(
    _stub_loop: Any,
) -> None:
    """No regression: a clean SIGTERM-shaped stop closes exactly once, in order."""
    entered = asyncio.Event()
    release = asyncio.Event()
    _stub_loop.entered = entered
    _stub_loop.release = release
    _stub_loop.stop_on_release = True  # a real SIGTERM sets the event

    order: list[str] = []

    async def _ordered_retire_loop(
        queue: Any, *, interval: float, stop_event: asyncio.Event
    ) -> None:
        await _real_retire_loop(queue, interval=interval, stop_event=stop_event)
        order.append("retire_done")

    async def _recording_shutdown() -> None:
        order.append("shutdown")

    mongo_worker._retire_loop = _ordered_retire_loop  # type: ignore[assignment]
    mongo_worker._shutdown = _recording_shutdown  # type: ignore[assignment]
    settings = _settings()
    mongo_worker.get_settings = lambda: settings  # type: ignore[assignment]

    task = asyncio.create_task(mongo_worker._run())
    await asyncio.wait_for(entered.wait(), timeout=5.0)
    release.set()  # the poll loop returns cleanly, as a stop_event would cause

    assert await asyncio.wait_for(task, timeout=5.0) == 0
    assert order == ["retire_done", "shutdown"]


def test_the_worker_refuses_to_run_under_another_backend() -> None:
    """The fail-loud gate must survive the Phase 18C edits."""
    original = mongo_worker.get_settings
    mongo_worker.get_settings = lambda: SimpleNamespace(queue_backend="arq")  # type: ignore[assignment]
    try:
        with pytest.raises(SystemExit):
            asyncio.run(mongo_worker._run())
    finally:
        mongo_worker.get_settings = original  # type: ignore[assignment]
