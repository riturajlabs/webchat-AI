"""Unit tests for the shared SSE streaming helpers (`backend/api/sse.py`).

The `stream_with_disconnect` wrapper is the Sprint 1 P1 fix that stops chat
generation the moment a client disconnects: it pre-flights the connection and
finalizes the inner generator on disconnect so partial answers are never
persisted and no further tokens are consumed.
"""

import asyncio
import json
import time
from typing import Any

import pytest
from backend.api.sse import (
    buffered_stream_with_disconnect,
    ensure_terminal_done,
    sse,
    stream_answer_with_usage,
    stream_with_disconnect,
    with_heartbeats,
)
from backend.core.errors import AppError
from backend.core.logging import request_id_var


class FakeRequest:
    """Minimal stand-in for `fastapi.Request.is_disconnected`."""

    def __init__(self, disconnected: bool = False) -> None:
        self._disconnected = disconnected

    def set_disconnected(self, value: bool) -> None:
        self._disconnected = value

    async def is_disconnected(self) -> bool:
        return self._disconnected


def _events(*, close_after: int | None = None, finalized: list[str]) -> Any:
    """A generator that reports `finalized` from its `finally` block."""

    async def gen():
        try:
            for i in range(3):
                if close_after is not None and i >= close_after:
                    yield {"event": "done", "data": {"chunk": i}}
                    break
                yield {"event": "delta", "data": {"chunk": i}}
        finally:
            finalized.append("closed")

    return gen()


async def test_sse_serializes_event_frame() -> None:
    assert sse("delta", {"chunk": "hello"}) == ('event: delta\ndata: {"chunk": "hello"}\n\n')


async def test_stream_with_disconnect_yields_all_events_when_connected() -> None:
    request = FakeRequest(disconnected=False)
    finalized: list[str] = []
    frames = [
        frame async for frame in stream_with_disconnect(request, _events(finalized=finalized))
    ]

    assert len(frames) == 3
    assert all(frame.startswith("event: delta") for frame in frames)
    assert finalized == ["closed"]


async def test_stream_with_disconnect_stops_on_mid_stream_disconnect() -> None:
    request = FakeRequest(disconnected=False)
    finalized: list[str] = []
    events = _events(finalized=finalized)
    iterator = stream_with_disconnect(request, events)

    first = await anext(iterator)
    assert first.startswith("event: delta")

    request.set_disconnected(True)
    with pytest.raises(StopAsyncIteration):
        await anext(iterator)

    assert finalized == ["closed"]


async def test_stream_with_disconnect_preflights_closed_connection() -> None:
    request = FakeRequest(disconnected=True)
    finalized: list[str] = []
    events = _events(finalized=finalized)

    frames = [frame async for frame in stream_with_disconnect(request, events)]

    assert frames == []
    assert finalized == ["closed"]


# ---------------------------------------------------------------------------
# Terminal-event guarantee (ensure_terminal_done)
# ---------------------------------------------------------------------------


def _parse_frames(frames: list[str]) -> list[tuple[str, dict]]:
    import json

    parsed = []
    for frame in frames:
        event_name = None
        data_lines = []
        for line in frame.split("\n"):
            if line.startswith("event: "):
                event_name = line[len("event: ") :]
            elif line.startswith("data: "):
                data_lines.append(line[len("data: ") :])
        parsed.append((event_name, json.loads("\n".join(data_lines))))
    return parsed


async def test_terminal_done_annotates_success_with_completed_status() -> None:
    async def gen():
        yield {"event": "message", "data": {"delta": "Hi"}}
        yield {"event": "done", "data": {"session_id": "s1"}}

    events = [event async for event in ensure_terminal_done(gen())]

    assert [event["event"] for event in events] == ["message", "done"]
    assert events[1]["data"]["status"] == "completed"
    assert events[1]["data"]["session_id"] == "s1"


async def test_terminal_done_appends_failed_status_after_handled_error() -> None:
    async def gen():
        yield {"event": "sources", "data": {"sources": []}}
        yield {"event": "error", "data": {"code": "GENERATION_FAILED", "message": "boom"}}
        return

    events = [event async for event in ensure_terminal_done(gen())]

    assert [event["event"] for event in events] == ["sources", "error", "done"]
    assert events[2]["data"] == {
        "status": "failed",
        "code": "GENERATION_FAILED",
        "message": "boom",
        # No HTTP context in a direct unit call: the log-formatter default.
        "request_id": "-",
    }


