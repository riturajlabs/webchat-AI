"""Crawl progress events over Redis pub/sub (real-time dashboard updates).

The ARQ worker publishes crawl lifecycle events to a per-job Redis channel;
the API server's SSE endpoint subscribes and forwards them to the connected
dashboard client.  Events are JSON-serialized, small (< 1 KB), and fire-and-
forget: if no SSE client is connected the events are simply lost (the
dashboard falls back to polling the ``crawl_jobs`` document).

Channel naming: ``crawl:progress:{crawl_job_id}``

Both publisher and subscriber reuse the application's shared Redis connection
pool (``backend.core.redis.get_redis``) instead of creating isolated clients,
preventing connection leaks in long-running SaaS deployments.
"""

import json
import logging
from typing import Any

from redis.asyncio.client import PubSub

from backend.core.redis import get_redis

logger = logging.getLogger("webchat_ai")

_CHANNEL_PREFIX = "crawl:progress"


def _channel(job_id: str) -> str:
    return f"{_CHANNEL_PREFIX}:{job_id}"


# ---------------------------------------------------------------------------
# Publisher (called by the ARQ worker)
# ---------------------------------------------------------------------------


async def publish_event(job_id: str, event: str, data: dict[str, Any]) -> None:
    """Publish a single crawl event to the per-job Redis channel.

    Best-effort: publishing failures are logged but never crash the worker.
    Uses the shared application Redis pool instead of a dedicated client.
    """
    payload = json.dumps({"event": event, "data": data}, default=str)
    try:
        await get_redis().publish(_channel(job_id), payload)
    except Exception:  # noqa: BLE001
        logger.warning("Failed to publish crawl event %s for job %s", event, job_id)


# Convenience helpers for lifecycle events ----------------------------------


async def publish_started(job_id: str) -> None:
    await publish_event(
        job_id,
        "crawl.started",
        {
            "status": "started",
            "message": "Starting crawler…",
        },
    )


async def publish_fetching(
    job_id: str,
    *,
    current_url: str,
    pages_completed: int,
    pages_total: int,
) -> None:
    await publish_event(
        job_id,
        "crawl.fetching",
        {
            "status": "fetching",
            "current_url": current_url,
            "pages_completed": pages_completed,
            "pages_total": pages_total,
        },
    )


async def publish_extracting(job_id: str, *, url: str) -> None:
    await publish_event(
        job_id,
        "crawl.extracting",
        {
            "status": "extracting",
            "message": "Extracting page content",
            "current_url": url,
        },
    )


async def publish_embedding(
    job_id: str,
    *,
    documents_completed: int,
    total_documents: int,
) -> None:
    await publish_event(
        job_id,
        "crawl.embedding",
        {
            "status": "embedding",
            "documents_completed": documents_completed,
            "total_documents": total_documents,
        },
    )


async def publish_completed(
    job_id: str,
    *,
    pages_completed: int,
    pages_total: int,
    chunks: int,
) -> None:
    await publish_event(
        job_id,
        "crawl.completed",
        {
            "status": "completed",
            "pages_completed": pages_completed,
            "pages_total": pages_total,
            "chunks": chunks,
        },
    )


async def publish_failed(job_id: str, *, error: str) -> None:
    await publish_event(
        job_id,
        "crawl.failed",
        {
            "status": "failed",
            "error": error,
        },
    )


async def publish_progress(
    job_id: str,
    *,
    pages_completed: int,
    pages_total: int,
) -> None:
    """Generic progress tick (called from the existing on_progress callback)."""
    await publish_event(
        job_id,
        "crawl.progress",
        {
            "status": "running",
            "pages_completed": pages_completed,
            "pages_total": pages_total,
        },
    )


# ---------------------------------------------------------------------------
# Subscriber (called by the API server SSE endpoint)
# ---------------------------------------------------------------------------


async def subscribe(job_id: str) -> PubSub:
    """Return a Redis PubSub handle subscribed to the job's channel.

    Uses the shared application Redis pool. The caller MUST close the PubSub
    handle in a ``finally`` block to release the subscription.
    """
    pubsub: PubSub = get_redis().pubsub()
    await pubsub.subscribe(_channel(job_id))
    return pubsub


async def close_publisher() -> None:
    """Shut down the worker-side publisher (called on worker exit).

    No-op when using the shared Redis pool: the pool is closed by the
    application lifespan.
    """
    pass
