"""Unit tests for the shared SSE streaming helpers (`backend/api/sse.py`).

The `stream_with_disconnect` wrapper is the Sprint 1 P1 fix that stops chat
generation the moment a client disconnects: it pre-flights the connection and
finalizes the inner generator on disconnect so partial answers are never
persisted and no further tokens are consumed.
"""

from typing import Any

import pytest
from backend.api.sse import sse, stream_with_disconnect


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
    assert sse("delta", {"chunk": "hello"}) == (
        'event: delta\ndata: {"chunk": "hello"}\n\n'
    )


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