async def test_terminal_done_emits_error_and_failed_done_on_unexpected_exception() -> None:
    finalized: list[str] = []

    async def gen():
        try:
            yield {"event": "message", "data": {"delta": "partial"}}
            raise RuntimeError("provider socket exploded")
        finally:
            finalized.append("closed")

    events = [event async for event in ensure_terminal_done(gen())]

    assert finalized == ["closed"]
    assert [event["event"] for event in events] == ["message", "error", "done"]
    assert events[1]["data"]["code"] == "INTERNAL_ERROR"
    # Internals never leak into the client-visible message.
    assert "socket" not in events[1]["data"]["message"]
    assert events[2]["data"] == {
        "status": "failed",
        "code": "INTERNAL_ERROR",
        "message": "An unexpected error occurred. Please try again later.",
        "request_id": "-",
    }


async def test_terminal_done_maps_app_errors_with_their_own_code() -> None:
    async def gen():
        yield {"event": "message", "data": {"delta": "x"}}
        raise AppError("Plan limit reached.")

    events = [event async for event in ensure_terminal_done(gen())]

    assert [event["event"] for event in events] == ["message", "error", "done"]
    assert events[1]["data"]["code"] == "APP_ERROR"
    assert events[1]["data"]["message"] == "Plan limit reached."
    assert events[2]["data"]["status"] == "failed"
    assert events[2]["data"]["code"] == "APP_ERROR"


async def test_terminal_done_synthesizes_failed_done_on_silent_close() -> None:
    async def gen():
        yield {"event": "sources", "data": {"sources": []}}

    events = [event async for event in ensure_terminal_done(gen())]

    assert [event["event"] for event in events] == ["sources", "done"]
    assert events[1]["data"]["status"] == "failed"
    assert events[1]["data"]["code"] == "INTERNAL_ERROR"


async def test_terminal_done_preserves_existing_failed_status() -> None:
    """A producer that already sets `status` is never overwritten."""

    async def gen():
        yield {"event": "done", "data": {"status": "completed", "custom": 1}}

    events = [event async for event in ensure_terminal_done(gen())]

    assert len(events) == 1
    assert events[0]["data"] == {
        "status": "completed",
        "custom": 1,
        "request_id": "-",
    }


# ---------------------------------------------------------------------------
# Phase 2 tracing: done/error frames carry the current request id
# ---------------------------------------------------------------------------


async def test_terminal_done_stamps_request_id_on_done_and_error_frames() -> None:
    """The middleware-set request id lands on every terminal frame."""
    token = request_id_var.set("trace-42")
    try:

        async def success_gen():
            yield {"event": "message", "data": {"delta": "Hi"}}
            yield {"event": "done", "data": {"session_id": "s1"}}

        events = [event async for event in ensure_terminal_done(success_gen())]
        assert events[-1]["data"]["request_id"] == "trace-42"
        assert events[-1]["data"]["session_id"] == "s1"

        async def error_gen():
            yield {
                "event": "error",
                "data": {"code": "GENERATION_FAILED", "message": "boom"},
            }

        events = [event async for event in ensure_terminal_done(error_gen())]
        assert [event["event"] for event in events] == ["error", "done"]
        assert events[0]["data"]["request_id"] == "trace-42"
        assert events[1]["data"]["status"] == "failed"
        assert events[1]["data"]["request_id"] == "trace-42"
    finally:
        request_id_var.reset(token)


async def test_terminal_done_stamps_request_id_on_unexpected_failure_frames() -> None:
    token = request_id_var.set("trace-9")
    try:

        async def gen():
            yield {"event": "message", "data": {"delta": "partial"}}
            raise RuntimeError("socket exploded")

        events = [event async for event in ensure_terminal_done(gen())]

        assert [event["event"] for event in events] == ["message", "error", "done"]
        assert events[1]["data"]["request_id"] == "trace-9"
        assert events[2]["data"]["request_id"] == "trace-9"
    finally:
        request_id_var.reset(token)


