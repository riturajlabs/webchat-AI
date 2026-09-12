"""ARQ worker configuration.

Run with:  python -m backend.workers   (ADR-002 entrypoint)
Direct:    arq backend.workers.app.WorkerSettings

Job functions are registered in `backend.workers.tasks` and land in Phase 2
(email), Phase 4/5 (crawler) and Phase 5 (knowledge processing). See
docs/07-Architecture-Decisions.md ADR-002.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from arq.connections import RedisSettings

from backend.ai.registry import build_ingestion_embedding_client
from backend.core.config import get_settings
from backend.core.database import MongoDB
from backend.core.logging import attach_sensitive_data_filter, configure_logging
from backend.core.redis import close_redis, get_redis
from backend.services.ai.provider_health import ProviderHealthStore
from backend.services.ingestion.browser import close_browser
from backend.services.ingestion.crawl_memory import measure_memory
from backend.workers import tasks

logger = logging.getLogger("webchat_ai")

_settings = get_settings()

# FIND-06: the audited production worker target (docs/CRAWL_EGRESS_HARDENING.md
# §6 "1 GiB Railway Worker constraints"). Logged at boot alongside the live
# cap so a deployment that drifts from this shape is visible immediately.
_WORKER_TARGET_MEMORY_MIB = 1024  # 1 GiB
_WORKER_TARGET_CPUS = 2


def _log_resource_caps() -> None:
    """Log the effective worker/container memory caps at startup.

    FIND-06: surfaces the live memory source, current usage, detected limit and
    process footprint next to the expected 1 GiB / 2 vCPU production target so
    memory-shape drift is observable in boot logs. Never raises and logs no
    secrets: ``measure_memory`` fails open (an environment without cgroup data
    reports ``source="unavailable"``) and the values below carry no credentials
    or URLs.
    """
    measurement = measure_memory()
    logger.info(
        "worker_resource_caps source=%s current_bytes=%s limit_bytes=%s "
        "python_rss_bytes=%s processes=%s expected_memory_mib=%s expected_cpus=%s",
        measurement.source,
        measurement.current_bytes,
        measurement.limit_bytes,
        measurement.python_rss_bytes,
        measurement.processes,
        _WORKER_TARGET_MEMORY_MIB,
        _WORKER_TARGET_CPUS,
    )


async def startup(ctx: dict[str, Any]) -> None:
    """Runs once when the worker starts."""
    # FIND-03 (OBS-06): adopt the project's shared structured logging and
    # sensitive-data filter. ARQ's CLI already ran its own log config before
    # this hook, so configuring here makes the shared formatter (JSON in
    # production, readable in development), the effective level
    # (ENVIRONMENT/LOG_LEVEL/DEBUG) and the scrubbing authoritative for worker
    # records without touching ARQ's own logger or the API's logging setup.
    configure_logging()
    attach_sensitive_data_filter()
    # The ARQ CLI gives the `arq` logger its own handler; keep its output
    # exactly as-is and stop it propagating to the root JSON handler (which
    # would double-emit every ARQ lifecycle record). ARQ logging is not
    # silenced - only the duplicate copy is removed.
    logging.getLogger("arq").propagate = False
    # FIND-06: log the effective worker memory shape at boot (best effort) so
    # sizing drift from the 1 GiB / 2 vCPU production target is observable.
    _log_resource_caps()
    ctx["app_name"] = _settings.app_name
    # Shared embedding client for all knowledge jobs in this process (Phase 9,
    # ADR-009): the single primary provider only. Ingestion must never switch
    # embedding spaces mid-corpus (BUG-1): a Gemini->Jina failover while
    # storing chunks would stamp one website with two incompatible vector
    # identities. On failure the same provider is retried (client batch
    # retries + document-level backoff); exhausted retries quarantine the
    # document instead of writing foreign-space vectors.
    ctx["embedding_client"] = build_ingestion_embedding_client()
    # Kept separate from generation health: an embedding quota cooldown must
    # not change LLM routing for the same provider.
    ctx["embedding_provider_health"] = ProviderHealthStore(get_redis())


async def _close_async(resource: str, closer: Callable[[], Awaitable[None]]) -> None:
    """Run one async closer, logging instead of aborting the rest."""
    try:
        await closer()
    except Exception:
        logger.exception("Worker shutdown failed to close %s.", resource)


async def shutdown(ctx: dict[str, Any]) -> None:
    """Runs once when the worker stops: release browser, Mongo and Redis.

    Each resource is closed independently so a failure in one never prevents
    the others from being released. Every close function is idempotent (a
    no-op when the resource was never initialized), so a worker that never
    opened a browser or touched Redis still shuts down cleanly. ARQ's own
    queue connection is managed by ARQ itself and is deliberately left alone.
    """
    _ = ctx
    await _close_async("Playwright browser", close_browser)
    await _close_async("MongoDB client", MongoDB.close)
    await _close_async("Redis client", close_redis)


class WorkerSettings:
    """ARQ worker settings consumed via `arq backend.workers.app.WorkerSettings`."""

    functions = tasks.TASKS
    redis_settings = RedisSettings.from_dsn(_settings.redis_url)
    on_startup = startup
    on_shutdown = shutdown
    max_tries = 3
    job_timeout = 600
    keep_result = 3600
    max_jobs = 10
