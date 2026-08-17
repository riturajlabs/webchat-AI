"""Crawl job status endpoints (Phase 4, ADR-002).

Progress is published by the ARQ worker onto the `crawl_jobs` document; this
route lets the dashboard poll live status. Tenancy comes from the
authenticated principal - a foreign tenant can never read another tenant's
crawl jobs (00-AI-Development-Rules §7).

Phase 16 adds a real-time SSE stream (``GET /{job_id}/stream``) that the
dashboard subscribes to for instant crawl-lifecycle updates instead of
polling every 3 seconds.  The endpoint first sends a ``snapshot`` event with
the current MongoDB document, then forwards Redis pub/sub events until the
job reaches a terminal status or the client disconnects.
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from backend.api.deps import (
    current_user,
    get_crawl_service,
    require_role,
    website_limiter,
)
from backend.core import crawl_events
from backend.schemas.crawl import CrawlJobOut
from backend.services.auth import Principal
from backend.services.crawl import CrawlService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/crawl-jobs",
    tags=["crawl-jobs"],
    dependencies=[Depends(require_role("owner", "admin"))],
)


@router.get("/{job_id}", response_model=CrawlJobOut)
async def get_crawl_job(
    job_id: str,
    principal: Annotated[Principal, Depends(current_user)],
    service: Annotated[CrawlService, Depends(get_crawl_service)],
    _: Annotated[None, Depends(website_limiter)],
) -> CrawlJobOut:
    job = await service.get_crawl_job(principal.tenant_id, job_id)
    return CrawlJobOut.from_job(job)


_TERMINAL_STATUSES = {"completed", "failed"}


@router.get("/{job_id}/stream")
async def stream_crawl_progress(
    job_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(current_user)],
    service: Annotated[CrawlService, Depends(get_crawl_service)],
    _: Annotated[None, Depends(website_limiter)],
) -> StreamingResponse:
    """SSE stream of crawl lifecycle events for the dashboard.

    Events:
      crawl.snapshot  – current job state (first frame)
      crawl.started   – worker picked up the job
      crawl.progress  – pages_completed / pages_total tick
      crawl.completed – terminal success
      crawl.failed    – terminal failure
    """
    # Validate tenant access and get current state
    job = await service.get_crawl_job(principal.tenant_id, job_id)

    async def event_stream() -> AsyncIterator[str]:
        # 1. Send current state snapshot immediately
        snapshot = CrawlJobOut.from_job(job)
        yield _sse("crawl.snapshot", snapshot.model_dump(mode="json"))

        # 2. If already terminal, close immediately
        if job.status in _TERMINAL_STATUSES:
            return

        # 3. Subscribe to Redis pub/sub for live updates
        pubsub = await crawl_events.subscribe(job_id)
        try:
            idle_seconds = 0.0
            max_idle = 600.0  # 10 minutes max stream lifetime

            while idle_seconds < max_idle:
                if await request.is_disconnected():
                    break

                message = await asyncio.wait_for(
                    pubsub.get_message(ignore_subscribe_messages=True),
                    timeout=1.0,
                )
                if message is None:
                    idle_seconds += 1.0
                    continue

                idle_seconds = 0.0
                if message["type"] != "message":
                    continue

                try:
                    payload = json.loads(message["data"])
                except (json.JSONDecodeError, TypeError):
                    continue

                event_name = payload.get("event", "")
                event_data = payload.get("data", {})
                yield _sse(event_name, event_data)

                # Stop after terminal events
                if event_name in ("crawl.completed", "crawl.failed"):
                    break
        except TimeoutError:
            pass
        except Exception:
            logger.exception("SSE stream error for crawl job %s", job_id)
        finally:
            await pubsub.unsubscribe()
            await pubsub.close()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"