async def test_terminal_done_never_overwrites_producer_request_id() -> None:
    token = request_id_var.set("trace-from-middleware")
    try:

        async def gen():
            yield {"event": "done", "data": {"status": "completed", "request_id": "mine"}}

        events = [event async for event in ensure_terminal_done(gen())]

        assert events[0]["data"]["request_id"] == "mine"
    finally:
        request_id_var.reset(token)


async def test_terminal_done_generator_exit_propagates_without_extra_frames() -> None:
    finalized: list[str] = []

    async def gen():
        try:
            yield {"event": "message", "data": {"delta": "a"}}
            yield {"event": "message", "data": {"delta": "b"}}
        finally:
            finalized.append("closed")

    iterator = ensure_terminal_done(gen())
    first = await anext(iterator)
    assert first["event"] == "message"

    await iterator.aclose()

    assert finalized == ["closed"]


async def test_terminal_done_cancelled_error_propagates() -> None:
    import asyncio

    async def gen():
        yield {"event": "message", "data": {"delta": "a"}}
        raise asyncio.CancelledError()

    iterator = ensure_terminal_done(gen())
    await anext(iterator)

    with pytest.raises(asyncio.CancelledError):
        await anext(iterator)


# ---------------------------------------------------------------------------
# Buffered streaming tests
# ---------------------------------------------------------------------------


async def test_buffered_stream_coalesces_message_deltas() -> None:
    """Multiple message deltas within the buffer window merge into one frame."""
    request = FakeRequest()

    async def _delta_events():
        for i in range(5):
            yield {"event": "message", "data": {"delta": f"t{i}"}}
        yield {"event": "done", "data": {"ok": True}}

    frames = [
        frame
        async for frame in buffered_stream_with_disconnect(
            request, _delta_events(), buffer_ms=200.0
        )
    ]
    # Deltas are buffered until the done event flushes them.
    message_frames = [f for f in frames if "message" in f]
    done_frames = [f for f in frames if "done" in f]
    assert len(done_frames) == 1
    # All deltas should be in a single merged message frame.
    assert len(message_frames) == 1
    assert "t0t1t2t3t4" in message_frames[0]


async def test_buffered_stream_flushes_non_message_immediately() -> None:
    """Non-message events (sources, done, error) flush the buffer and yield immediately."""
    request = FakeRequest()

    async def _mixed_events():
        yield {"event": "message", "data": {"delta": "a"}}
        yield {"event": "sources", "data": {"sources": []}}
        yield {"event": "message", "data": {"delta": "b"}}
        yield {"event": "done", "data": {}}

    frames = [
        frame
        async for frame in buffered_stream_with_disconnect(
            request, _mixed_events(), buffer_ms=500.0
        )
    ]
    # "a" buffered, "sources" flushes "a" + yields sources, "b" buffered, "done" flushes "b"
    assert any("sources" in f for f in frames)
    assert any("done" in f for f in frames)
    message_frames = [f for f in frames if "event: message" in f]
    assert len(message_frames) == 2  # "a" flushed before sources, "b" flushed before done


async def test_buffered_stream_stops_on_disconnect() -> None:
    """Buffered stream stops when the client disconnects mid-stream."""
    request = FakeRequest()

    async def _slow_events():
        yield {"event": "message", "data": {"delta": "a"}}
        request.set_disconnected(True)
        yield {"event": "message", "data": {"delta": "b"}}

    frames = [
        frame
        async for frame in buffered_stream_with_disconnect(request, _slow_events(), buffer_ms=50.0)
    ]
    # Only the first delta is yielded; the disconnect stops the stream.
    assert len(frames) == 1
    assert "a" in frames[0]


async def test_buffered_stream_preflights_closed_connection() -> None:
    """Buffered stream returns no frames when the connection is already closed."""
    request = FakeRequest(disconnected=True)

    async def _events():
        yield {"event": "message", "data": {"delta": "x"}}

    frames = [
        frame async for frame in buffered_stream_with_disconnect(request, _events(), buffer_ms=50.0)
    ]
    assert frames == []


# ---------------------------------------------------------------------------
# stream_answer_with_usage with buffer_ms
# ---------------------------------------------------------------------------


