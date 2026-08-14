"""Shared Server-Sent-Events helpers for streaming chat endpoints.

Both the dashboard chat (`/api/chat/stream`) and the public widget chat
(`/api/widget/v1/chat`) stream `RagService.stream_answer` events as SSE. The
`stream_with_disconnect` wrapper checks `request.is_disconnected()` before
every event so a client that closes the connection mid-stream stops the
pipeline promptly: generation is cancelled at the next chunk boundary, the
partial answer is never persisted, and no further tokens are consumed
(Sprint 1 P1 remediation).
"""

import json
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any

from fastapi import Request


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


__all__ = ["sse", "stream_with_disconnect"]
