"""Pydantic v2 response schemas for the conversations API (Phase 11.2)."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel

# Display text limits (00-AI-Development-Rules: validate all requests).
MAX_CONVERSATION_SEARCH_LENGTH = 120
MAX_LIST_PAGE_SIZE = 100
MAX_TITLE_LENGTH = 100
MAX_MESSAGE_PREVIEW_LENGTH = 200


class ConversationSummary(BaseModel):
    """A row in the conversation list (docs/04, Phase 11.2 UI)."""

    # `session_id` is the public, non-secret conversation key (docs/05 §9).
    id: str
    website_id: str
    visitor_id: str | None
    title: str
    message_count: int
    last_message: str
    status: str
    created_at: datetime
    updated_at: datetime


class ConversationListResponse(BaseModel):
    items: list[ConversationSummary]
    total: int
    page: int
    per_page: int


class ConversationMessageOut(BaseModel):
    """One turn of a conversation, including audit/usage fields."""

    role: str
    content: str
    sources: list[dict[str, Any]]
    response_time: float | None
    input_tokens: int
    output_tokens: int
    created_at: datetime


class ConversationDetail(BaseModel):
    """A conversation with its full, chronological message history."""

    id: str
    website_id: str
    visitor_id: str | None
    title: str
    status: str
    created_at: datetime
    updated_at: datetime
    messages: list[ConversationMessageOut]


__all__ = [
    "ConversationDetail",
    "ConversationListResponse",
    "ConversationMessageOut",
    "ConversationSummary",
    "MAX_CONVERSATION_SEARCH_LENGTH",
]
