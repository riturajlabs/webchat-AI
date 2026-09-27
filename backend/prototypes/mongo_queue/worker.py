"""Prototype worker: claim -> lease-heartbeat -> run handler -> complete/fail.

Mimics the production ARQ worker's contract (run a registered ``function``,
bounded by max_tries, timeout-shaped leases, per-job execution context) but
entirely on the Mongo queue and without importing any production worker code.

The execution context (``JobContext``) carries ``tenant_id`` so a job's tenant
travels with it from enqueue through execution - the same guarantee the
production worker gets from `payload["tenant_id"]`.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from backend.prototypes.mongo_queue.config import QueueConfig
from backend.prototypes.mongo_queue.ids import new_worker_id, utcnow
from backend.prototypes.mongo_queue.models import STATUS_COMPLETED, Job
from backend.prototypes.mongo_queue.poller import AdaptivePoller
from backend.prototypes.mongo_queue.queue import MongoQueue

logger = logging.getLogger("webchat_ai.mongo_queue_prototype")

Handler = Callable[[dict[str, Any], "JobContext"], Awaitable[Any]]
SleepFn = Callable[[float], Awaitable[None]]


@dataclass(frozen=True)
class JobContext:
    """Per-execution context handed to a handler (mirrors log_context)."""

    job_id: str
    function: str
    tenant_id: str
    worker_id: str
    job_try: int
    execution_version: int
    claimed_at: datetime


@dataclass(frozen=True)
class WorkOutcome:
    """Result of one claimed job execution."""

    job_id: str
    function: str
    status: str
    attempts: int
    execution_version: int
    lease_lost: bool = False


class PrototypeWorker:
    """A single worker poller over the Mongo queue."""

    def __init__(
        self,
        queue: MongoQueue,
        config: QueueConfig,
        *,
        worker_id: str | None = None,
        handlers: dict[str, Handler] | None = None,
    ) -> None:
        self._queue = queue
        self._config = config
        self._worker_id = worker_id or new_worker_id()
        self._handlers = handlers or {}
        self._poller = AdaptivePoller(config.poll_schedule)

    @property
    def worker_id(self) -> str:
        return self._worker_id

    @property
    def poller(self) -> AdaptivePoller:
        return self._poller

    async def work_once(
        self,
        *,
        now: datetime | None = None,
        sleep: SleepFn | None = None,
    ) -> WorkOutcome | None:
        """Claim one job and run it to completion/failure (or None if idle)."""
        job = await self._queue.claim(self._worker_id, now=now)
        if job is None:
            return None
        return await self._execute(job, sleep=sleep)

    async def run(
        self,
        *,
        sleep: SleepFn | None = None,
        stop_after_seconds: float | None = None,
        stop_event: asyncio.Event | None = None,
    ) -> None:
        """Continuous poll loop with adaptive idle backoff.

        No per-iteration DB command occurs while sleeping: only a claim on
        wake. This is what eliminates the ~172,800-ops/day idle ARQ behaviour.
        """
        sleep_fn = sleep if sleep is not None else asyncio.sleep
        if stop_after_seconds is not None:
            stop_event = stop_event or asyncio.Event()

            async def _timer() -> None:
                await sleep_fn(stop_after_seconds)
                if stop_event is not None:
                    stop_event.set()

            timer = asyncio.create_task(_timer())
        else:
            timer = None
        try:
            while stop_event is None or not stop_event.is_set():
                outcome = await self.work_once()
                interval = self._poller.nick(outcome is not None)
                await sleep_fn(interval)
        finally:
            if timer is not None:
                timer.cancel()

    async def _execute(
        self,
        job: Job,
        *,
        sleep: SleepFn | None = None,
    ) -> WorkOutcome:
        handler = self._handlers.get(job.function)
        if handler is None:
            status = await self._queue.fail_job(
                job.id,
                self._worker_id,
                f"no handler registered for function '{job.function}'",
                execution_version=job.execution_version,
            )
            return WorkOutcome(
                job_id=job.id,
                function=job.function,
                status=status,
                attempts=job.attempts,
                execution_version=job.execution_version,
            )
        ctx = JobContext(
            job_id=job.id,
            function=job.function,
            tenant_id=job.tenant_id,
            worker_id=self._worker_id,
            job_try=job.attempts,
            execution_version=job.execution_version,
            claimed_at=job.started_at or utcnow(),
        )
        lease_lost = asyncio.Event()
        heartbeat = asyncio.create_task(self._heartbeat_loop(job.id, ctx, lease_lost, sleep=sleep))
        try:
            result = await handler(job.payload, ctx)
        except Exception as exc:  # noqa: BLE001 - prototype records and retries
            status = await self._queue.fail_job(
                job.id,
                self._worker_id,
                f"{type(exc).__name__}: {exc}",
                execution_version=ctx.execution_version,
            )
            return WorkOutcome(job.id, job.function, status, job.attempts, ctx.execution_version)
        finally:
            lease_lost.set()
            heartbeat.cancel()
        completed = await self._queue.complete_job(
            job.id,
            self._worker_id,
            execution_version=ctx.execution_version,
            result=result,
        )
        if not completed:
            logger.warning(
                "completion_rejected function=%s job=%s worker=%s version=%s",
                job.function,
                job.id,
                self._worker_id,
                ctx.execution_version,
            )
        return WorkOutcome(
            job.id,
            job.function,
            STATUS_COMPLETED,
            job.attempts,
            ctx.execution_version,
        )

    async def _heartbeat_loop(
        self,
        job_id: str,
        ctx: JobContext,
        lease_lost: asyncio.Event,
        *,
        sleep: SleepFn | None,
    ) -> None:
        """Renew the lease while the handler runs (ownership-checked)."""
        sleep_fn = sleep if sleep is not None else asyncio.sleep
        while not lease_lost.is_set():
            await sleep_fn(self._config.heartbeat_interval_seconds)
            if lease_lost.is_set():
                return
            renewed = await self._queue.renew_lease(job_id, self._worker_id)
            if not renewed:
                logger.warning(
                    "lease_renewal_rejected job=%s worker=%s version=%s",
                    job_id,
                    self._worker_id,
                    ctx.execution_version,
                )
