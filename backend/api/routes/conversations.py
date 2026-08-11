"""Conversation management endpoints (Phase 11.2).

Read/delete views over chat history. All routes require a valid bearer access
token with tenant role `owner` or `admin`. Tenant scoping comes from the
authenticated principal - the request path/query can never select another
tenant's conversations (00-AI-Development-Rules §7).

    GET    /api/conversations            paginated list (search + website filter)
    GET    /api/conversations/{id}       detail with full message history
    DELETE /api/conversations/{id}       delete a conversation (session + messages)
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response

from backend.api.deps import (
    client_ip,
    conversations_limiter,
    current_user,
    get_conversation_service,
    require_role,
)
from backend.schemas.conversations import (
    MAX_CONVERSATION_SEARCH_LENGTH,
    MAX_LIST_PAGE_SIZE,
    ConversationDetail,
    ConversationListResponse,
    ConversationMessageOut,
    ConversationSummary,
)
from backend.services.auth import Principal
from backend.services.conversations.conversation_service import ConversationService

router = APIRouter(
    prefix="/conversations",
    tags=["conversations"],
    dependencies=[Depends(require_role("owner", "admin"))],
)


@router.get("", response_model=ConversationListResponse)
async def list_conversations(
    principal: Annotated[Principal, Depends(current_user)],
    service: Annotated[ConversationService, Depends(get_conversation_service)],
    _: Annotated[None, Depends(conversations_limiter)],
    response: Response,
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=MAX_LIST_PAGE_SIZE)] = 20,
    search: Annotated[
        str | None,
        Query(max_length=MAX_CONVERSATION_SEARCH_LENGTH, description="Filter by message content"),
    ] = None,
    website_id: Annotated[str | None, Query(description="Filter by website")] = None,
) -> ConversationListResponse:
    items, total = await service.list_conversations(
        principal.tenant_id,
        page=page,
        per_page=per_page,
        search=search,
        website_id=website_id,
    )
    response.headers["X-Total-Count"] = str(total)
    return ConversationListResponse(
        items=[
            ConversationSummary(
                id=item.id,
                website_id=item.website_id,
                visitor_id=item.visitor_id,
                title=item.title,
                message_count=item.message_count,
                last_message=item.last_message,
                status=item.status,
                created_at=item.created_at,
                updated_at=item.updated_at,
            )
            for item in items
        ],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/{session_id}", response_model=ConversationDetail)
async def get_conversation(
    session_id: str,
    principal: Annotated[Principal, Depends(current_user)],
    service: Annotated[ConversationService, Depends(get_conversation_service)],
    _: Annotated[None, Depends(conversations_limiter)],
) -> ConversationDetail:
    item = await service.get_conversation(principal.tenant_id, session_id)
    return ConversationDetail(
        id=item.id,
        website_id=item.website_id,
        visitor_id=item.visitor_id,
        title=item.title,
        status=item.status,
        created_at=item.created_at,
        updated_at=item.updated_at,
        messages=[
            ConversationMessageOut(
                role=message.role,
                content=message.content,
                sources=message.sources,
                response_time=message.response_time,
                input_tokens=message.input_tokens,
                output_tokens=message.output_tokens,
                created_at=message.created_at,
            )
            for message in item.messages
        ],
    )


@router.delete("/{session_id}", status_code=204)
async def delete_conversation(
    session_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(current_user)],
    service: Annotated[ConversationService, Depends(get_conversation_service)],
    _: Annotated[None, Depends(conversations_limiter)],
) -> None:
    await service.delete_conversation(
        principal.tenant_id,
        session_id,
        user_id=principal.user_id,
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )


__all__ = ["router"]
