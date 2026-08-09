"""Chat session document model (Phase 6, docs/05 §9, ADR-005 §5.7).

One `chat_sessions` document per visitor/dashboard conversation. The
`session_id` is the unique key used across `messages` and the future widget
API; `expires_at` backs the 90-day TTL (configurable via
`CHAT_RETENTION_DAYS`). Every document carries `tenant_id`; every repository
query is tenant-scoped (00-AI-Development-Rules.md §7).
"""

from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict

from backend.core.config import get_settings
from backend.core.security import new_id, utcnow

CHAT_SCHEMA_VERSION = 1


class ChatSession(BaseModel):
    """A conversation between a visitor (or dashboard user) and the chatbot."""

    model_config = ConfigDict(extra="allow")

    id: str
    tenant_id: str
    website_id: str
    session_id: str
    visitor_id: str | None = None
    user_id: str | None = None
    started_at: datetime
    last_activity: datetime
    expires_at: datetime
    schema_version: int = CHAT_SCHEMA_VERSION

    @classmethod
    def new(
        cls,
        *,
        tenant_id: str,
        website_id: str,
        session_id: str,
        visitor_id: str | None = None,
        user_id: str | None = None,
    ) -> "ChatSession":
        now = utcnow()
        expires_at = now + timedelta(days=get_settings().chat_retention_days)
        return cls(
            id=new_id(),
            tenant_id=tenant_id,
            website_id=website_id,
            session_id=session_id,
            visitor_id=visitor_id,
            user_id=user_id,
            started_at=now,
            last_activity=now,
            expires_at=expires_at,
        )

    @classmethod
    def from_doc(cls, doc: dict[str, Any]) -> "ChatSession":
        doc = dict(doc)
        doc["id"] = str(doc.pop("_id"))
        return cls(**doc)

    def to_doc(self) -> dict[str, Any]:
        doc = self.model_dump(exclude={"id"})
        doc["_id"] = self.id
        return doc


__all__ = ["CHAT_SCHEMA_VERSION", "ChatSession"]
