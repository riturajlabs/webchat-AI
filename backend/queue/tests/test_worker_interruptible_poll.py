"""Phase 18C - interruptible idle polling in ``MongoWorkerLoop.run``.

Phase 18B measured an idle Mongo worker taking 5.7-10.7 s to die after a real
SIGTERM, and a real container exiting ``137`` under ``docker stop -t 10``. Root
cause: the poll wait was ``await self._sleep(interval)``, a plain
``asyncio.sleep`` that ``stop_event`` cannot interrupt, so the signal was only
observed when the current poll slot elapsed.

These tests pin the fixed contract:

* an idle loop stops **promptly** when ``stop_event`` is set;
* the poll interval is still the authoritative duration (a stop signal can only
  shorten a wait, never lengthen it, and never change normal polling);
* a handler that is already running is never cancelled by the stop signal, and
  its heartbeat keeps renewing the lease while it drains;
* a failure inside the wait is re-raised, not swallowed.

Everything here is deterministic and Mongo-free: the loop's ``sleep`` is
injected, so no test waits on a real 30-second poll interval, no test asserts on
a wall-clock deadline, and the suite runs even with no mongod available. A real
lease/fence regression for the in-flight SIGKILL path lives in
``test_worker_loop.py`` and is unchanged.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from backend.queue.protocol import QueueJob
from backend.queue.worker import MongoWorkerLoop

_TENANT = "tenant-p18c"
_FUNCTION = "ping"


class _PumpingClock:
    """Deterministic stand-in for the loop's injected ``sleep``.

    Every requested duration is recorded, then the call parks until the test
    calls :meth:`advance`. Nothing consults the wall clock, so a test can sit in
    a "30 second" poll slot for as long as it likes and still finish instantly.
    """

    def __init__(self) -> None:
        self.requested: list[float] = []
        self._arrivals = 0
        self._arrived = asyncio.Event()
        self._gates: asyncio.Queue[asyncio.Event] = asyncio.Queue()

    async def __call__(self, seconds: float) -> None:
        self.requested.append(seconds)
        self._arrivals += 1
        self._arrived.set()
        gate = asyncio.Event()
        await self._gates.put(gate)
        await gate.wait()

    async def wait_for_arrival(self) -> None:
        """Block until the sleep has been called at least once more than on entry."""
        target = self._arrivals
        while self._arrivals <= target:
            self._arrived.clear()
            if self._arrivals > target:
                return
            await asyncio.wait_for(self._arrived.wait(), timeout=5.0)

    async def advance(self) -> None:
        gate = await asyncio.wait_for(self._gates.get(), timeout=5.0)
        gate.set()


class _RecordingClock:
    """Records every requested duration and returns immediately.

    Used where a handler is executing, because the heartbeat shares the same
    injected ``sleep`` and needs to keep ticking while the test holds the
    handler open.
    """

    def __init__(self) -> None:
        self.requested: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.requested.append(seconds)
        await asyncio.sleep(0)


class _FakeQueue:
    """Minimal in-memory ``WorkerQueue`` for the poll-loop contract.

    Implements only what ``MongoWorkerLoop`` calls, and records every claim so a
    test can assert that stopping during an idle wait takes no further work.
    """

    queue_name = "fake:queue"

    def __init__(self, jobs: list[QueueJob] | None = None) -> None:
        self._jobs = list(jobs or [])
        self.claims = 0
        self.completions: list[tuple[str, str, int]] = []
        self.heartbeats: list[tuple[str, str, int | None]] = []
        self.retired = 0

    async def enqueue(
        self,
        function: str,
        *,
        payload: dict[str, Any] | None = None,
        tenant_id: str = "",
        dedup_key: str | None = None,
        defer_by: float | None = None,
        job_id: str | None = None,
        max_tries: int | None = None,
    ) -> str:
        """Never called by the poll loop; present so the fake satisfies WorkerQueue."""
        raise AssertionError("the poll loop must not enqueue")

    async def claim(self, worker_id: str) -> QueueJob | None:
        self.claims += 1
        return self._jobs.pop(0) if self._jobs else None

    async def heartbeat(
        self, job_id: str, worker_id: str, *, execution_version: int | None = None
    ) -> bool:
        self.heartbeats.append((job_id, worker_id, execution_version))
        return True

    async def complete(
        self, job_id: str, worker_id: str, *, execution_version: int, result: Any = None
    ) -> bool:
        self.completions.append((job_id, worker_id, execution_version))
        return True

    async def fail(
        self,
        job_id: str,
        worker_id: str,
        *,
        execution_version: int,
        error: str,
        retry: bool = True,
    ) -> str:
        return "failed"

    async def retire_expired(self) -> int:
        self.retired += 1
        return 0

    async def ping(self) -> bool:
        return True


def _job(job_id: str = "job-1", *, job_try: int = 1) -> QueueJob:
    from backend.queue.mongo.ids import utcnow

    now = utcnow()
    return QueueJob(
        id=job_id,
        function=_FUNCTION,
        payload={},
        tenant_id=_TENANT,
        job_try=job_try,
        max_tries=3,
        execution_version=1,
        enqueue_time=now,
        score=now,
    )


# ----------------------------------------------------------------------
# 1 + 2. an idle loop stops promptly, without waiting out the poll interval
# ----------------------------------------------------------------------


async def test_idle_loop_returns_promptly_when_the_stop_event_is_set() -> None:
    """The regression itself.

    The injected clock parks forever inside a 30 s poll slot, so the *only* way
    out of the wait is ``stop_event``. Under the pre-18C ``await self._sleep(...)
    this deadlocks and the guard below fires. ``timeout=`` is a deadlock tripwire,
    not the assertion: the assertion is that the loop returned while the
    requested 30 s sleep never completed.
    """
    clock = _PumpingClock()
    queue = _FakeQueue()
    stop = asyncio.Event()
    loop = MongoWorkerLoop(queue, worker_id="w", poll_schedule=(30.0,), sleep=clock)

    task = asyncio.create_task(loop.run(stop_event=stop))
    await clock.wait_for_arrival()  # the loop is now parked inside its 30 s idle wait

    stop.set()
    await asyncio.wait_for(task, timeout=5.0)  # would hang on the old code

    # The configured interval is still what was asked for, and the wait ended
    # without the sleep ever completing (this test never calls advance()).
    assert clock.requested == [30.0]


async def test_a_set_stop_event_does_not_claim_another_job() -> None:
    """Falsification of a "stop but keep polling" regression.

    ``stop_event`` is already set before ``run()`` starts, so the loop body must
    never execute - one claim would be a violation.
    """
    clock = _PumpingClock()
    queue = _FakeQueue([_job("job-1"), _job("job-2")])
    stop = asyncio.Event()
    stop.set()
    loop = MongoWorkerLoop(queue, worker_id="w", poll_schedule=(30.0,), sleep=clock)

    await asyncio.wait_for(loop.run(stop_event=stop), timeout=5.0)

    assert queue.claims == 0
    assert clock.requested == []


# ----------------------------------------------------------------------
# 3. a wait that times out keeps the adaptive schedule advancing
# ----------------------------------------------------------------------


async def test_a_timed_out_wait_keeps_the_adaptive_schedule_advancing() -> None:
    """Normal production polling must be unchanged by the fix.

    The queue is empty, so every poll is idle and ``AdaptivePoller`` walks its
    schedule. The recorded durations must be exactly the configured slots - proof
    that replacing the sleep did not change the cadence.
    """
    clock = _PumpingClock()
    queue = _FakeQueue()
    stop = asyncio.Event()
    loop = MongoWorkerLoop(
        queue, worker_id="w", poll_schedule=(1.0, 2.0, 5.0, 10.0, 30.0), sleep=clock
    )

    task = asyncio.create_task(loop.run(stop_event=stop))
    for _ in range(7):
        await clock.wait_for_arrival()
        await clock.advance()

    stop.set()
    await asyncio.wait_for(task, timeout=5.0)

    # 1 -> 2 -> 5 -> 10 -> 30 -> 30 -> 30 (capped at the last slot)
    assert clock.requested == [1.0, 2.0, 5.0, 10.0, 30.0, 30.0, 30.0]
    assert queue.claims == 7, "one claim per completed poll, no busy-looping"


async def test_the_configured_schedule_replaces_the_loop_default() -> None:
    """A non-default schedule must be honoured, not silently replaced."""
    clock = _PumpingClock()
    queue = _FakeQueue()
    stop = asyncio.Event()
    loop = MongoWorkerLoop(queue, worker_id="w", poll_schedule=(7.0, 9.0), sleep=clock)

    task = asyncio.create_task(loop.run(stop_event=stop))
    for _ in range(3):
        await clock.wait_for_arrival()
        await clock.advance()
    stop.set()
    await asyncio.wait_for(task, timeout=5.0)

    assert clock.requested == [7.0, 9.0, 9.0]


# ----------------------------------------------------------------------
# 4. stopping during an idle wait takes no further work
# ----------------------------------------------------------------------


async def test_stopping_during_an_idle_wait_claims_no_further_job() -> None:
    """One job is consumed, then the loop parks; the stop must end it there.

    The stop is raised while the loop sits in the post-work idle wait, so a
    second claim would mean the signal was ignored.
    """
    clock = _PumpingClock()
    queue = _FakeQueue([_job("job-1"), _job("job-2")])
    stop = asyncio.Event()

    async def _handler(_ctx: dict[str, Any], *_: Any) -> dict[str, Any]:
        return {"ok": True}

    loop = MongoWorkerLoop(
        queue,
        worker_id="w",
        handlers={_FUNCTION: _handler},
        poll_schedule=(30.0,),
        sleep=clock,
    )

    task = asyncio.create_task(loop.run(stop_event=stop))
    # claim 1 -> job-1 runs -> idle wait (schedule[0]); claim 2 -> job-2 ...
    await clock.wait_for_arrival()
    assert queue.claims == 1
    assert [c[0] for c in queue.completions] == ["job-1"]

    stop.set()
    await asyncio.wait_for(task, timeout=5.0)

    assert queue.claims == 1, "the stop landed during the idle wait, before a second claim"
    assert [c[0] for c in queue.completions] == ["job-1"]


# ----------------------------------------------------------------------
# 5 + 6. a running handler is never cancelled, and keeps its heartbeat
# ----------------------------------------------------------------------


async def test_a_running_handler_is_not_cancelled_by_the_stop_event() -> None:
    """SIGTERM must not cancel the job; the handler still runs to completion.

    ARQ parity: a stop signal stops the *poll* loop, it does not abandon claimed
    work. The handler is released after the stop and must still write its
    terminal state.
    """
    clock = _RecordingClock()
    queue = _FakeQueue([_job("job-1")])
    stop = asyncio.Event()
    started = asyncio.Event()
    release = asyncio.Event()
    cancelled = False

    async def _handler(_ctx: dict[str, Any], *_: Any) -> dict[str, Any]:
        nonlocal cancelled
        started.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled = True
            raise
        return {"ok": True}

    loop = MongoWorkerLoop(
        queue,
        worker_id="w",
        handlers={_FUNCTION: _handler},
        poll_schedule=(30.0,),
        sleep=clock,
    )

    task = asyncio.create_task(loop.run(stop_event=stop))
    await asyncio.wait_for(started.wait(), timeout=5.0)

    stop.set()  # arrives while the handler is mid-flight
    await asyncio.sleep(0)  # give the loop every chance to react wrongly
    assert not task.done(), "the loop must stay alive while the job drains"
    assert not cancelled

    release.set()
    await asyncio.wait_for(task, timeout=5.0)

    assert cancelled is False
    assert [c[0] for c in queue.completions] == ["job-1"]
    assert queue.claims == 1


async def test_the_heartbeat_keeps_renewing_while_a_handler_drains_after_stop() -> None:
    """The lease must survive the drain, or a second worker steals the job.

    The heartbeat shares the loop's injected ``sleep``; it is the record of
    renewals that matters here, since the row itself is a real-Mongo concern
    covered by ``test_worker_loop.py``.
    """
    clock = _RecordingClock()
    queue = _FakeQueue([_job("job-1")])
    stop = asyncio.Event()
    started = asyncio.Event()
    release = asyncio.Event()

    async def _handler(_ctx: dict[str, Any], *_: Any) -> dict[str, Any]:
        started.set()
        await release.wait()
        return {"ok": True}

    loop = MongoWorkerLoop(
        queue,
        worker_id="w",
        handlers={_FUNCTION: _handler},
        poll_schedule=(30.0,),
        heartbeat_seconds=0.001,
        sleep=clock,
    )

    task = asyncio.create_task(loop.run(stop_event=stop))
    await asyncio.wait_for(started.wait(), timeout=5.0)
    stop.set()
    await asyncio.sleep(0.01)  # let the heartbeat tick a few times post-stop

    renewed_while_draining = len(queue.heartbeats)
    assert renewed_while_draining > 0, "the lease must keep renewing during the drain"

    release.set()
    await asyncio.wait_for(task, timeout=5.0)

    assert queue.completions == [("job-1", "w", 1)]
    assert len(queue.heartbeats) >= renewed_while_draining
    # the heartbeat stopped when the execution finished
    settled = len(queue.heartbeats)
    await asyncio.sleep(0.01)
    assert len(queue.heartbeats) == settled


# ----------------------------------------------------------------------
# 7. the wait must not swallow failures
# ----------------------------------------------------------------------


async def test_a_sleep_failure_is_not_swallowed() -> None:
    """``asyncio.wait`` stores a child's exception instead of raising it.

    A bare ``asyncio.wait`` would leave the failure sitting on the task and the
    worker would look healthy, so the loop must re-raise it.
    """
    boom = RuntimeError("clock exploded")

    async def _exploding_sleep(_seconds: float) -> None:
        raise boom

    queue = _FakeQueue()
    stop = asyncio.Event()
    loop = MongoWorkerLoop(queue, worker_id="w", sleep=_exploding_sleep)

    with pytest.raises(RuntimeError) as excinfo:
        await asyncio.wait_for(loop.run(stop_event=stop), timeout=5.0)

    assert excinfo.value is boom


async def test_a_stop_event_wins_without_waiting_for_the_sleep_to_fail() -> None:
    """A cancelled sleep must not surface as an error on the shutdown path.

    Counterpart to the test above: when the stop signal wins the race the sleep
    task is cancelled on purpose, and that cancellation must stay silent.
    """

    async def _never(_seconds: float) -> None:
        await asyncio.Event().wait()  # parks forever

    queue = _FakeQueue()
    stop = asyncio.Event()
    loop = MongoWorkerLoop(queue, worker_id="w", poll_schedule=(30.0,), sleep=_never)

    task = asyncio.create_task(loop.run(stop_event=stop))
    await asyncio.sleep(0)  # let the loop reach the parked sleep
    await asyncio.sleep(0)
    stop.set()

    await asyncio.wait_for(task, timeout=5.0)  # a raised CancelledError would fail here
