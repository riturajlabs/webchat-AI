"""Public widget API (Phase 8, ADR-004): config, sessions, streaming chat, feedback.

Mounted at `/api/widget/v1`. Four surfaces:

    GET  /api/widget/v1/config/{widget_id}   public, Redis-cached (5 min)
    POST /api/widget/v1/sessions             public, rate-limited token mint
    POST /api/widget/v1/chat                 Bearer widget-session token, SSE
    POST /api/widget/v1/feedback             Bearer widget-session token (Phase 12.4)

The chat endpoint adapts `RagService.stream_answer` with widget-derived
principal and limits - the pipeline itself is untouched (plan §2.3). Widget
session tokens are short-lived JWTs scoped to one widget+tenant+website+visitor
(plan §3.2); the conversation `session_id` in the request body is a separate,
non-secret identifier (plan §3.2.1).
"""

import logging
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from backend.api.deps import (
    get_feedback_service,
    get_rag_service,
    get_usage_service,
    get_widget_service,
    widget_chat_ip_limiter,
    widget_chat_limiter,
    widget_claims_origin_guard,
    widget_config_origin_guard,
    widget_feedback_limiter,
    widget_ip_limiter,
    widget_session_claims,
    widget_session_ip_limiter,
    widget_session_issue_limiter,
    widget_session_origin_guard,
    widget_visitor_limiter,
)
from backend.api.sse import ensure_terminal_done, sse, stream_answer_with_usage
from backend.core.config import get_settings
from backend.core.errors import AppError, SpamRejectedError
from backend.core.logging import get_request_id
from backend.schemas.feedback import WidgetFeedbackRequest
from backend.schemas.widget import (
    CreateWidgetSessionRequest,
    WidgetChatRequest,
    WidgetPublicConfig,
    WidgetSessionResponse,
)
from backend.services.billing import UsageService
from backend.services.chat.rag_service import RagService
from backend.services.feedback.feedback_service import FeedbackService
from backend.services.widget.spam_filter import is_spam
from backend.services.widget.widget_service import WidgetService

logger = logging.getLogger("webchat_ai")

router = APIRouter(
    prefix="/widget/v1",
    tags=["widget"],
)


@router.get("/config/{widget_id}", response_model=WidgetPublicConfig)
async def get_widget_config(
    widget_id: str,
    service: Annotated[WidgetService, Depends(get_widget_service)],
    _: Annotated[None, Depends(widget_config_origin_guard)],
    __: Annotated[None, Depends(widget_ip_limiter)],
) -> WidgetPublicConfig:
    """Return the public widget configuration (theme, branding, suggestions).

    Anonymous and cheap to serve; Redis-cached for 5 minutes. A suspended
    tenant's widget returns `enabled: false` rather than 403 (ADR-005).
    Browser embeds from domains outside the widget allowlist get a 403.
    """
    return await service.get_public_config(widget_id)


@router.post("/sessions", response_model=WidgetSessionResponse)
async def create_widget_session(
    body: CreateWidgetSessionRequest,
    service: Annotated[WidgetService, Depends(get_widget_service)],
    _: Annotated[None, Depends(widget_session_origin_guard)],
    __: Annotated[None, Depends(widget_session_issue_limiter)],
    ___: Annotated[None, Depends(widget_ip_limiter)],
    ____: Annotated[None, Depends(widget_session_ip_limiter)],
) -> WidgetSessionResponse:
    """Mint a short-lived widget-session token for an anonymous visitor.

    `visitor_id` is the non-PII anonymous cookie id (ADR-004); the token is
    kept in memory by the SDK and never persisted client-side. Beyond the
    per-widget issue budget, a dedicated per-IP burst budget (P0-4) bounds
    minting even when both entity keys are attacker-rotated.
    """
    token, expires_at = await service.create_session(
        widget_id=body.widget_id,
        visitor_id=body.visitor_id,
    )
    return WidgetSessionResponse(session_token=token, expires_at=expires_at)


