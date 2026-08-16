"""Pydantic v2 schemas for the widget API (Phase 8 + Phase 11.5).

The public config intentionally mirrors the dashboard `WidgetOut` *minus*
`website_id` and timestamps (no internal identifiers leak to anonymous
visitors) and is derived only from fields the embed needs. `WidgetConfigUpdate`
is the dashboard-side customization surface (Phase 11.5 widget builder) and is
strictly additive: it never touches the public API contract.
"""

import re
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator

from backend.models.widget import (
    WIDGET_FONT_SIZES,
    WIDGET_POSITIONS,
    WIDGET_THEME_PRESETS,
    WIDGET_THEMES,
)
from backend.utils.origin import normalize_allowed_domains

MAX_WIDGET_ID_LENGTH = 128
MAX_VISITOR_ID_LENGTH = 128
MAX_QUESTION_LENGTH = 2000
MAX_SESSION_ID_LENGTH = 128

# Phase 11.5 widget builder field limits (dashboard customization API).
MAX_WELCOME_MESSAGE_LENGTH = 500
MAX_PLACEHOLDER_LENGTH = 120
MAX_SUGGESTED_QUESTIONS = 5
MAX_SUGGESTED_QUESTION_LENGTH = 200
MAX_WIDGET_URL_LENGTH = 2048
# Phase 11.6 branding presentation limits.
MAX_BOT_NAME_LENGTH = 60
MAX_BOT_STATUS_LENGTH = 40
MAX_FONT_FAMILY_LENGTH = 100
MAX_SIZE_LENGTH = 20
# Embed-origin allowlist bounds (production hardening).
MAX_ALLOWED_DOMAINS = 50
MAX_ALLOWED_DOMAIN_LENGTH = 253

_HTML_HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
# CSS length for window/launcher sizing (safe subset: the widget passes the
# string straight through to CSS custom properties).
_CSS_LENGTH = re.compile(r"^\d+(?:\.\d+)?(?:px|em|rem|vh|vw|%)$")

WIDGET_THEMES_ALLOWED = WIDGET_THEMES
WIDGET_POSITIONS_ALLOWED = WIDGET_POSITIONS
WIDGET_FONT_SIZES_ALLOWED = WIDGET_FONT_SIZES

WidgetTheme = Literal["light", "dark", "auto"]
WidgetPosition = Literal["bottom-right", "bottom-left"]
WidgetFontSize = Literal["sm", "md", "lg"]


