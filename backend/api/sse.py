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

Phase 12.6 latency work adds `buffered_stream_with_disconnect`: the same
disconnect-aware adapter with delta coalescing. Small `message` deltas are
buffered and flushed as a single SSE frame every `buffer_ms` milliseconds
(default 50ms), reducing the number of frames and network round-trips without
changing the client-visible streaming semantics.
"""

import json
import logging
import time
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any

from fastapi import Request

from backend.core.errors import AppError
from backend.core.logging import get_request_id
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


# Default buffer window for delta coalescing (milliseconds).
_DEFAULT_BUFFER_MS = 50.0


async def buffered_stream_with_disconnect(
    request: Request,
    events: AsyncGenerator[dict[str, Any]],
    *,
    buffer_ms: float = _DEFAULT_BUFFER_MS,
) -> AsyncIterator[str]:
    """`stream_with_disconnect` with delta coalescing for reduced frame count.

    Small `message` deltas are buffered and flushed as a single SSE frame
    every `buffer_ms` milliseconds (default 50ms). Non-message events
    (`sources`, `done`, `error`) are flushed immediately so they are never
    delayed. This reduces the number of SSE frames and network round-trips
    without changing the client-visible streaming semantics: the client still
    receives the same sequence of text, just in slightly larger chunks.

    The first iteration acts as the pre-flight disconnect check, identical to
    `stream_with_disconnect`.
    """
    buffer: list[str] = []
    flush_deadline: float | None = None

    async def _flush() -> str | None:
        """Coalesce buffered deltas into a single SSE frame, or None if empty."""
        if not buffer:
            return None
        merged = "".join(buffer)
        buffer.clear()
        return sse("message", {"delta": merged})

    try:
        async for event in events:
            if await request.is_disconnected():
                break
            event_name = event["event"]
            if event_name == "message":
                delta = event["data"].get("delta", "")
                buffer.append(delta)
                now = time.monotonic()
                if flush_deadline is None:
                    flush_deadline = now + buffer_ms / 1000.0
                if now >= flush_deadline:
                    frame = await _flush()
                    if frame is not None:
                        yield frame
                    flush_deadline = None
            else:
                # Non-message events flush the buffer first, then yield immediately.
                frame = await _flush()
                if frame is not None:
                    yield frame
                flush_deadline = None
                yield sse(event_name, event["data"])
    finally:
        # Flush any remaining buffered deltas on stream end or disconnect.
        frame = await _flush()
        if frame is not None:
            yield frame
        await events.aclose()


async def stream_answer_with_usage(
    request: Request,
    events: AsyncGenerator[dict[str, Any]],
    *,
    usage: UsageService,
    tenant_id: str,
    user_id: str | None,
    website_id: str | None,
    buffer_ms: float = 0.0,
) -> AsyncIterator[str]:
    """`stream_with_disconnect` plus the Phase 13 billing gate and recordings.

    Enforces the tenant's `max_monthly_messages` before the pipeline starts;
    on exhaustion it yields a single `error` frame (`LIMIT_REACHED`) instead
    of running generation. Recording failures never surface to the client.

    When ``buffer_ms > 0``, small ``message`` deltas are coalesced into a
    single SSE frame every ``buffer_ms`` milliseconds, reducing frame count
    and network round-trips without changing client-visible semantics.
    """
    try:
        await usage.check_limit(tenant_id, event_type="messages_sent")
    except AppError as exc:
        yield sse("error", {"code": exc.code, "message": exc.message})
        return

    recording_gen = _recording_events(events, usage, tenant_id, user_id, website_id)
    if buffer_ms > 0:
        stream_fn = buffered_stream_with_disconnect(request, recording_gen, buffer_ms=buffer_ms)
    else:
        stream_fn = stream_with_disconnect(request, recording_gen)
    sse_started = time.perf_counter()
    event_count = 0
    async for frame in stream_fn:
        event_count += 1
        yield frame
    sse_transport_ms = (time.perf_counter() - sse_started) * 1000.0
    logger.info(
        "sse_transport",
        extra={
            "request_id": get_request_id(),
            "tenant_id": tenant_id,
            "website_id": website_id,
            "events_yielded": event_count,
            "buffer_ms": buffer_ms,
            "sse_transport_ms": round(sse_transport_ms, 2),
        },
    )


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
            tokens = int(data.get("input_tokens", 0) or 0) + int(data.get("output_tokens", 0) or 0)
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
        logger.exception("Failed to record usage event %s for tenant %s", event_type, tenant_id)


__all__ = [
    "buffered_stream_with_disconnect",
    "sse",
    "stream_answer_with_usage",
    "stream_with_disconnect",
]
