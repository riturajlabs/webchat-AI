"""Chat message document model (Phase 6, docs/05 §10, ADR-005 §5.8).

One `messages` document per turn of a conversation. Assistant messages carry
the retrieved `sources`, the generation latency (`response_time`), and the raw
Gemini token usage (`input_tokens`/`output_tokens`) for audit; daily rollups
live in `usage_records` (ADR-005 §5.5). Every document carries `tenant_id`;
every repository query is tenant-scoped (00-AI-Development-Rules.md §7).
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.core.security import new_id, utcnow

CHAT_SCHEMA_VERSION = 1

CHAT_ROLE_USER = "user"
CHAT_ROLE_ASSISTANT = "assistant"
CHAT_ROLE_SYSTEM = "system"

CHAT_ROLES = {CHAT_ROLE_USER, CHAT_ROLE_ASSISTANT, CHAT_ROLE_SYSTEM}


class ChatMessage(BaseModel):
    """A single turn in a conversation (docs/05 §10)."""

    model_config = ConfigDict(extra="allow")

    id: str
    tenant_id: str
    website_id: str
    session_id: str
    role: str
    content: str
    sources: list[dict[str, Any]] = Field(default_factory=list)
    response_time: float | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    # Per-stage latency breakdown (milliseconds, Phase 12.6). Assistant
    # messages record where the response time went so the performance dashboard
    # can report average embedding/retrieval/generation latency per window.
    latency_embedding_ms: float | None = None
    latency_retrieval_ms: float | None = None
    latency_context_ms: float | None = None
    latency_history_ms: float | None = None
    latency_generation_ms: float | None = None
    latency_ttft_ms: float | None = None
    latency_total_ms: float | None = None
    created_at: datetime
    schema_version: int = CHAT_SCHEMA_VERSION

    @classmethod
    def new(
        cls,
        *,
        tenant_id: str,
        website_id: str,
        session_id: str,
        role: str,
        content: str,
    ) -> "ChatMessage":
        return cls(
            id=new_id(),
            tenant_id=tenant_id,
            website_id=website_id,
            session_id=session_id,
            role=role,
            content=content,
            created_at=utcnow(),
        )

    @classmethod
    def from_doc(cls, doc: dict[str, Any]) -> "ChatMessage":
        doc = dict(doc)
        doc["id"] = str(doc.pop("_id"))
        return cls(**doc)

    def to_doc(self) -> dict[str, Any]:
        doc = self.model_dump(exclude={"id"})
        doc["_id"] = self.id
        return doc


__all__ = [
    "CHAT_ROLE_ASSISTANT",
    "CHAT_ROLE_SYSTEM",
    "CHAT_ROLE_USER",
    "CHAT_ROLES",
    "CHAT_SCHEMA_VERSION",
    "ChatMessage",
]