class WidgetConfigUpdate(BaseModel):
    """Dashboard-side widget customization payload (Phase 11.5).

    Every field is optional (PATCH semantics): only the fields the tenant
    actually sends are applied to the `widgets` document. Explicit `null` for
    `logo_url`/`avatar_url` clears the image; empty strings are normalized to
    `None` by the validators below.
    """

    theme: WidgetTheme | None = None
    position: WidgetPosition | None = None
    primary_color: str | None = None
    accent_color: str | None = None
    font_size: WidgetFontSize | None = None
    # Curated theme preset ("" = classic fully-custom setup).
    theme_preset: str | None = Field(default=None, max_length=32)
    logo_url: str | None = Field(default=None, max_length=MAX_WIDGET_URL_LENGTH)
    avatar_url: str | None = Field(default=None, max_length=MAX_WIDGET_URL_LENGTH)
    welcome_message: str | None = Field(default=None, max_length=MAX_WELCOME_MESSAGE_LENGTH)
    placeholder: str | None = Field(default=None, max_length=MAX_PLACEHOLDER_LENGTH)
    suggested_questions: list[str] | None = None
    branding: bool | None = None
    dark_mode: bool | None = None
    auto_open: bool | None = None
    # Branding presentation (Phase 11.6). Nulls leave the widget defaults.
    bot_name: str | None = Field(default=None, max_length=MAX_BOT_NAME_LENGTH)
    bot_status_text: str | None = Field(default=None, max_length=MAX_BOT_STATUS_LENGTH)
    header_color: str | None = None
    secondary_color: str | None = None
    background_color: str | None = None
    text_color: str | None = None
    font_family: str | None = Field(default=None, max_length=MAX_FONT_FAMILY_LENGTH)
    width: str | None = Field(default=None, max_length=MAX_SIZE_LENGTH)
    height: str | None = Field(default=None, max_length=MAX_SIZE_LENGTH)
    border_radius: str | None = Field(default=None, max_length=MAX_SIZE_LENGTH)
    launcher_size: str | None = Field(default=None, max_length=MAX_SIZE_LENGTH)
    enabled: bool | None = None
    # Embed-origin allowlist. Entries are normalized bare hostnames (optionally
    # `*.`-wildcards); the literal `*` opts into open embedding. An empty list
    # blocks browser embeds with WIDGET_DOMAIN_NOT_CONFIGURED until domains are
    # configured - it never means "any origin".
    allowed_domains: list[str] | None = None

    @field_validator(
        "primary_color",
        "accent_color",
        "header_color",
        "secondary_color",
        "background_color",
        "text_color",
    )
    @classmethod
    def _validate_color(cls, value: str | None) -> str | None:
        if value is None:
            return value
        cleaned = value.strip()
        if not cleaned:
            # An empty string means "clear the override" (revert to default).
            return None
        if not _HTML_HEX_COLOR.match(cleaned):
            raise ValueError("colors must be a hex value like #2563eb")
        return cleaned

    @field_validator("welcome_message", "placeholder", "bot_status_text")
    @classmethod
    def _strip_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("bot_name")
    @classmethod
    def _validate_bot_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("bot name must not be blank")
        return cleaned

    @field_validator("font_family")
    @classmethod
    def _strip_font_family(cls, value: str | None) -> str | None:
        if value is None:
            return value
        cleaned = value.strip()
        if not cleaned:
            return None
        return cleaned

    @field_validator("theme_preset")
    @classmethod
    def _validate_theme_preset(cls, value: str | None) -> str | None:
        if value is None:
            return value
        cleaned = value.strip()
        if not cleaned:
            # An empty string means "clear the preset" (back to classic).
            return ""
        if cleaned not in WIDGET_THEME_PRESETS:
            raise ValueError("unknown theme preset")
        return cleaned

    @field_validator("width", "height", "border_radius", "launcher_size")
    @classmethod
    def _validate_css_length(cls, value: str | None) -> str | None:
        if value is None:
            return value
        cleaned = value.strip()
        if not cleaned:
            return None
        if not _CSS_LENGTH.match(cleaned):
            raise ValueError("size must be a CSS length like 420px, 90%, 0.5rem or 24px")
        return cleaned

    @field_validator("logo_url", "avatar_url")
    @classmethod
    def _validate_image_url(cls, value: str | None) -> str | None:
        if value is None:
            return value
        cleaned = value.strip()
        if not cleaned:
            # An empty string means "clear the image".
            return None
        if len(cleaned) > MAX_WIDGET_URL_LENGTH:
            raise ValueError("the URL is too long")
        parsed = urlparse(cleaned)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("must be a valid http(s) URL")
        return cleaned

    @field_validator("suggested_questions")
    @classmethod
    def _validate_suggested_questions(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        if len(value) > MAX_SUGGESTED_QUESTIONS:
            raise ValueError(f"no more than {MAX_SUGGESTED_QUESTIONS} questions are allowed")
        cleaned: list[str] = []
        for question in value:
            stripped = " ".join(question.split())
            if not stripped:
                raise ValueError("suggested questions must not be blank")
            if len(stripped) > MAX_SUGGESTED_QUESTION_LENGTH:
                raise ValueError("a suggested question is too long")
            cleaned.append(stripped)
        return cleaned

    @field_validator("allowed_domains")
    @classmethod
    def _validate_allowed_domains(cls, value: list[str] | None) -> list[str] | None:
        """Validate + normalize the embed-origin allowlist.

        Entries are bare hostnames or `*.`-prefixed wildcards; schemes, ports
        and paths are rejected (embedding is matched on the hostname only).
        A bare single-label hostname is only accepted for the loopback host
        (`localhost`), so typos like `example` fail loudly. The dashboard
        normalizes full URLs (e.g. `https://example.com` → `example.com`)
        before sending.
        """
        if value is None:
            return None
        if len(value) > MAX_ALLOWED_DOMAINS:
            raise ValueError(f"no more than {MAX_ALLOWED_DOMAINS} domains are allowed")
        cleaned = normalize_allowed_domains(value)
        if len(cleaned) != len(value):
            raise ValueError(
                "allowed domains must be bare hostnames (optionally *.wildcards)"
            )
        return cleaned

    @model_validator(mode="after")
    def _at_least_one_field(self) -> "WidgetConfigUpdate":
        if not self.model_fields_set:
            raise ValueError("at least one widget setting is required")
        return self


class WidgetPublicConfig(BaseModel):
    """Theme/branding/config the embed needs to render itself.

    Never includes `tenant_id` or `website_id`. Widget requests authenticate
    via the short-lived session JWTs issued by `POST /api/widget/v1/sessions` -
    there is no long-lived widget secret.
    """

    widget_id: str
    enabled: bool
    theme: str
    position: str
    primary_color: str
    accent_color: str
    font_size: str
    theme_preset: str = ""
    logo_url: str | None = None
    avatar_url: str | None = None
    welcome_message: str
    placeholder: str
    suggested_questions: list[str]
    branding: bool
    dark_mode: bool
    auto_open: bool
    # Phase 11.6 branding presentation (nullable fields revert to defaults).
    bot_name: str = "WebChat AI"
    bot_status_text: str = "Online"
    header_color: str | None = None
    secondary_color: str | None = None
    background_color: str | None = None
    text_color: str | None = None
    font_family: str | None = None
    width: str = "380px"
    height: str = "600px"
    border_radius: str = "20px"
    launcher_size: str = "58px"

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
            theme_preset=widget.theme_preset,
            logo_url=widget.logo_url,
            avatar_url=widget.avatar_url,
            welcome_message=widget.welcome_message,
            placeholder=widget.placeholder,
            suggested_questions=widget.suggested_questions,
            branding=widget.branding,
            dark_mode=widget.dark_mode,
            auto_open=widget.auto_open,
            bot_name=widget.bot_name,
            bot_status_text=widget.bot_status_text,
            header_color=widget.header_color,
            secondary_color=widget.secondary_color,
            background_color=widget.background_color,
            text_color=widget.text_color,
            font_family=widget.font_family,
            width=widget.width,
            height=widget.height,
            border_radius=widget.border_radius,
            launcher_size=widget.launcher_size,
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
    "WidgetConfigUpdate",
    "WidgetPublicConfig",
    "WidgetSessionResponse",
]
