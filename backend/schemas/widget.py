"""Pydantic v2 schemas for the public widget API (Phase 8, ADR-004).

The public config intentionally mirrors the dashboard `WidgetOut` *minus*
`website_id` and timestamps (no internal identifiers leak to anonymous
visitors) and is derived only from fields the embed needs.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from backend.models.widget import (
    WIDGET_FONT_SIZES,
    WIDGET_POSITIONS,
    WIDGET_THEMES,
)

MAX_WIDGET_ID_LENGTH = 128
MAX_VISITOR_ID_LENGTH = 128
MAX_QUESTION_LENGTH = 2000
MAX_SESSION_ID_LENGTH = 128

WIDGET_THEMES_ALLOWED = WIDGET_THEMES
WIDGET_POSITIONS_ALLOWED = WIDGET_POSITIONS
WIDGET_FONT_SIZES_ALLOWED = WIDGET_FONT_SIZES


class WidgetPublicConfig(BaseModel):
    """Theme/branding/config the embed needs to render itself.

    Never includes `widget_secret_hash`, the raw secret (which is never
    persisted anyway), `tenant_id`, or `website_id`.
    """

    widget_id: str
    enabled: bool
    theme: str
    position: str
    primary_color: str
    accent_color: str
    font_size: str
    logo_url: str | None = None
    avatar_url: str | None = None
    welcome_message: str
    placeholder: str
    suggested_questions: list[str]
    branding: bool
    dark_mode: bool
    auto_open: bool

    @classmethod
    def from_widget(cls, widget: Any) -> "WidgetPublicConfig":
        return cls(
            widget_id=widget.widget_id,
            enabled=widget.enabled,
            theme=widget.theme,
            position=widget.position,
            primary_color=widget.primary_color,
            accent_color=widget.accent_color,
            font_size=widget.font_size,
            logo_url=widget.logo_url,
            avatar_url=widget.avatar_url,
            welcome_message=widget.welcome_message,
            placeholder=widget.placeholder,
            suggested_questions=widget.suggested_questions,
            branding=widget.branding,
            dark_mode=widget.dark_mode,
            auto_open=widget.auto_open,
        )


class CreateWidgetSessionRequest(BaseModel):
    """Body of the public session-minting endpoint.

    `visitor_id` is the anonymous id from the `wc_visitor` cookie - never PII
    (ADR-004). A malicious client may omit or spoof it; the API treats it as a
    best-effort identity for per-visitor rate limits and 24-hour session
    continuity, not as authentication.
    """

    widget_id: str = Field(min_length=1, max_length=MAX_WIDGET_ID_LENGTH)
    visitor_id: str | None = Field(default=None, min_length=1, max_length=MAX_VISITOR_ID_LENGTH)


class WidgetSessionResponse(BaseModel):
    session_token: str
    expires_at: datetime


class WidgetChatRequest(BaseModel):
    """Body of the public streaming chat endpoint.

    `session_id` is the *conversation* id returned in the `done` SSE event
    (persisted in `chat_sessions`, 90-day TTL) - distinct from the widget
    session token that authorizes the request (plan §3.2.1).
    """

    question: str = Field(min_length=1, max_length=MAX_QUESTION_LENGTH)
    session_id: str | None = Field(default=None, min_length=1, max_length=MAX_SESSION_ID_LENGTH)

    @field_validator("question")
    @classmethod
    def _normalize_question(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("question must not be blank")
        return cleaned


__all__ = [
    "CreateWidgetSessionRequest",
    "MAX_VISITOR_ID_LENGTH",
    "MAX_WIDGET_ID_LENGTH",
    "WidgetChatRequest",
    "WidgetPublicConfig",
    "WidgetSessionResponse",
]