class FakeUsageService:
    """Minimal usage service for testing."""

    async def check_limit(self, tenant_id: str, *, event_type: str) -> None:
        pass

    async def record_usage(self, **kwargs: Any) -> None:
        pass


async def test_stream_answer_with_usage_buffer_ms_passthrough() -> None:
    """When buffer_ms > 0, buffered_stream_with_disconnect is used internally."""
    request = FakeRequest()

    async def _chat_events():
        yield {"event": "sources", "data": {"sources": []}}
        yield {"event": "message", "data": {"delta": "Hello "}}
        yield {"event": "message", "data": {"delta": "world"}}
        yield {
            "event": "done",
            "data": {"session_id": "s1", "input_tokens": 5, "output_tokens": 10},
        }

    usage = FakeUsageService()
    frames = [
        frame
        async for frame in stream_answer_with_usage(
            request,
            _chat_events(),
            usage=usage,
            tenant_id="t1",
            user_id=None,
            website_id="w1",
            buffer_ms=200.0,
        )
    ]
    # With buffering, the two message deltas merge into one frame.
    message_frames = [f for f in frames if "event: message" in f]
    assert len(message_frames) == 1
    assert "Hello world" in message_frames[0]
    assert any("done" in f for f in frames)


async def test_stream_answer_with_usage_no_buffer() -> None:
    """When buffer_ms is 0, raw per-token frames are yielded (no coalescing)."""
    request = FakeRequest()

    async def _chat_events():
        yield {"event": "sources", "data": {"sources": []}}
        yield {"event": "message", "data": {"delta": "A"}}
        yield {"event": "message", "data": {"delta": "B"}}
        yield {"event": "done", "data": {"session_id": "s1"}}

    usage = FakeUsageService()
    frames = [
        frame
        async for frame in stream_answer_with_usage(
            request,
            _chat_events(),
            usage=usage,
            tenant_id="t1",
            user_id=None,
            website_id="w1",
            buffer_ms=0.0,
        )
    ]
    message_frames = [f for f in frames if "event: message" in f]
    assert len(message_frames) == 2  # each delta is its own frame


# ---------------------------------------------------------------------------
# SSE transport timing
# ---------------------------------------------------------------------------


async def test_stream_answer_with_usage_logs_sse_transport(caplog) -> None:
    """stream_answer_with_usage emits a sse_transport log with timing data."""
    import logging

    request = FakeRequest()

    async def _chat_events():
        yield {"event": "sources", "data": {"sources": []}}
        yield {"event": "message", "data": {"delta": "Hello "}}
        yield {"event": "message", "data": {"delta": "world"}}
        yield {
            "event": "done",
            "data": {"session_id": "s1", "input_tokens": 5, "output_tokens": 10},
        }

    usage = FakeUsageService()
    with caplog.at_level(logging.INFO, logger="webchat_ai"):
        frames = [
            frame
            async for frame in stream_answer_with_usage(
                request,
                _chat_events(),
                usage=usage,
                tenant_id="t1",
                user_id=None,
                website_id="w1",
                buffer_ms=0.0,
            )
        ]

    assert len(frames) > 0
    records = [r for r in caplog.records if r.getMessage() == "sse_transport"]
    assert len(records) == 1
    record = records[0]
    assert record.events_yielded > 0
    assert record.sse_transport_ms >= 0
    assert record.tenant_id == "t1"
    assert record.buffer_ms == 0.0
    assert record.first_event_ms is not None
    assert record.first_event_ms >= 0
    assert record.first_token_ms is not None
    assert record.first_token_ms >= 0


# ---------------------------------------------------------------------------
# Billing gate + usage recording with terminal states
# ---------------------------------------------------------------------------


class _RecordingUsageService(FakeUsageService):
    """Records every event_type so tests can assert exact billing calls."""

    def __init__(self, *, limit_error: AppError | None = None) -> None:
        self.recorded: list[tuple[str, int]] = []
        self._limit_error = limit_error

    async def check_limit(self, tenant_id: str, *, event_type: str) -> None:
        if self._limit_error is not None:
            raise self._limit_error

    async def record_usage(self, **kwargs: Any) -> None:
        self.recorded.append((kwargs["event_type"], kwargs.get("quantity", 1)))


