"""Public widget API (Phase 8, ADR-004): config, sessions, and streaming chat.

Mounted at `/api/widget/v1`. Three surfaces:

    GET  /api/widget/v1/config/{widget_id}   public, Redis-cached (5 min)
    POST /api/widget/v1/sessions             public, rate-limited token mint
    POST /api/widget/v1/chat                 Bearer widget-session token, SSE

The chat endpoint adapts `RagService.stream_answer` with widget-derived
principal and limits - the pipeline itself is untouched (plan §2.3). Widget
session tokens are short-lived JWTs scoped to one widget+tenant+website+visitor
(plan §3.2); the conversation `session_id` in the request body is a separate,
non-secret identifier (plan §3.2.1).
"""

import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from backend.api.deps import (
    get_rag_service,
    get_widget_service,
    widget_chat_limiter,
    widget_session_claims,
    widget_session_issue_limiter,
    widget_visitor_limiter,
)
from backend.core.errors import AppError, SpamRejectedError
from backend.schemas.widget import (
    CreateWidgetSessionRequest,
    WidgetChatRequest,
    WidgetPublicConfig,
    WidgetSessionResponse,
)
from backend.services.chat.rag_service import RagService
from backend.services.widget.spam_filter import is_spam
from backend.services.widget.widget_service import WidgetService

logger = logging.getLogger("webchat_ai")

router = APIRouter(
    prefix="/widget/v1",
    tags=["widget"],
)


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@router.get("/config/{widget_id}", response_model=WidgetPublicConfig)
async def get_widget_config(
    widget_id: str,
    service: Annotated[WidgetService, Depends(get_widget_service)],
) -> WidgetPublicConfig:
    """Return the public widget configuration (theme, branding, suggestions).

    Anonymous and cheap to serve; Redis-cached for 5 minutes. A suspended
    tenant's widget returns `enabled: false` rather than 403 (ADR-005).
    """
    return await service.get_public_config(widget_id)


@router.post("/sessions", response_model=WidgetSessionResponse)
async def create_widget_session(
    body: CreateWidgetSessionRequest,
    service: Annotated[WidgetService, Depends(get_widget_service)],
    _: Annotated[None, Depends(widget_session_issue_limiter)],
) -> WidgetSessionResponse:
    """Mint a short-lived widget-session token for an anonymous visitor.

    `visitor_id` is the non-PII anonymous cookie id (ADR-004); the token is
    kept in memory by the SDK and never persisted client-side.
    """
    token, expires_at = await service.create_session(
        widget_id=body.widget_id,
        visitor_id=body.visitor_id,
    )
    return WidgetSessionResponse(session_token=token, expires_at=expires_at)


@router.post("/chat")
async def widget_chat(
    body: WidgetChatRequest,
    claims: Annotated[dict[str, Any], Depends(widget_session_claims)],
    service: Annotated[WidgetService, Depends(get_widget_service)],
    rag: Annotated[RagService, Depends(get_rag_service)],
    _: Annotated[None, Depends(widget_chat_limiter)],
    __: Annotated[None, Depends(widget_visitor_limiter)],
) -> StreamingResponse:
    """Stream an answer for the visitor's question (SSE).

    Requires `Authorization: Bearer <widget_session_token>`. The token's claims
    are re-validated against the live widget/tenant/website state before the
    pipeline runs (ADR-004 tenant validation flow). Validation failures surface
    as SSE `error` events so the stream stays uniform; only auth/rate-limit
    rejections happen before the stream begins.
    """

    async def event_stream() -> AsyncIterator[str]:
        # Re-check the token claims against live state (never trust claims).
        try:
            await service.validate_chat(
                widget_id=claims["widget_id"],
                tenant_id=claims["tenant_id"],
                website_id=claims["website_id"],
            )
            if is_spam(body.question):
                raise SpamRejectedError("This message looks like spam.")
            await service.check_message_cap(
                widget_id=claims["widget_id"],
                visitor_id=claims.get("visitor_id"),
                session_id=body.session_id,
            )
        except AppError as exc:
            yield _sse("error", {"code": exc.code, "message": exc.message})
            return

        async for event in rag.stream_answer(
            tenant_id=claims["tenant_id"],
            website_id=claims["website_id"],
            question=body.question,
            session_id=body.session_id,
            visitor_id=claims.get("visitor_id"),
            user_id=None,
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
