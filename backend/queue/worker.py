"""Mongo worker loop (Phase 17A, opt-in, not wired into any entrypoint).

A production-shaped consumer for the MongoDB queue: claim -> lease heartbeat ->
dispatch the registered production coroutine with an ARQ-shaped context ->
complete/fail under the measured ARQ retry policy.

ARQ remains the production consumer (``python -m backend.workers``). This loop
is the explicit opt-in Mongo-mode consumer an operator would run with
``QUEUE_BACKEND=mongo``. Tests inject fake handlers, so nothing here ever
executes real side effects.

Retry / timeout mapping (measured on arq 0.28 by running a real worker with the
production ``WorkerSettings`` shape - max_tries=3, job_timeout=600,
retry_jobs=True; see report section 8):

===========================  ========  ==================================
raised inside the job        retried?  mapped to
===========================  ========  ==================================
success                      -         complete()
ordinary exception           NO        fail(retry=False) -> dead
job timeout (wait_for)       NO        fail(retry=False) -> dead
``arq.worker.Retry``         YES       fail(retry=True)  -> retry_pending
``RetryJob``                 YES       fail(retry=True)  -> retry_pending
job-raised CancelledError    YES       fail(retry=True)  -> retry_pending
===========================  ========  ==================================

The non-obvious rows are the first three: under arq 0.28 ``max_tries=3`` is
unreachable for an ordinary exception or a job timeout, so introducing retries
for them would silently change production crawl/quota behaviour. A job timeout
surfaces here as ``JobTimeoutError`` (ARQ raises the builtin ``TimeoutError``)
and is terminal, exactly as under ARQ; the crawl domain row is still finalized
by ``crawl_website``'s own ``CancelledError`` handler before that, because
``asyncio.wait_for`` cancels the job before raising.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from backend.queue.errors import JobTimeoutError
from backend.queue.mongo.ids import new_worker_id
from backend.queue.mongo.poller import AdaptivePoller
from backend.queue.protocol import QueueJob, WorkerQueue, job_context
from backend.queue.registry import (
    args_from_payload,
    job_timeout_seconds,
    validate_function,
)
from backend.queue.registry import (
    resolve as resolve_registered,
)

logger = logging.getLogger("webchat_ai.mongo_queue")

Handler = Callable[..., Awaitable[Any]]
SleepFn = Callable[[float], Awaitable[None]]

_NOT_OWNED = "not_owned"


@dataclass(frozen=True)
class WorkOutcome:
    """Result of one claimed job execution."""

    job_id: str
    function: str
    status: str
    attempts: int
    execution_version: int
    lease_lost: bool = False


class MongoWorkerLoop:
    """A single opt-in worker poller over the Mongo queue."""

    def __init__(
        self,
        queue: WorkerQueue,
        *,
        worker_id: str | None = None,
        handlers: dict[str, Handler] | None = None,
        poll_schedule: tuple[float, ...] = (1.0, 2.0, 5.0, 10.0, 30.0),
        heartbeat_seconds: float = 30.0,
        sleep: SleepFn | None = None,
    ) -> None:
        self._queue = queue
        self._worker_id = worker_id if worker_id is not None else new_worker_id()
        self._handlers = handlers or {}
        self._poller = AdaptivePoller(poll_schedule)
        self._heartbeat_seconds = heartbeat_seconds
        self._sleep = sleep if sleep is not None else asyncio.sleep

    @property
    def worker_id(self) -> str:
        return self._worker_id

    async def work_once(self) -> WorkOutcome | None:
        """Claim one job and run it to completion/failure (``None`` if idle)."""
        job = await self._queue.claim(self._worker_id)
        if job is None:
            return None
        return await self._execute(job)

    async def run(
        self,
        *,
        stop_event: asyncio.Event | None = None,
        stop_after_seconds: float | None = None,
    ) -> None:
        """Continuous adaptive-poll loop (no DB commands while idle)."""
        timer: asyncio.Task[None] | None = None
        if stop_after_seconds is not None:
            stop_event = stop_event or asyncio.Event()

            async def _timer() -> None:
                await self._sleep(stop_after_seconds)
                stop_event.set()

            timer = asyncio.create_task(_timer())
        try:
            while stop_event is None or not stop_event.is_set():
                outcome = await self.work_once()
                interval = self._poller.nick(outcome is not None)
                await self._sleep(interval)
        finally:
            if timer is not None:
                timer.cancel()

    # ------------------------------------------------------------------

    def _handler_for(self, function: str) -> Handler | None:
        """Return the coroutine to run, or ``None`` for an unknown function.

        An unregistered name is dead-lettered rather than executed: the registry
        is closed, so an unknown name is a poisoned or hand-edited queue row and
        must never reach an import or a call.
        """
        if function in self._handlers:
            return self._handlers[function]
        try:
            validate_function(function)
            return resolve_registered(function)
        except Exception:  # noqa: BLE001 - registry rejects unknown names safely
            logger.warning(
                "mongo_queue_unknown_function worker=%s function=%s",
                self._worker_id,
                function,
            )
            return None

    async def _execute(self, job: QueueJob) -> WorkOutcome:
        handler = self._handler_for(job.function)
        if handler is None:
            status = await self._queue.fail(
                job.id,
                self._worker_id,
                error=f"no handler registered for function '{job.function}'",
                execution_version=job.execution_version,
                retry=False,
            )
            return WorkOutcome(
                job_id=job.id,
                function=job.function,
                status=status,
                attempts=job.job_try,
                execution_version=job.execution_version,
            )

        args = args_from_payload(job.function, dict(job.payload))
        timeout = job_timeout_seconds(job.function)
        ctx = job_context(
            job,
            timeout=timeout,
            queue_name=getattr(self._queue, "queue_name", "arq:queue"),
            # Phase 17B: hand the job the very queue it is executing on, so any
            # child it enqueues is routed back onto this backend instead of a
            # hard-wired ARQ/Redis call (split-brain guard).
            queue=self._queue,
        )

        lease_lost = asyncio.Event()
        heartbeat = asyncio.create_task(
            self._heartbeat_loop(job.id, job.execution_version, lease_lost)
        )
        result: Any = None
        try:
            try:
                result = await asyncio.wait_for(handler(ctx, *args), timeout=timeout)
            except (asyncio.CancelledError, TimeoutError) as exc:
                # ARQ parity, both terminal-or-retry decided below:
                #  * `asyncio.CancelledError` reaching us means the JOB raised
                #    it (ARQ retries that), or the worker itself was cancelled.
                #  * `TimeoutError` (and its alias `asyncio.TimeoutError`) is
                #    what `asyncio.wait_for` raises when the function-level
                #    timeout fires - ARQ treats that as terminal, no retry.
                #    `crawl_website` has already finalized its domain row in
                #    its own CancelledError handler before we get here.
                is_job_timeout = not isinstance(exc, asyncio.CancelledError)
                status = await self._queue.fail(
                    job.id,
                    self._worker_id,
                    error=(
                        f"{type(exc).__name__}: job timeout after {timeout}s"
                        if is_job_timeout
                        else "cancelled"
                    ),
                    execution_version=job.execution_version,
                    retry=not is_job_timeout,
                )
                return WorkOutcome(
                    job_id=job.id,
                    function=job.function,
                    status=status,
                    attempts=job.job_try,
                    execution_version=job.execution_version,
                )
            except JobTimeoutError as exc:
                status = await self._queue.fail(
                    job.id,
                    self._worker_id,
                    error=f"JobTimeoutError: {exc}",
                    execution_version=job.execution_version,
                    retry=False,
                )
                return WorkOutcome(
                    job_id=job.id,
                    function=job.function,
                    status=status,
                    attempts=job.job_try,
                    execution_version=job.execution_version,
                )
            except Exception as exc:  # noqa: BLE001 - ARQ parity: ordinary exception
                # ARQ 0.28 dead-letters an ordinary exception on the first
                # attempt; it does NOT consume the max_tries budget.
                status = await self._queue.fail(
                    job.id,
                    self._worker_id,
                    error=f"{type(exc).__name__}: {exc}",
                    execution_version=job.execution_version,
                    retry=False,
                )
                return WorkOutcome(
                    job_id=job.id,
                    function=job.function,
                    status=status,
                    attempts=job.job_try,
                    execution_version=job.execution_version,
                )
        finally:
            lease_lost.set()
            heartbeat.cancel()
            try:
                await heartbeat
            except asyncio.CancelledError:
                pass

        completed = await self._queue.complete(
            job.id,
            self._worker_id,
            execution_version=job.execution_version,
            result=result,
        )
        if not completed:
            logger.warning(
                "mongo_queue_completion_rejected worker=%s job=%s function=%s version=%s",
                self._worker_id,
                job.id,
                job.function,
                job.execution_version,
            )
            return WorkOutcome(
                job_id=job.id,
                function=job.function,
                status=_NOT_OWNED,
                attempts=job.job_try,
                execution_version=job.execution_version,
                lease_lost=True,
            )
        return WorkOutcome(
            job_id=job.id,
            function=job.function,
            status="completed",
            attempts=job.job_try,
            execution_version=job.execution_version,
        )

    async def _heartbeat_loop(
        self, job_id: str, execution_version: int, lease_lost: asyncio.Event
    ) -> None:
        """Renew the lease while the handler runs (ownership-checked).

        The renewal carries the execution's fencing token, not just the worker
        id. Without it, a worker that reclaims its *own* expired job under the
        same id would let the stale execution keep extending the new
        execution's lease - a stall that no completion could ever clear.
        """
        while not lease_lost.is_set():
            await self._sleep(self._heartbeat_seconds)
            if lease_lost.is_set():
                return
            renewed = await self._queue.heartbeat(
                job_id, self._worker_id, execution_version=execution_version
            )
            if not renewed:
                logger.warning(
                    "mongo_queue_lease_renewal_rejected worker=%s job=%s version=%s",
                    self._worker_id,
                    job_id,
                    execution_version,
                )


__all__ = ["MongoWorkerLoop", "WorkOutcome"]