async def test_stream_answer_with_usage_gate_emits_failed_terminal() -> None:
    """An exhausted plan opens with error + terminal done(status=failed)."""
    request = FakeRequest()
    usage = _RecordingUsageService(limit_error=AppError("Monthly messages_sent limit reached."))

    async def _never_called():  # pragma: no cover - pipeline must not start
        yield {"event": "done", "data": {}}

    frames = [
        frame
        async for frame in stream_answer_with_usage(
            request,
            _never_called(),
            usage=usage,
            tenant_id="t1",
            user_id=None,
            website_id="w1",
        )
    ]
    events = _parse_frames(frames)

    assert [name for name, _ in events] == ["error", "done"]
    assert events[0][1]["code"] == "APP_ERROR"
    assert events[1][1]["status"] == "failed"
    assert usage.recorded == []


async def test_stream_answer_with_usage_gate_frames_include_request_id() -> None:
    """Pre-stream LIMIT_REACHED frames carry the request id (Phase 2)."""
    token = request_id_var.set("trace-7")
    try:
        request = FakeRequest()
        usage = _RecordingUsageService(limit_error=AppError("Monthly messages_sent limit reached."))

        async def _never_called():  # pragma: no cover - pipeline must not start
            yield {"event": "done", "data": {}}

        frames = [
            frame
            async for frame in stream_answer_with_usage(
                request,
                _never_called(),
                usage=usage,
                tenant_id="t1",
                user_id=None,
                website_id="w1",
            )
        ]
        events = _parse_frames(frames)

        assert [name for name, _ in events] == ["error", "done"]
        assert events[0][1]["request_id"] == "trace-7"
        assert events[1][1]["status"] == "failed"
        assert events[1][1]["request_id"] == "trace-7"
    finally:
        request_id_var.reset(token)


async def test_recording_skips_failed_done_but_bills_completed_done() -> None:
    request = FakeRequest()

    async def _events():
        yield {"event": "sources", "data": {"sources": []}}
        yield {"event": "message", "data": {"delta": "Hi"}}
        yield {
            "event": "done",
            "data": {"session_id": "s1", "input_tokens": 5, "output_tokens": 10},
        }

    usage = _RecordingUsageService()
    frames = [
        frame
        async for frame in stream_answer_with_usage(
            request,
            ensure_terminal_done(_events()),
            usage=usage,
            tenant_id="t1",
            user_id=None,
            website_id="w1",
        )
    ]

    assert [frame.split("\n")[0] for frame in frames][-1] == "event: done"
    assert usage.recorded == [("messages_sent", 1), ("ai_responses", 1), ("tokens_used", 15)]


async def test_recording_skips_billing_on_failed_terminal_done() -> None:
    request = FakeRequest()

    async def _events():
        yield {"event": "sources", "data": {"sources": []}}
        yield {"event": "error", "data": {"code": "GENERATION_FAILED", "message": "boom"}}
        return

    usage = _RecordingUsageService()
    wrapped = ensure_terminal_done(_events())
    frames = [
        frame
        async for frame in stream_answer_with_usage(
            request,
            wrapped,
            usage=usage,
            tenant_id="t1",
            user_id=None,
            website_id="w1",
        )
    ]
    events = _parse_frames(frames)

    assert [name for name, _ in events] == ["sources", "error", "done"]
    assert events[-1][1]["status"] == "failed"
    # The sent message is billed at `sources` (existing behavior), but the
    # failed turn records no ai_responses / tokens_used.
    assert usage.recorded == [("messages_sent", 1)]


# ---------------------------------------------------------------------------
# SSE heartbeats during silent generation (audit S-03)
# ---------------------------------------------------------------------------


