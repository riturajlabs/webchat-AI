"""Widget document model (docs/05-Backend-Schema.md §6 + ADR-005 §5.3)."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.core.security import new_id, utcnow

# Widget themes and positions (ADR-005 §5.3).
WIDGET_THEMES = {"light", "dark", "auto"}
WIDGET_POSITIONS = {"bottom-left", "bottom-right"}
WIDGET_FONT_SIZES = {"sm", "md", "lg"}


class Widget(BaseModel):
    """Per-website embeddable widget configuration.

    Widget authentication is covered exclusively by the short-lived, per-widget
    session JWTs issued by the public widget API (Phase 8) - there is no
    long-lived widget secret (Sprint 2 removed the reserved field).
    """

    model_config = ConfigDict(extra="allow")

    id: str
    tenant_id: str
    website_id: str
    widget_id: str
    theme: str = "light"
    position: str = "bottom-right"
    primary_color: str = "#2563eb"
    accent_color: str = "#4f46e5"
    font_size: str = "md"
    logo_url: str | None = None
    avatar_url: str | None = None
    welcome_message: str = "Hi! How can I help you?"
    placeholder: str = "Type your question..."
    suggested_questions: list[str] = []
    branding: bool = True
    dark_mode: bool = False
    auto_open: bool = False
    enabled: bool = True
    # Embed-origin allowlist (production hardening). Normalized bare hostnames
    # (optionally `*.`-wildcards); the literal `*` opts into open embedding.
    # An empty list blocks browser embeds (WIDGET_DOMAIN_NOT_CONFIGURED) until
    # domains are configured - it never means "any origin". Seeded from the
    # website host at creation and editable via the dashboard widget builder.
    allowed_domains: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    schema_version: int = 1

    @classmethod
    def new(
        cls,
        *,
        tenant_id: str,
        website_id: str,
    ) -> "Widget":
        now = utcnow()
        return cls(
            id=new_id(),
            tenant_id=tenant_id,
            website_id=website_id,
            widget_id=new_id(),
            created_at=now,
            updated_at=now,
        )

    @classmethod
    def from_doc(cls, doc: dict[str, Any]) -> "Widget":
        doc = dict(doc)
        doc["id"] = str(doc.pop("_id"))
        return cls(**doc)

    def to_doc(self) -> dict[str, Any]:
        doc = self.model_dump(exclude={"id"})
        doc["_id"] = self.id
        return doc
