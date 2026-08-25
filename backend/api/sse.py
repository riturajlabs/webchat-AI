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

Production hardening (audit S-03/S-08): `with_heartbeats` injects SSE comment
frames (`: ping`) while the upstream is silent so idle proxies and browsers do
not reap an apparently-dead connection during long generation pauses; comments
are ignored by every SSE client and never reorder application events.
`buffered_stream_with_disconnect` no longer yields from its cleanup path - a
`yield` inside `finally` during GeneratorExit raises RuntimeError on client
disconnects.
"""

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any

from fastapi import Request

from backend.core.errors import AppError
from backend.core.logging import get_request_id
from backend.core.metrics import observe_done, observe_sources, observe_sse_error
from backend.services.billing import UsageService

logger = logging.getLogger("webchat_ai")


def sse(event: str, data: dict[str, Any]) -> str:
    """Serialize one SSE frame: `event: <name>\ndata: <json>\n\n`."""
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


# Audit S-03: SSE keepalive comment emitted while generation is silent. The
# spec allows comment lines (`:` prefix); every client - including the widget
# SDK's `parseSseFrame` - ignores them, but the bytes reset idle timeouts in
# browsers and reverse proxies so long silent generations are not reaped.
_SSE_HEARTBEAT_FRAME = ": ping\n\n"
_DEFAULT_HEARTBEAT_INTERVAL_S = 15.0


async def with_heartbeats(
    frames: AsyncIterator[str], *, interval_s: float = _DEFAULT_HEARTBEAT_INTERVAL_S
) -> AsyncIterator[str]:
    """Yield `frames` unchanged, emitting a `: ping` comment when silent.

    While waiting longer than `interval_s` for the next upstream frame, a
    heartbeat comment is yielded between (never before/after or instead of)
    real frames, so application event order is preserved exactly. Waiting
    uses `asyncio.wait` on the pending `__anext__` task rather than
    `wait_for`: timing out must NOT cancel the in-flight pull, only observe
    it. On cleanup the pending pull is cancelled and the upstream closed so
    persistence bookkeeping still runs.

    Heartbeat comments are excluded from transport metrics by the caller.
    """
    iterator = frames.__aiter__()
    pending: asyncio.Task[str] | None = None
    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(iterator.__anext__())
            done, _ = await asyncio.wait({pending}, timeout=interval_s)
            if pending not in done:
                yield _SSE_HEARTBEAT_FRAME
                continue
            finished = pending
            pending = None
            try:
                yield finished.result()
            except StopAsyncIteration:
                return
    finally:
        if pending is not None and not pending.done():
            # Teardown while a pull is in flight (client disconnect): cancel
            # it so the upstream generator can be closed synchronously below.
            pending.cancel()
        if pending is not None:
            try:
                await pending
            except BaseException:  # noqa: BLE001 - teardown of a dead pull
                pass
        aclose = getattr(frames, "aclose", None)
        if aclose is not None:
            await aclose()


def _stamp_request_id(data: dict[str, Any]) -> dict[str, Any]:
    """Attach the current request ID to an event payload (Phase 2 tracing).

    `setdefault` semantics: never overwrite an id already on the frame.
    Mirrors the log formatter's convention of carrying `-` when no request
    context exists (direct unit invocation); under HTTP the middleware always
    provides a real id.
    """
    data.setdefault("request_id", get_request_id())
    return data


def _failed_done(failure: dict[str, Any]) -> dict[str, Any]:
    """Build the terminal `done` frame for a stream that did not complete."""
    data = dict(failure)
    data["status"] = "failed"
    _stamp_request_id(data)
    return {"event": "done", "data": data}


async def ensure_terminal_done(
    events: AsyncGenerator[dict[str, Any]],
) -> AsyncGenerator[dict[str, Any]]:
    """Guarantee every event stream ends with an explicit terminal `done` frame.

    Success `done` frames gain the additive field `status: "completed"`
    (unknown fields are ignored by older clients). A handled failure - a
    yielded `error` frame - is followed by `done {"status": "failed", ...}`,
    as is a silent generator close or an unexpected exception (which also gets
    its own `error` frame first, mirroring `_error_event`). This closes audit
    P0-5: clients can always distinguish a finished stream from a dropped
    connection, so partial answers are never mislabeled as network errors.

    `GeneratorExit` (client disconnect cleanup via `aclose()`) and
    `CancelledError` propagate unchanged - disconnect handling must never grow
    extra frames.
    """
    failure: dict[str, Any] | None = None
    saw_done = False
    try:
        async for event in events:
            name = event["event"]
            if name == "done":
                saw_done = True
                data = event.setdefault("data", {})
                data.setdefault("status", "completed")
                _stamp_request_id(data)
            elif name == "error" and failure is None:
                failure = dict(event.get("data") or {})
                failure.setdefault("code", "INTERNAL_ERROR")
                failure.setdefault(
                    "message", "An unexpected error occurred. Please try again later."
                )
                _stamp_request_id(event.setdefault("data", {}))
            yield event
    except GeneratorExit:
        # Disconnect cleanup: close the inner generator so its persistence /
        # usage bookkeeping `finally` blocks run now, not at GC time.
        await events.aclose()
        raise
    except asyncio.CancelledError:
        await events.aclose()
        raise
    except Exception as exc:
        # Unexpected generator death: mirror RagService._safe_message so
        # internals never leak, then close with the failed terminal state.
        if isinstance(exc, AppError):
            code, message = exc.code, exc.message
        else:
            code = "INTERNAL_ERROR"
            message = "An unexpected error occurred. Please try again later."
        logger.exception(
            "chat stream failed without terminal event (request_id=%s)", get_request_id()
        )
        yield {
            "event": "error",
            "data": _stamp_request_id({"code": code, "message": message}),
        }
        yield _failed_done({"code": code, "message": message})
        return
    if saw_done:
        return
    if failure is None:
        failure = {
            "code": "INTERNAL_ERROR",
            "message": "Chat stream ended unexpectedly.",
        }
    yield _failed_done(failure)


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


async def _cancel_pending(pending: asyncio.Task[Any] | None) -> None:
    """Cancel an in-flight upstream pull and wait for its teardown.

    Awaiting the cancelled task before closing the upstream generator is what
    makes `events.aclose()` safe: closing a generator whose `__anext__` is
    still running raises RuntimeError. Swallowing the resulting
    CancelledError/StopAsyncIteration keeps cleanup side-effect free.
    """
    if pending is None:
        return
    if not pending.done():
        pending.cancel()
    try:
        await pending
    except BaseException:  # noqa: BLE001 - teardown of a dead pull
        pass


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

    Audit S-18 (lazy flush): the flush is driven by *time*, not by upstream
    traffic. While deltas sit in the buffer, the wait for the next upstream
    event is bounded by the flush deadline; when it expires the buffer is
    yielded immediately without waiting for more tokens. Previously a model
    pause longer than `buffer_ms` silently extended how long already-produced
    text was withheld, doubling perceived inter-token latency. The wait uses
    `asyncio.wait` on the in-flight `__anext__` task so a timeout never
    cancels the pull itself (mirroring `with_heartbeats`).

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

    iterator = events.__aiter__()
    pending: asyncio.Task[Any] | None = None
    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(iterator.__anext__())
            # Bound the wait by the pending deadline only when deltas are
            # actually held; otherwise block indefinitely like `async for`.
            timeout = (
                max(0.0, flush_deadline - time.monotonic())
                if buffer and flush_deadline is not None
                else None
            )
            done_set, _ = await asyncio.wait({pending}, timeout=timeout)
            if pending not in done_set:
                # Audit S-18: deadline expiry with a live buffer - flush now.
                # The upstream pull stays in flight and is simply awaited on
                # the next loop turn.
                frame = await _flush()
                flush_deadline = None
                if frame is not None:
                    yield frame
                continue
            finished, pending = pending, None
            try:
                event = finished.result()
            except StopAsyncIteration:
                break
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
    except GeneratorExit:
        # Audit S-08: disconnect cleanup must not yield. Cancel any in-flight
        # upstream pull first (a dangling pull would keep the pipeline alive -
        # a leak on long streams), then close the inner generator so its
        # persistence bookkeeping runs immediately; still-buffered deltas are
        # undeliverable (the client is gone).
        await _cancel_pending(pending)
        await events.aclose()
        raise
    except asyncio.CancelledError:
        await _cancel_pending(pending)
        await events.aclose()
        raise
    # Normal loop exit (stream exhausted or client-disconnect break): deliver
    # deltas still held when iteration ended. This is live-stream control flow,
    # never GeneratorExit cleanup - the except blocks above close the upstream
    # without flushing (audit S-08).
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
    heartbeat_interval_s: float = _DEFAULT_HEARTBEAT_INTERVAL_S,
) -> AsyncIterator[str]:
    """`stream_with_disconnect` plus the Phase 13 billing gate and recordings.

    Enforces the tenant's `max_monthly_messages` before the pipeline starts;
    on exhaustion it yields a single `error` frame (`LIMIT_REACHED`) instead
    of running generation. Recording failures never surface to the client.

    When ``buffer_ms > 0``, small ``message`` deltas are coalesced into a
    single SSE frame every ``buffer_ms`` milliseconds, reducing frame count
    and network round-trips without changing client-visible semantics.

    When the upstream is silent for longer than ``heartbeat_interval_s``
    (audit S-03), a `: ping` SSE comment is emitted so proxies and browsers
    keep the connection open during long generation pauses. Heartbeat
    comments are ignored by clients and excluded from transport metrics.
    Pass ``heartbeat_interval_s <= 0`` to disable.
    """
    try:
        await usage.check_limit(tenant_id, event_type="messages_sent")
    except AppError as exc:
        # Pre-stream rejection frames also carry the request id so a blocked
        # turn is traceable exactly like a streamed one (Phase 2 tracing).
        yield sse(
            "error",
            _stamp_request_id({"code": exc.code, "message": exc.message}),
        )
        yield sse(
            "done",
            _stamp_request_id({"status": "failed", "code": exc.code, "message": exc.message}),
        )
        return

    recording_gen = _recording_events(
        _metrics_events(events), usage, tenant_id, user_id, website_id
    )
    if buffer_ms > 0:
        stream_fn = buffered_stream_with_disconnect(request, recording_gen, buffer_ms=buffer_ms)
    else:
        stream_fn = stream_with_disconnect(request, recording_gen)
    if heartbeat_interval_s > 0:
        frames: AsyncIterator[str] = with_heartbeats(stream_fn, interval_s=heartbeat_interval_s)
    else:
        frames = stream_fn
    sse_started = time.perf_counter()
    event_count = 0
    first_event_ms: float | None = None
    first_token_ms: float | None = None
    try:
        async for frame in frames:
            if not frame.startswith(":"):
                # Heartbeat comments are transport keepalives, not events: they
                # must not skew event counts or latency percentiles.
                event_count += 1
                if first_event_ms is None:
                    first_event_ms = (time.perf_counter() - sse_started) * 1000.0
                if first_token_ms is None and frame.startswith("event: message"):
                    first_token_ms = (time.perf_counter() - sse_started) * 1000.0
            yield frame
    except GeneratorExit:
        # Consumer abandonment (client disconnect cancels the response task,
        # or the route generator is closed early): tear down the whole wrapper
        # chain now - heartbeat/buffer/disconnect layers, billing recording,
        # metrics and the pipeline itself - instead of leaving it suspended
        # until garbage collection on a long-lived process.
        await _aclose_events(frames)
        raise
    except asyncio.CancelledError:
        await _aclose_events(frames)
        raise
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
            "first_event_ms": round(first_event_ms, 2) if first_event_ms is not None else None,
            "first_token_ms": round(first_token_ms, 2) if first_token_ms is not None else None,
        },
    )


async def _aclose_events(events: AsyncIterator[Any]) -> None:
    """Close an async iterator if it supports it (best-effort, never raises).

    Long-lived processes must not wait for garbage collection to finalize an
    abandoned stream: every wrapper in the SSE chain holds the previous layer
    (and through it the whole chat pipeline) alive until then. Explicit close
    on early exit releases those resources deterministically.
    """
    aclose = getattr(events, "aclose", None)
    if aclose is None:
        return
    try:
        await aclose()
    except Exception:  # noqa: BLE001 - teardown must never mask the real exit
        pass


async def _metrics_events(
    events: AsyncGenerator[dict[str, Any]],
) -> AsyncGenerator[dict[str, Any]]:
    """Observe SSE frames for Phase 3 metrics without altering them.

    Pure pass-through: every value recorded here was already computed by the
    pipeline (source counts, confidence, tokens, timing block). Observation
    errors are swallowed so metrics can never break a chat stream.
    Early exit (consumer abandonment) closes the wrapped generator so the
    teardown cascades through the whole chain instead of waiting for GC.
    """
    try:
        async for event in events:
            try:
                name = event.get("event")
                data = event.get("data")
                payload = data if isinstance(data, dict) else {}
                if name == "sources":
                    sources = payload.get("sources")
                    observe_sources(len(sources) if isinstance(sources, list) else 0)
                elif name == "error":
                    observe_sse_error(str(payload.get("code") or "UNKNOWN"))
                elif name == "done" and payload.get("status") != "failed":
                    observe_done(payload)
            except Exception:  # pragma: no cover - observation must never break streaming
                pass
            yield event
    except GeneratorExit:
        await events.aclose()
        raise
    except asyncio.CancelledError:
        await events.aclose()
        raise


async def _recording_events(
    events: AsyncGenerator[dict[str, Any]],
    usage: UsageService,
    tenant_id: str,
    user_id: str | None,
    website_id: str | None,
) -> AsyncGenerator[dict[str, Any]]:
    """Forward `events`, recording usage at the `sources` and `done` frames.

    Early exit (consumer abandonment) closes the wrapped generator so the
    teardown cascades through the whole chain instead of waiting for GC.
    """
    recorded = False
    try:
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
                if data.get("status") == "failed":
                    # Terminal failure frame from `ensure_terminal_done`: the turn
                    # did not complete, so no ai_responses/tokens are billed.
                    yield event
                    continue
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
    except GeneratorExit:
        await events.aclose()
        raise
    except asyncio.CancelledError:
        await events.aclose()
        raise


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
    "ensure_terminal_done",
    "sse",
    "stream_answer_with_usage",
    "stream_with_disconnect",
    "with_heartbeats",
]
