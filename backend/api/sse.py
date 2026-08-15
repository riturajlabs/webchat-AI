"""Shared Server-Sent-Events helpers for streaming chat endpoints.

Both the dashboard chat (`/api/chat/stream`) and the public widget chat
(`/api/widget/v1/chat`) stream `RagService.stream_answer` events as SSE. The
`stream_with_disconnect` wrapper checks `request.is_disconnected()` before
every event so a client that closes the connection mid-stream stops the
pipeline promptly: generation is cancelled at the next chunk boundary, the
partial answer is never persisted, and no further tokens are consumed
(Sprint 1 P1 remediation).

Phase 13 adds `stream_answer_with_usage`: the same stream adapter plus the
SaaS billing gate and event recording. The plan's `messages_sent` limit is
checked before the pipeline starts (surfacing as an SSE `error` event with
code `LIMIT_REACHED`, consistent with other in-stream failures); then
`messages_sent` is recorded at the first `sources` frame, and `ai_responses`
+ `tokens_used` on the `done` frame. Recording is best-effort: a billing
write failure is logged, never allowed to interrupt the answer stream.
"""

import json
import logging
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any

from fastapi import Request

from backend.core.errors import AppError
from backend.services.billing import UsageService

logger = logging.getLogger("webchat_ai")


def sse(event: str, data: dict[str, Any]) -> str:
    """Serialize one SSE frame: `event: <name>\ndata: <json>\n\n`."""
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


async def stream_with_disconnect(
    request: Request, events: AsyncGenerator[dict[str, Any]]
) -> AsyncIterator[str]:
    """Yield `events` as SSE frames, stopping as soon as the client disconnects.

    The first iteration also acts as the pre-flight check: an already-closed
    connection never starts the pipeline. On disconnect the inner generator is
    explicitly closed (GeneratorExit), so the remainder of `stream_answer` -
    including persisting the assistant message and recording usage - does not
    run and the pipeline stops immediately instead of waiting for GC.
    """
    try:
        async for event in events:
            if await request.is_disconnected():
                break
            yield sse(event["event"], event["data"])
    finally:
        await events.aclose()


async def stream_answer_with_usage(
    request: Request,
    events: AsyncGenerator[dict[str, Any]],
    *,
    usage: UsageService,
    tenant_id: str,
    user_id: str | None,
    website_id: str | None,
) -> AsyncIterator[str]:
    """`stream_with_disconnect` plus the Phase 13 billing gate and recordings.

    Enforces the tenant's `max_monthly_messages` before the pipeline starts;
    on exhaustion it yields a single `error` frame (`LIMIT_REACHED`) instead
    of running generation. Recording failures never surface to the client.
    """
    try:
        await usage.check_limit(tenant_id, event_type="messages_sent")
    except AppError as exc:
        yield sse("error", {"code": exc.code, "message": exc.message})
        return

    async for frame in stream_with_disconnect(
        request,
        _recording_events(events, usage, tenant_id, user_id, website_id),
    ):
        yield frame


async def _recording_events(
    events: AsyncGenerator[dict[str, Any]],
    usage: UsageService,
    tenant_id: str,
    user_id: str | None,
    website_id: str | None,
) -> AsyncGenerator[dict[str, Any]]:
    """Forward `events`, recording usage at the `sources` and `done` frames."""
    recorded = False
    async for event in events:
        if event["event"] == "sources" and not recorded:
            recorded = True
            await _record(
                usage,
                tenant_id=tenant_id,
                user_id=user_id,
                website_id=website_id,
                event_type="messages_sent",
            )
        elif event["event"] == "done":
            data = event["data"]
            tokens = int(data.get("input_tokens", 0) or 0) + int(
                data.get("output_tokens", 0) or 0
            )
            await _record(
                usage,
                tenant_id=tenant_id,
                user_id=user_id,
                website_id=website_id,
                event_type="ai_responses",
            )
            if tokens > 0:
                await _record(
                    usage,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    website_id=website_id,
                    event_type="tokens_used",
                    quantity=tokens,
                )
        yield event


async def _record(
    usage: UsageService,
    *,
    tenant_id: str,
    user_id: str | None,
    website_id: str | None,
    event_type: str,
    quantity: int = 1,
) -> None:
    """Best-effort usage recording: never break the answer stream."""
    try:
        await usage.record_usage(
            tenant_id=tenant_id,
            user_id=user_id,
            website_id=website_id,
            event_type=event_type,
            quantity=quantity,
        )
    except Exception:
        logger.exception(
            "Failed to record usage event %s for tenant %s", event_type, tenant_id
        )


__all__ = ["sse", "stream_answer_with_usage", "stream_with_disconnect"]
