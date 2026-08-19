"""Crawl progress events over Redis pub/sub (real-time dashboard updates).

The ARQ worker publishes crawl lifecycle events to a per-job Redis channel;
the API server's SSE endpoint subscribes and forwards them to the connected
dashboard client.  Events are JSON-serialized, small (< 1 KB), and fire-and-
forget: if no SSE client is connected the events are simply lost (the
dashboard falls back to polling the ``crawl_jobs`` document).

Channel naming: ``crawl:progress:{crawl_job_id}``

The worker uses a lightweight ``aioredis`` (``redis.asyncio``) publisher that
shares the same connection URL as the ARQ queue but operates on a dedicated
connection pool so enqueue/progress never contend.
"""

import json
import logging
from typing import Any, cast

from redis.asyncio import Redis
from redis.asyncio.client import PubSub

from backend.core.config import get_settings

logger = logging.getLogger(__name__)

_CHANNEL_PREFIX = "crawl:progress"


def _channel(job_id: str) -> str:
    return f"{_CHANNEL_PREFIX}:{job_id}"


# ---------------------------------------------------------------------------
# Publisher (called by the ARQ worker)
# ---------------------------------------------------------------------------

_pubsub_redis: Redis | None = None


def _publisher() -> Redis:
    """Lazy singleton Redis connection for the worker publisher."""
    global _pubsub_redis
    if _pubsub_redis is None:
        _pubsub_redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    return _pubsub_redis


async def publish_event(job_id: str, event: str, data: dict[str, Any]) -> None:
    """Publish a single crawl event to the per-job Redis channel.

    Best-effort: publishing failures are logged but never crash the worker.
    """
    payload = json.dumps({"event": event, "data": data}, default=str)
    try:
        await _publisher().publish(_channel(job_id), payload)
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
    pages_processed: int,
    total_pages: int,
) -> None:
    await publish_event(
        job_id,
        "crawl.fetching",
        {
            "status": "fetching",
            "current_url": current_url,
            "pages_processed": pages_processed,
            "total_pages": total_pages,
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
    pages: int,
    chunks: int,
) -> None:
    await publish_event(
        job_id,
        "crawl.completed",
        {
            "status": "completed",
            "pages": pages,
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
    """Return a Redis PubSub handle subscribed to the job's channel."""
    client = Redis.from_url(get_settings().redis_url, decode_responses=True)
    pubsub = cast(PubSub, client.pubsub())
    await pubsub.subscribe(_channel(job_id))
    return pubsub


async def close_publisher() -> None:
    """Shut down the worker-side publisher (called on worker exit)."""
    global _pubsub_redis
    if _pubsub_redis is not None:
        await _pubsub_redis.aclose()
        _pubsub_redis = None
