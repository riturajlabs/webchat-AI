"""Knowledge chunk document model (Phase 5, docs/05-Backend-Schema.md §7).

One `knowledge_chunks` document per semantic chunk of a crawled page: the clean
text, its dense embedding (gemini-embedding-001), and the metadata needed by
Phase 6 retrieval (source URL, page title, heading). Every document carries
`tenant_id`; every repository query is tenant-scoped
(00-AI-Development-Rules.md §7).
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.core.security import new_id, utcnow

KNOWLEDGE_SCHEMA_VERSION = 1

# Knowledge-base status of a document or website (dashboard "embedding status").
KNOWLEDGE_STATUS_NONE = "none"
# Crawled but not yet handed to the embedding pipeline (queued/fan-out pending).
# `none` is kept for backward compatibility with pre-status documents; both
# normalize to "pending" for the dashboard.
KNOWLEDGE_STATUS_PENDING = "pending"
KNOWLEDGE_STATUS_PROCESSING = "processing"
KNOWLEDGE_STATUS_READY = "ready"
KNOWLEDGE_STATUS_FAILED = "failed"
# Embedding failed for quota/rate-limit reasons and a deferred automatic retry
# is pending (Part E/ING-02). Unlike `failed`, this is non-terminal: the doc may
# still succeed on retry, so the dashboard renders it separately.
KNOWLEDGE_STATUS_RATE_LIMITED = "rate_limited"

KNOWLEDGE_STATUSES = {
    KNOWLEDGE_STATUS_NONE,
    KNOWLEDGE_STATUS_PENDING,
    KNOWLEDGE_STATUS_PROCESSING,
    KNOWLEDGE_STATUS_READY,
    KNOWLEDGE_STATUS_FAILED,
    KNOWLEDGE_STATUS_RATE_LIMITED,
}


class KnowledgeChunk(BaseModel):
    """A single embedded chunk of a document's cleaned text."""

    model_config = ConfigDict(extra="allow")

    id: str
    tenant_id: str
    website_id: str
    document_id: str
    chunk_text: str
    embedding: list[float] = Field(default_factory=list)
    embedding_provider: str | None = None
    embedding_model: str | None = None
    embedding_dimensions: int | None = None
    embedding_version: str | None = None
    chunk_index: int
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    schema_version: int = KNOWLEDGE_SCHEMA_VERSION

    @classmethod
    def new(
        cls,
        *,
        tenant_id: str,
        website_id: str,
        document_id: str,
        chunk_text: str,
        embedding: list[float],
        chunk_index: int,
        metadata: dict[str, Any] | None = None,
        embedding_provider: str | None = None,
        embedding_model: str | None = None,
        embedding_dimensions: int | None = None,
        embedding_version: str | None = None,
    ) -> "KnowledgeChunk":
        return cls(
            id=new_id(),
            tenant_id=tenant_id,
            website_id=website_id,
            document_id=document_id,
            chunk_text=chunk_text,
            embedding=embedding,
            embedding_provider=embedding_provider,
            embedding_model=embedding_model,
            embedding_dimensions=embedding_dimensions,
            embedding_version=embedding_version,
            chunk_index=chunk_index,
            metadata=metadata or {},
            created_at=utcnow(),
        )

    @classmethod
    def from_doc(cls, doc: dict[str, Any]) -> "KnowledgeChunk":
        doc = dict(doc)
        doc["id"] = str(doc.pop("_id"))
        return cls(**doc)

    def to_doc(self) -> dict[str, Any]:
        doc = self.model_dump(exclude={"id"})
        doc["_id"] = self.id
        return doc

    def to_out(self) -> dict[str, Any]:
        """Dashboard-facing shape: never includes the embedding vector."""
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "website_id": self.website_id,
            "document_id": self.document_id,
            "chunk_index": self.chunk_index,
            "chunk_text": self.chunk_text,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }


__all__ = [
    "KNOWLEDGE_SCHEMA_VERSION",
    "KNOWLEDGE_STATUSES",
    "KNOWLEDGE_STATUS_FAILED",
    "KNOWLEDGE_STATUS_NONE",
    "KNOWLEDGE_STATUS_PENDING",
    "KNOWLEDGE_STATUS_PROCESSING",
    "KNOWLEDGE_STATUS_RATE_LIMITED",
    "KNOWLEDGE_STATUS_READY",
    "KnowledgeChunk",
]