async def test_heartbeat_emitted_during_silent_stream() -> None:
    """A silent upstream produces `: ping` comments between real frames."""
    import asyncio

    request = FakeRequest()

    async def _silent_events():
        yield {"event": "sources", "data": {"sources": []}}
        await asyncio.sleep(0.18)  # > 3 heartbeat intervals
        yield {"event": "message", "data": {"delta": "late answer"}}
        yield {"event": "done", "data": {"session_id": "s1"}}

    usage = FakeUsageService()
    frames = [
        frame
        async for frame in stream_answer_with_usage(
            request,
            _silent_events(),
            usage=usage,
            tenant_id="t1",
            user_id=None,
            website_id="w1",
            heartbeat_interval_s=0.05,
        )
    ]

    pings = [frame for frame in frames if frame == ": ping\n\n"]
    assert len(pings) >= 2  # silence spanned several heartbeat intervals


async def test_heartbeats_never_reorder_or_delay_application_events() -> None:
    """Real frames keep their exact sequence; pings only appear between them."""
    import asyncio

    request = FakeRequest()

    async def _slow_events():
        yield {"event": "sources", "data": {"sources": []}}
        await asyncio.sleep(0.12)
        yield {"event": "message", "data": {"delta": "a"}}
        await asyncio.sleep(0.12)
        yield {"event": "done", "data": {}}

    usage = FakeUsageService()
    frames = [
        frame
        async for frame in stream_answer_with_usage(
            request,
            _slow_events(),
            usage=usage,
            tenant_id="t1",
            user_id=None,
            website_id="w1",
            buffer_ms=0.0,
            heartbeat_interval_s=0.03,
        )
    ]

    parsed = _parse_frames([f for f in frames if not f.startswith(":")])
    assert [name for name, _ in parsed] == ["sources", "message", "done"]
    # Pings (if any) sit strictly between application frames, never after done.
    assert frames[-1].startswith("event: done")


async def test_fast_stream_emits_no_heartbeats() -> None:
    """Streams that never go quiet carry no comment noise."""
    request = FakeRequest()

    async def _chat_events():
        yield {"event": "sources", "data": {"sources": []}}
        yield {"event": "message", "data": {"delta": "Hi"}}
        yield {"event": "done", "data": {}}

    usage = FakeUsageService()
    frames = [
        frame
        async for frame in stream_answer_with_usage(
            request,
            _chat_events(),
            usage=usage,
            tenant_id="t1",
            user_id=None,
            website_id="w1",
            heartbeat_interval_s=15.0,
        )
    ]
    assert all(not frame.startswith(":") for frame in frames)


async def test_with_heartbeats_passes_frames_through_unchanged() -> None:
    """Direct unit check: an already-live stream yields identical bytes."""

    async def _fast():
        for i in range(3):
            yield sse("message", {"delta": str(i)})

    out = [frame async for frame in with_heartbeats(_fast(), interval_s=15.0)]
    assert len(out) == 3
    assert all(frame.startswith("event: message") for frame in out)


async def test_with_heartbeats_closes_upstream_on_generator_exit() -> None:
    """Disconnect cleanup: pending pull cancelled, upstream finalized."""
    import asyncio

    finalized: list[str] = []

    async def _upstream():
        try:
            yield sse("message", {"delta": "a"})
            await asyncio.sleep(5)  # long pull in flight
            yield sse("done", {})
        finally:
            finalized.append("closed")

    iterator = with_heartbeats(_upstream(), interval_s=0.01)
    first = await anext(iterator)
    assert first.startswith("event: message")

    await iterator.aclose()  # must not hang on the in-flight pull

    assert finalized == ["closed"]


# ---------------------------------------------------------------------------
# Disconnect cleanup without yield-in-finally (audit S-08)
# ---------------------------------------------------------------------------


async def test_buffered_disconnect_cleanup_never_yields_and_finalizes_upstream() -> None:
    """Closing mid-await with a dirty buffer must not raise RuntimeError.

    Reproduces audit S-08: deltas coalesce (no deadline reached), the client
    disconnects while the generator waits for the next event, and Starlette
    closes the response iterator - the old `finally` flushed by yielding
    during GeneratorExit cleanup and died with RuntimeError.
    """
    import asyncio
    from contextlib import suppress

    request = FakeRequest()
    finalized: list[str] = []
    block = asyncio.Event()

    async def _events():
        try:
            yield {"event": "message", "data": {"delta": "a"}}
            yield {"event": "message", "data": {"delta": "b"}}  # buffered, unflushed
            await block.wait()  # next event never arrives
        finally:
            finalized.append("closed")

    gen = buffered_stream_with_disconnect(request, _events(), buffer_ms=60_000.0)
    pull = asyncio.ensure_future(anext(gen))
    await asyncio.sleep(0.02)  # let both deltas buffer; generator now blocked
    assert not pull.done()

    pull.cancel()
    with suppress(asyncio.CancelledError):
        await pull
    await gen.aclose()  # RuntimeError here means yield-during-cleanup survived

    assert finalized == ["closed"]