@router.post("/chat")
async def widget_chat(
    body: WidgetChatRequest,
    request: Request,
    claims: Annotated[dict[str, Any], Depends(widget_session_claims)],
    service: Annotated[WidgetService, Depends(get_widget_service)],
    rag: Annotated[RagService, Depends(get_rag_service)],
    usage: Annotated[UsageService, Depends(get_usage_service)],
    _: Annotated[None, Depends(widget_chat_limiter)],
    __: Annotated[None, Depends(widget_visitor_limiter)],
    ___: Annotated[None, Depends(widget_claims_origin_guard)],
    ____: Annotated[None, Depends(widget_ip_limiter)],
    _____: Annotated[None, Depends(widget_chat_ip_limiter)],
) -> StreamingResponse:
    """Stream an answer for the visitor's question (SSE).

    Requires `Authorization: Bearer <widget_session_token>`. The token's claims
    are re-validated against the live widget/tenant/website state before the
    pipeline runs (ADR-004 tenant validation flow). Validation failures surface
    as SSE `error` events so the stream stays uniform; only auth/rate-limit
    rejections happen before the stream begins. The tenant's `messages_sent`
    plan limit is enforced before the pipeline runs (code `LIMIT_REACHED`).
    The stream stops the moment the client disconnects (no wasted generation
    tokens, no partial answer saved).
    """

    async def event_stream() -> AsyncIterator[str]:
        # Re-check the token claims against live state (never trust claims).
        try:
            await service.validate_chat(
                widget_id=claims["widget_id"],
                tenant_id=claims["tenant_id"],
                website_id=claims["website_id"],
            )
            # P0-2 visitor binding: the client-supplied session_id may only
            # resume a conversation owned by this token's tenant+website+
            # visitor triple (same SESSION_NOT_FOUND code as unknown ids).
            await service.validate_session_access(
                tenant_id=claims["tenant_id"],
                website_id=claims["website_id"],
                visitor_id=claims.get("visitor_id"),
                session_id=body.session_id,
            )
            if is_spam(body.question):
                raise SpamRejectedError("This message looks like spam.")
            await service.check_message_cap(
                widget_id=claims["widget_id"],
                visitor_id=claims.get("visitor_id"),
                session_id=body.session_id,
            )
        except AppError as exc:
            # Pre-stream rejection: the frame still carries the request id so
            # a blocked turn is traceable like a streamed one (Phase 2).
            yield sse(
                "error",
                {
                    "code": exc.code,
                    "message": exc.message,
                    "request_id": get_request_id(),
                },
            )
            return

        stream = ensure_terminal_done(
            rag.stream_answer(
                tenant_id=claims["tenant_id"],
                website_id=claims["website_id"],
                question=body.question,
                session_id=body.session_id,
                visitor_id=claims.get("visitor_id"),
                user_id=None,
            )
        )
        buffer_ms = get_settings().sse_buffer_ms
        async for frame in stream_answer_with_usage(
            request,
            stream,
            usage=usage,
            tenant_id=claims["tenant_id"],
            user_id=None,
            website_id=claims["website_id"],
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


@router.post("/feedback", status_code=204)
async def submit_feedback(
    body: WidgetFeedbackRequest,
    claims: Annotated[dict[str, Any], Depends(widget_session_claims)],
    service: Annotated[FeedbackService, Depends(get_feedback_service)],
    widgets: Annotated[WidgetService, Depends(get_widget_service)],
    _: Annotated[None, Depends(widget_feedback_limiter)],
    __: Annotated[None, Depends(widget_claims_origin_guard)],
    ___: Annotated[None, Depends(widget_ip_limiter)],
) -> None:
    """Record a visitor rating for an assistant answer.

    Requires `Authorization: Bearer <widget_session_token>`. The token's
    tenant/website are authoritative: the untrusted `message_id`/`session_id`
    are validated against them before anything is persisted - P0-2 visitor
    binding first (the conversation must belong to this token's visitor), then
    the feedback service verifies the message exists and belongs to this
    tenant/website/session. A repeat rating for the same message is
    idempotent. A per-visitor sliding-window budget (`WIDGET_FEEDBACK_LIMIT`)
    bounds abuse.
    """
    # P0-2: reject conversations that belong to a different visitor before
    # touching the message store (404 SESSION_NOT_FOUND, no existence oracle).
    await widgets.validate_session_access(
        tenant_id=claims["tenant_id"],
        website_id=claims["website_id"],
        visitor_id=claims.get("visitor_id"),
        session_id=body.session_id,
    )
    await service.submit(
        tenant_id=claims["tenant_id"],
        website_id=claims["website_id"],
        session_id=body.session_id,
        message_id=body.message_id,
        rating=body.rating,
        category=body.category,
        comment=body.comment,
    )


__all__ = ["router"]
