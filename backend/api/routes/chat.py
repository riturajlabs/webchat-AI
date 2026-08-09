"""Chat streaming endpoint (Phase 6, ADR-008).

`POST /api/chat/stream` answers a question with retrieval (tenant-filtered
Top-5) + Gemini streaming and returns a Server-Sent-Events stream:

    event: sources  data: {"sources": [{"chunk_id", "url", "title", "score", "citation"}]}
    event: message  data: {"delta": "..."}
    event: done     data: {"message_id", "session_id", "input_tokens",
                            "output_tokens", "response_time_ms", "created_at",
                            "prompt_version", "fallback"}
    event: error    data: {"code", "message"}

All errors surface as `error` events (200), except auth/role/rate-limit which
fail before the stream begins. The chatbot never answers without context
(hallucination guard - docs/06 Phase 6 rules).
"""

import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from backend.api.deps import chat_limiter, current_user, get_rag_service, require_role
from backend.schemas.chat import ChatRequest
from backend.services.auth import Principal
from backend.services.chat.rag_service import RagService

logger = logging.getLogger("webchat_ai")

router = APIRouter(
    prefix="/chat",
    tags=["chat"],
    dependencies=[Depends(require_role("owner", "admin"))],
)


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@router.post("/stream")
async def stream_chat(
    body: ChatRequest,
    principal: Annotated[Principal, Depends(current_user)],
    service: Annotated[RagService, Depends(get_rag_service)],
    _: Annotated[None, Depends(chat_limiter)],
) -> StreamingResponse:
    """Stream an answer for `question` from the tenant's knowledge base."""

    async def event_stream() -> AsyncIterator[str]:
        async for event in service.stream_answer(
            tenant_id=principal.tenant_id,
            website_id=body.website_id,
            question=body.question,
            session_id=body.session_id,
            visitor_id=body.visitor_id,
            user_id=principal.user_id,
        ):
            yield _sse(event["event"], event["data"])

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


__all__ = ["router"]
