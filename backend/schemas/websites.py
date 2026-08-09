"""Pydantic v2 request/response schemas for the websites API."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

# Uploaded field limits (00-AI-Development-Rules: validate all requests).
MAX_WEBSITE_NAME_LENGTH = 100
MIN_WEBSITE_NAME_LENGTH = 2
MAX_SUGGESTED_QUESTIONS = 5


class CreateWebsiteRequest(BaseModel):
    name: str = Field(min_length=MIN_WEBSITE_NAME_LENGTH, max_length=MAX_WEBSITE_NAME_LENGTH)
    url: str = Field(min_length=4, max_length=2048)


class UpdateWebsiteRequest(BaseModel):
    name: str | None = Field(
        default=None, min_length=MIN_WEBSITE_NAME_LENGTH, max_length=MAX_WEBSITE_NAME_LENGTH
    )
    url: str | None = Field(default=None, min_length=4, max_length=2048)


class WebsiteOut(BaseModel):
    id: str
    tenant_id: str
    name: str
    url: str
    status: str
    pages_indexed: int
    last_crawled_at: datetime | None
    checksum: str | None
    created_at: datetime
    updated_at: datetime
    widget_id: str
    # Phase 5 knowledge base statistics (dashboard "knowledge status").
    knowledge_status: str
    knowledge_documents: int
    knowledge_chunks: int
    last_knowledge_at: datetime | None

    @classmethod
    def from_website(cls, website: Any, *, widget_id: str) -> "WebsiteOut":
        return cls(
            id=website.id,
            tenant_id=website.tenant_id,
            name=website.name,
            url=website.url,
            status=website.status,
            pages_indexed=website.pages_indexed,
            last_crawled_at=website.last_crawled_at,
            checksum=website.checksum,
            created_at=website.created_at,
            updated_at=website.updated_at,
            widget_id=widget_id,
            knowledge_status=website.knowledge_status,
            knowledge_documents=website.knowledge_documents,
            knowledge_chunks=website.knowledge_chunks,
            last_knowledge_at=website.last_knowledge_at,
        )


class WidgetOut(BaseModel):
    widget_id: str
    website_id: str
    theme: str
    position: str
    primary_color: str
    accent_color: str
    font_size: str
    logo_url: str | None
    avatar_url: str | None
    welcome_message: str
    placeholder: str
    suggested_questions: list[str]
    branding: bool
    dark_mode: bool
    auto_open: bool
    enabled: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_widget(cls, widget: Any) -> "WidgetOut":
        return cls(
            widget_id=widget.widget_id,
            website_id=widget.website_id,
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
            enabled=widget.enabled,
            created_at=widget.created_at,
            updated_at=widget.updated_at,
        )


class WidgetResponse(BaseModel):
    widget: WidgetOut
    embed_script: str


class CreateWebsiteResponse(BaseModel):
    website: WebsiteOut
    widget: WidgetOut
    # Shown exactly once; only a hash is persisted (ADR-004).
    widget_secret: str
    embed_script: str
