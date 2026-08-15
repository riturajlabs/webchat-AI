"""Usage event document model (Phase 13, SaaS billing foundation).

The `usage_events` collection stores one append-only document per tracked
action so billing can sum quantities per tenant over a window (monthly
limits) without re-aggregating live state. The five event types map to the
plan limits:

    messages_sent       every accepted chat question (dashboard + widget)
    ai_responses        every assistant answer emitted (incl. fallback)
    tokens_used         input + output tokens for a generated answer
    documents_created   knowledge documents added by the ingestion pipeline
    crawl_pages         pages crawled by the ingestion pipeline

Events are write-only by the services; `usage_events` never replaces the
authoritative counts (websites, documents), which stay live repository
counts. `tenant_id` is always set for tenant isolation; `user_id` is the
acting user (None for anonymous widget visitors / system actions) and
`website_id` is optional (None for tenant-wide actions).
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from backend.core.security import new_id, utcnow

USAGE_EVENT_MESSAGES_SENT = "messages_sent"
USAGE_EVENT_AI_RESPONSES = "ai_responses"
USAGE_EVENT_TOKENS_USED = "tokens_used"
USAGE_EVENT_DOCUMENTS_CREATED = "documents_created"
USAGE_EVENT_CRAWL_PAGES = "crawl_pages"

USAGE_EVENT_TYPES = frozenset(
    {
        USAGE_EVENT_MESSAGES_SENT,
        USAGE_EVENT_AI_RESPONSES,
        USAGE_EVENT_TOKENS_USED,
        USAGE_EVENT_DOCUMENTS_CREATED,
        USAGE_EVENT_CRAWL_PAGES,
    }
)

USAGE_EVENT_SCHEMA_VERSION = 1


class UsageEvent(BaseModel):
    """One atomic usage counter increment for a tenant (append-only)."""

    model_config = ConfigDict(extra="allow")

    id: str
    tenant_id: str
    user_id: str | None
    website_id: str | None
    event_type: str
    quantity: int
    created_at: datetime
    schema_version: int = USAGE_EVENT_SCHEMA_VERSION

    @classmethod
    def new(
        cls,
        *,
        tenant_id: str,
        user_id: str | None,
        website_id: str | None,
        event_type: str,
        quantity: int,
    ) -> "UsageEvent":
        return cls(
            id=new_id(),
            tenant_id=tenant_id,
            user_id=user_id,
            website_id=website_id,
            event_type=event_type,
            quantity=quantity,
            created_at=utcnow(),
        )

    @classmethod
    def from_doc(cls, doc: dict[str, Any]) -> "UsageEvent":
        doc = dict(doc)
        doc["id"] = str(doc.pop("_id"))
        return cls(**doc)

    def to_doc(self) -> dict[str, Any]:
        doc = self.model_dump(exclude={"id"})
        doc["_id"] = self.id
        return doc


__all__ = [
    "USAGE_EVENT_AI_RESPONSES",
    "USAGE_EVENT_CRAWL_PAGES",
    "USAGE_EVENT_DOCUMENTS_CREATED",
    "USAGE_EVENT_MESSAGES_SENT",
    "USAGE_EVENT_TOKENS_USED",
    "USAGE_EVENT_TYPES",
    "USAGE_EVENT_SCHEMA_VERSION",
    "UsageEvent",
]