async def test_buffered_stream_flushes_trailing_deltas_on_normal_completion() -> None:
    """A bare stream that ends without a terminal event still delivers its tail.

    The S-08 fix moved the trailing flush out of `finally`; normal completion
    must keep delivering coalesced leftovers.
    """
    request = FakeRequest()
    finalized: list[str] = []

    async def _events():
        try:
            yield {"event": "message", "data": {"delta": "x"}}
            yield {"event": "message", "data": {"delta": "y"}}
        finally:
            finalized.append("closed")

    frames = [
        frame
        async for frame in buffered_stream_with_disconnect(request, _events(), buffer_ms=60_000.0)
    ]

    assert len(frames) == 1
    assert "xy" in frames[0]
    assert finalized == ["closed"]


async def test_buffered_stream_disconnect_flushes_live_tail_before_close() -> None:
    """The disconnect-break path is live control flow: the tail still flushes.

    Only GeneratorExit cleanup (the generator being closed mid-await) must be
    yield-free (audit S-08); a loop `break` after `is_disconnected()` is an
    ordinary exit that preserves the pre-fix tail delivery.
    """
    request = FakeRequest()
    finalized: list[str] = []

    async def _events():
        try:
            yield {"event": "sources", "data": {"sources": []}}  # yields a frame
            yield {"event": "message", "data": {"delta": "tail"}}  # stays buffered
            request.set_disconnected(True)
            yield {"event": "message", "data": {"delta": "never"}}
        finally:
            finalized.append("closed")

    frames = [
        frame
        async for frame in buffered_stream_with_disconnect(request, _events(), buffer_ms=60_000.0)
    ]

    assert [f.split("\n")[0] for f in frames] == ["event: sources", "event: message"]
    assert "tail" in frames[1]
    assert finalized == ["closed"]


# ---------------------------------------------------------------------------
# Audit S-18: interval flush (time-driven, not traffic-driven)
# ---------------------------------------------------------------------------


async def test_buffered_stream_flushes_at_deadline_without_upstream_input() -> None:
    """Buffered deltas must be delivered at the flush deadline even when the
    upstream stays silent - not held until the *next* delta arrives (S-18)."""
    request = FakeRequest()

    async def _paused_events():
        yield {"event": "message", "data": {"delta": "a"}}
        await asyncio.sleep(0.3)  # model pause longer than the buffer window
        yield {"event": "message", "data": {"delta": "b"}}
        yield {"event": "done", "data": {}}

    received: list[tuple[str, float]] = []
    start = time.monotonic()
    async for frame in buffered_stream_with_disconnect(request, _paused_events(), buffer_ms=50.0):
        received.append((frame, time.monotonic() - start))

    message_frames = [(frame, at) for frame, at in received if frame.startswith("event: message")]
    assert len(message_frames) == 2

    def _delta(frame: str) -> str:
        payload_line = next(line for line in frame.splitlines() if line.startswith("data: "))
        return str(json.loads(payload_line[len("data: ") :]).get("delta", ""))

    # "a" ships at the ~50ms deadline, well before the producer resumes at
    # ~300ms; under the old lazy flush it was withheld until "b" arrived.
    first_frame, first_at = message_frames[0]
    assert _delta(first_frame) == "a"
    assert first_at < 0.25
    second_frame, second_at = message_frames[1]
    assert _delta(second_frame) == "b"
    assert second_at > first_at
    assert any(frame.startswith("event: done") for frame, _at in received)


