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
(hallucination guard - docs/06 Phase 6 rules). If the client disconnects
mid-stream the pipeline stops at the next chunk boundary - no further tokens
are consumed and the partial answer is not persisted.
"""

import logging
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from backend.api.deps import (
    chat_limiter,
    current_principal,
    enforce_api_key_rate_limit,
    get_llm_quota_service,
    get_rag_service,
    get_usage_service,
    require_principal_role,
)
from backend.api.sse import ensure_terminal_done, stream_answer_with_usage
from backend.core.config import get_settings
from backend.core.errors import AIQuotaExceededError
from backend.core.quota import LLMQuotaService
from backend.schemas.chat import ChatRequest
from backend.services.api_keys import ApiKeyPrincipal
from backend.services.auth import Principal
from backend.services.billing import UsageService
from backend.services.chat.rag_service import RagService

logger = logging.getLogger("webchat_ai")

router = APIRouter(
    prefix="/chat",
    tags=["chat"],
    dependencies=[Depends(require_principal_role("owner", "admin"))],
)


@router.post("/stream")
async def stream_chat(
    body: ChatRequest,
    request: Request,
    principal: Annotated[Principal | ApiKeyPrincipal, Depends(current_principal)],
    service: Annotated[RagService, Depends(get_rag_service)],
    usage: Annotated[UsageService, Depends(get_usage_service)],
    quota: Annotated[LLMQuotaService, Depends(get_llm_quota_service)],
    _: Annotated[None, Depends(chat_limiter)],
    __: Annotated[None, Depends(enforce_api_key_rate_limit)],
) -> Response:
    """Stream an answer for `question` from the tenant's knowledge base.

    The `messages_sent` plan limit is enforced before the pipeline runs; when
    exhausted the stream opens with an `error` frame (code `LIMIT_REACHED`).
    The per-tenant AI quota (Phase 14.9.4) is checked first and, when exhausted,
    the request is rejected with HTTP 429 before any LLM token is generated.
    """

    # Per-tenant AI spending protection (Phase 14.9.4): reject before any LLM
    # token is generated so an exhausted quota costs nothing.
    try:
        await quota.check(principal.tenant_id)
    except AIQuotaExceededError as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.message, "code": exc.code},
        )

    async def event_stream() -> AsyncIterator[str]:
        buffer_ms = get_settings().sse_buffer_ms
        async for frame in stream_answer_with_usage(
            request,
            ensure_terminal_done(
                service.stream_answer(
                    tenant_id=principal.tenant_id,
                    website_id=body.website_id,
                    question=body.question,
                    session_id=body.session_id,
                    visitor_id=body.visitor_id,
                    user_id=principal.user_id,
                )
            ),
            usage=usage,
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            website_id=body.website_id,
            buffer_ms=buffer_ms,
        ):
            yield frame

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


__all__ = ["router"]
