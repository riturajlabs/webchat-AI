"""Mongo queue worker entrypoint (Phase 18A, opt-in).

The consumer ``python -m backend.workers`` runs when ``QUEUE_BACKEND=mongo``
(``MONGO_QUEUE_ENABLED=true`` enforced at ``Settings`` build): the cousin of
``backend.workers.app`` for the Mongo backend, wiring the same production job
coroutines and the same process-level services onto :class:`MongoWorkerLoop`.

Guarantees:

* fail-loud: this module MUST only ever run under ``QUEUE_BACKEND=mongo`` - if
  it is invoked under ARQ, it exits with an explicit error instead of silently
  starting a second consumer against the wrong backend.
* crash recovery is scheduled: ``retire_expired`` runs once at boot and then on
  a bounded heartbeat cadence, so a worker that died mid-job cannot strand work
  until another worker happens to poll.
* graceful shutdown: SIGINT/SIGTERM stop the poll loop and the retire loop,
  then release the browser, the shared ``MongoDB`` client and Redis - each
  independently, so one close failure never blocks the others.
* no ARQ connection is ever built: the ``arq`` package stays importable (the
  factory has to be able to build an ARQ adapter), but this process neither
  connects to Redis nor consumes an ARQ queue. ``_build_app_context`` is
  synchronous and opens no socket - the embedding client and
  ``ProviderHealthStore`` are built lazily over the shared Redis getter - and
  the sole Redis usage is the shared client released at shutdown.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from typing import Any

from backend.ai.registry import build_ingestion_embedding_client
from backend.core.config import get_settings
from backend.core.database import MongoDB
from backend.core.logging import attach_sensitive_data_filter, configure_logging
from backend.core.redis import close_redis, get_redis
from backend.queue.factory import get_queue
from backend.queue.mongo_adapter import MongoQueueAdapter
from backend.queue.protocol import WorkerQueue
from backend.queue.worker import MongoWorkerLoop
from backend.services.ai.provider_health import ProviderHealthStore
from backend.services.ingestion.browser import close_browser
from backend.workers.app import _log_resource_caps

logger = logging.getLogger("webchat_ai")

# Floor for the crash-recovery sweep cadence. The sweep is a single indexed
# query, so it is cheap, but it must never become a busy loop on a tiny
# heartbeat setting.
_RETIRE_INTERVAL_FLOOR_SECONDS = 5.0


def _build_app_context() -> dict[str, Any]:
    """Process-level services the Mongo worker hands every job.

    Mirrors the ARQ worker's startup context (``backend.workers.app.startup``):
    shared app name, one embedding client for the whole process (Phase 9/ADR-009:
    never switch embedding spaces mid-corpus), and one embedding provider-health
    store kept separate from generation health.

    Synchronous and connection-safe by construction - neither the embedding
    client nor ``ProviderHealthStore`` opens a socket at construction, so an
    API/Redis outage cannot block worker boot (the §12 Redis-outage guarantee).
    """
    settings = get_settings()
    return {
        "app_name": settings.app_name,
        "embedding_client": build_ingestion_embedding_client(),
        "embedding_provider_health": ProviderHealthStore(get_redis()),
    }


async def _run() -> int:
    """Event-loop body: boot, run both loops, shut down cleanly."""
    settings = get_settings()
    if settings.queue_backend.strip().lower() != "mongo":
        # Fail-loud: never start a Mongo consumer under another backend.
        raise SystemExit(
            f"Mongo worker requested via backend.workers.mongo but "
            f"QUEUE_BACKEND={settings.queue_backend!r}; run the ARQ entrypoint "
            "(python -m backend.workers) or set QUEUE_BACKEND=mongo + "
            "MONGO_QUEUE_ENABLED=true."
        )

    queue = get_queue()
    if not isinstance(queue, MongoQueueAdapter):
        # Fail-loud second gate: the backend says mongo but the factory produced
        # something else, so this process must not consume it.
        raise SystemExit(
            f"QUEUE_BACKEND=mongo did not yield a Mongo queue adapter (got "
            f"{type(queue).__name__}); refusing to start the Mongo worker."
        )
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    installed: list[signal.Signals] = []
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
            installed.append(sig)
        except (NotImplementedError, RuntimeError):
            # Non-POSIX hosts / closed loop: polling still stops via the event.
            pass

    try:
        # Indexes first: a brand-new queue database has no claim/scan index,
        # and no worker may race one before the schema is in place.
        await queue.ensure_indexes()
        await _retire_initial(queue)

        worker = MongoWorkerLoop(
            queue,
            # Phase 18C: honour MONGO_QUEUE_POLL_SCHEDULE. Without this the loop
            # silently used its own hardcoded default (1, 2, 5, 10, 30) and the
            # configured cadence was ignored in production. `tuple(...)` matches
            # the loop's `tuple[float, ...]` signature; AdaptivePoller validates
            # the values itself, and Settings already rejects an empty or
            # non-positive schedule, so there is still exactly one parser.
            poll_schedule=tuple(settings.mongo_queue_poll_schedule),
            heartbeat_seconds=settings.mongo_queue_heartbeat_seconds,
            app_context=_build_app_context(),
        )
        # Phase 18C: the two loops run as explicit tasks so a failure in one cannot
        # orphan the other. A bare `asyncio.gather(...)` propagates the first
        # exception immediately and leaves the sibling running, and on this error
        # path nothing ever sets `stop_event` - so the retire loop kept issuing
        # `retire_expired` against a MongoDB client that `_shutdown()` was
        # concurrently closing. The `finally` below stops and awaits both tasks
        # before anything is closed, and re-raises the original failure.
        worker_task = asyncio.create_task(worker.run(stop_event=stop_event))
        retire_task = asyncio.create_task(
            _retire_loop(
                queue,
                interval=max(
                    settings.mongo_queue_heartbeat_seconds, _RETIRE_INTERVAL_FLOOR_SECONDS
                ),
                stop_event=stop_event,
            )
        )
        try:
            await asyncio.gather(worker_task, retire_task)
        finally:
            stop_event.set()
            for task in (worker_task, retire_task):
                if not task.done():
                    task.cancel()
            # return_exceptions: the survivor is already being torn down, so its
            # result is drained rather than discarded or re-raised over the
            # failure that got us here.
            await asyncio.gather(worker_task, retire_task, return_exceptions=True)
            await _shutdown()
    finally:
        for sig in installed:
            try:
                loop.remove_signal_handler(sig)
            except NotImplementedError:
                pass
    return 0


async def _retire_initial(queue: WorkerQueue) -> None:
    """One bounded crash-recovery sweep before the first claim.

    A previous single worker can leave an expired lease behind after the
    deployment restarts; recovering it at boot (before any new claim) keeps the
    at-least-once guarantee from waiting on the first heartbeat interval.
    Best-effort: a store outage here must not prevent the worker from starting.
    """
    try:
        retired = await queue.retire_expired()
        if retired:
            logger.info("mongo_queue_retired_initial count=%s", retired)
    except Exception:  # noqa: BLE001 - boot must not die on a store hiccup
        logger.warning("mongo_queue_retire_initial_failed", exc_info=True)


async def _retire_loop(
    queue: WorkerQueue,
    *,
    interval: float,
    stop_event: asyncio.Event,
) -> None:
    """Periodically retire expired/reclaimable jobs so a dead worker's leases
    never block work until the next deployment.

    Runs on the same bounded cadence as the lease heartbeat (no busy-waiting):
    one ``retire_expired`` sweep per interval, with failures logged - a store
    hiccup must degrade the recovery cadence, never crash the worker.
    """
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except TimeoutError:
            pass
        if stop_event.is_set():
            return
        try:
            retired = await queue.retire_expired()
            if retired:
                logger.info("mongo_queue_retired count=%s", retired)
        except Exception:  # noqa: BLE001 - recovery must be best-effort
            logger.warning("mongo_queue_retire_failed", exc_info=True)


async def _shutdown() -> None:
    """Release browser, Mongo and Redis - each independently (ARQ parity)."""
    for resource, closer in (
        ("Playwright browser", close_browser),
        ("MongoDB client", MongoDB.close),
        ("Redis client", close_redis),
    ):
        try:
            await closer()
        except Exception:  # noqa: BLE001 - one failure must not block the rest
            logger.exception("Mongo worker shutdown failed to close %s.", resource)


def run_worker() -> int:
    """Synchronous entrypoint for ``python -m backend.workers`` (Mongo mode)."""
    configure_logging()
    attach_sensitive_data_filter()
    _log_resource_caps()
    return asyncio.run(_run())


__all__ = ["run_worker"]