async def test_buffered_stream_interval_flush_preserves_content_order() -> None:
    """Repeated pauses each flush exactly the deltas accumulated so far,
    preserving text order and never duplicating or dropping content."""
    request = FakeRequest()

    async def _stuttering_events():
        yield {"event": "message", "data": {"delta": "a"}}
        await asyncio.sleep(0.12)
        yield {"event": "message", "data": {"delta": "b"}}
        await asyncio.sleep(0.12)
        yield {"event": "message", "data": {"delta": "c"}}
        yield {"event": "done", "data": {}}

    frames = [
        frame
        async for frame in buffered_stream_with_disconnect(
            request, _stuttering_events(), buffer_ms=30.0
        )
    ]
    message_frames = [f for f in frames if f.startswith("event: message")]

    def _delta(frame: str) -> str:
        payload_line = next(line for line in frame.splitlines() if line.startswith("data: "))
        return str(json.loads(payload_line[len("data: ") :]).get("delta", ""))

    deltas = "".join(_delta(f) for f in message_frames)
    assert deltas == "abc"
    assert sum(1 for f in frames if f.startswith("event: done")) == 1


async def test_buffered_stream_fast_deltas_still_coalesce() -> None:
    """The S-18 interval flush must not regress coalescing: a burst inside one
    window still ships as a single merged frame."""
    request = FakeRequest()

    async def _burst_events():
        for i in range(5):
            yield {"event": "message", "data": {"delta": f"t{i}"}}
        yield {"event": "done", "data": {}}

    frames = [
        frame
        async for frame in buffered_stream_with_disconnect(
            request, _burst_events(), buffer_ms=200.0
        )
    ]
    message_frames = [f for f in frames if f.startswith("event: message")]
    assert len(message_frames) == 1
    assert "t0t1t2t3t4" in message_frames[0]


# ---------------------------------------------------------------------------
# Audit disconnect-cleanup / long-stream memory leaks: deterministic teardown
# ---------------------------------------------------------------------------


async def test_buffered_stream_cancels_pending_pull_on_close() -> None:
    """Closing the stream mid-pause must cancel the in-flight upstream pull
    (no dangling pipeline tasks on a long-lived process) and close the inner
    generator so its bookkeeping `finally` runs immediately."""
    request = FakeRequest()
    finalized: list[str] = []
    release = asyncio.Event()

    async def _paused_events():
        try:
            yield {"event": "message", "data": {"delta": "x"}}
            await release.wait()  # wrapper's pull is parked here when closed
            yield {"event": "done", "data": {}}
        finally:
            finalized.append("closed")

    iterator = buffered_stream_with_disconnect(request, _paused_events(), buffer_ms=10.0)
    first = await anext(iterator)  # deadline flush delivers the buffered delta
    assert "x" in first

    await iterator.aclose()
    assert finalized == ["closed"]


async def test_stream_answer_with_usage_closes_pipeline_on_abandonment() -> None:
    """Abandoning the transport closes the ENTIRE wrapper chain (heartbeats →
    disconnect/buffer → recording → metrics → pipeline) deterministically."""
    request = FakeRequest()
    finalized: list[str] = []

    async def _events():
        try:
            yield {"event": "sources", "data": {"sources": []}}
            yield {"event": "done", "data": {"input_tokens": 1, "output_tokens": 1}}
        finally:
            finalized.append("closed")

    iterator = stream_answer_with_usage(
        request,
        _events(),
        usage=FakeUsageService(),
        tenant_id="t1",
        user_id=None,
        website_id="w1",
        buffer_ms=0.0,
    )
    first = await anext(iterator)
    assert first.startswith("event:")

    await iterator.aclose()
    assert finalized == ["closed"]


async def test_heartbeats_close_upstream_when_consumer_stops() -> None:
    """`with_heartbeats` teardown (cancel pending pull + close upstream) runs
    when the consumer abandons the stream during a silent stretch."""
    finalized: list[str] = []
    release = asyncio.Event()

    async def _silent_events():
        try:
            yield sse("sources", {"sources": []})
            await release.wait()
            yield sse("done", {})
        finally:
            finalized.append("closed")

    iterator = with_heartbeats(_silent_events(), interval_s=0.01)
    first = await anext(iterator)
    assert first.startswith("event:")  # real event passes through unchanged
    ping = await anext(iterator)
    assert ping == ": ping\n\n"

    await iterator.aclose()
    assert finalized == ["closed"]
