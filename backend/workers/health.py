"""Backend-aware worker healthcheck (Phase 18A).

``python -m backend.workers.health`` is the container ``HEALTHCHECK`` command
and reports whether the worker can reach *its own* broker:

* ``QUEUE_BACKEND=arq`` (production default) - ping the shared Redis client,
  exactly the check the previous inline ``redis.ping()`` Docker command did.
* ``QUEUE_BACKEND=mongo`` - ping the Mongo queue store. A Mongo-mode worker must
  NOT be health-checked through Redis: ARQ may be switched off entirely, and a
  Redis probe would either fail forever (Redis deleted) or, worse, report
  healthy while the queue database is unreachable.

It never enqueues a job, never claims one and never mutates queue state, so a
frequent probe cannot consume or duplicate work. Exit code ``0`` = healthy,
``1`` = unhealthy. A Redis failure in Mongo mode is not a failure: only the
selected broker is probed.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from backend.core.config import get_settings

logger = logging.getLogger("webchat_ai")


async def check() -> bool:
    """Return whether the configured queue backend is reachable."""
    if get_settings().queue_backend.strip().lower() == "mongo":
        from backend.core.database import MongoDB
        from backend.queue.factory import get_queue
        from backend.queue.mongo_adapter import MongoQueueAdapter

        try:
            queue = get_queue()
            if not isinstance(queue, MongoQueueAdapter):
                # The backend is configured as mongo but the factory produced
                # something else (or the opt-in is missing) - report unhealthy
                # instead of probing a broker this process does not consume.
                logger.error(
                    "worker_health queue_backend=mongo adapter=%s healthy=0",
                    type(queue).__name__,
                )
                return False
            return await queue.ping()
        finally:
            # The probe opens the shared client; release it so the check exits.
            await MongoDB.close()

    from backend.core.redis import ping_redis

    return await ping_redis()


def main() -> int:
    """Entry point for ``python -m backend.workers.health``."""
    try:
        healthy = asyncio.run(check())
    except Exception:  # noqa: BLE001 - a probe must never traceback-crash
        logger.exception("worker_health healthy=0 reason=error")
        return 1
    if not healthy:
        logger.error("worker_health healthy=0")
        return 1
    logger.info("worker_health healthy=1")
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = ["check", "main"]
