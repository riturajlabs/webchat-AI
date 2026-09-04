"""Website document model (docs/05-Backend-Schema.md §5 + ADR-005 §5.1)."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from backend.core.embedding_identity import EmbeddingIdentity
from backend.core.security import new_id, utcnow
from backend.models.knowledge_chunk import KNOWLEDGE_STATUS_NONE


class EmbeddingRun(BaseModel):
    """Immutable embedding-space selection for one fenced ingestion pass."""

    id: str
    state: Literal["running", "completed", "failed"] = "running"
    identity: EmbeddingIdentity
    attempt: int = 0
    started_at: datetime
    updated_at: datetime
    next_retry_at: datetime | None = None


def ingestion_embedding_identity_from_website(
    website: "Website",
) -> EmbeddingIdentity | None:
    """Rebuild an `EmbeddingIdentity` from a website's persisted ingestion lock.

    Returns `None` when the website has not been locked to a provider yet
    (i.e. ingestion has never run, or ran before provider locking existed).
    """
    if not website.ingestion_embedding_provider:
        return None

    return EmbeddingIdentity(
        provider=website.ingestion_embedding_provider,
        model=website.ingestion_embedding_model or "",
        dimensions=int(website.ingestion_embedding_dimensions or 0),
        version=website.ingestion_embedding_version or "1",
    )


# Website statuses (docs/05-Backend-Schema.md §5 + soft delete).
WEBSITE_STATUS_PENDING = "pending"
WEBSITE_STATUS_CRAWLING = "crawling"
WEBSITE_STATUS_PROCESSING = "processing"
WEBSITE_STATUS_READY = "ready"
WEBSITE_STATUS_FAILED = "failed"
# Soft-deleted (Phase 3): the document is kept for audit/recovery but hidden
# from every tenant-facing query (00-AI-Development-Rules: never destroy data).
WEBSITE_STATUS_DELETED = "deleted"

WEBSITE_STATUSES = {
    WEBSITE_STATUS_PENDING,
    WEBSITE_STATUS_CRAWLING,
    WEBSITE_STATUS_PROCESSING,
    WEBSITE_STATUS_READY,
    WEBSITE_STATUS_FAILED,
    WEBSITE_STATUS_DELETED,
}


class Website(BaseModel):
    """A tenant-connected website awaiting/undergoing indexing."""

    model_config = ConfigDict(extra="allow")

    id: str
    tenant_id: str
    name: str
    url: str
    status: str = WEBSITE_STATUS_PENDING
    # Soft-delete index flag: mirrors `status == WEBSITE_STATUS_DELETED` so the
    # (tenant_id, url) unique index can be *partial* (`deleted: false`).
    # MongoDB partial filters only support equality, so a boolean (not `$ne`)
    # drives URL re-registration after a website is deleted (docs/05 §5).
    deleted: bool = False
    pages_indexed: int = 0
    last_crawled_at: datetime | None = None
    checksum: str | None = None
    created_at: datetime
    updated_at: datetime
    schema_version: int = 1
    # Phase 5 knowledge base statistics (dashboard "knowledge status").
    knowledge_status: str = KNOWLEDGE_STATUS_NONE
    knowledge_documents: int = 0
    knowledge_chunks: int = 0
    last_knowledge_at: datetime | None = None
    # Open Graph / Twitter preview image (absolute URL) surfaced on the
    # dashboard website card. Populated from the homepage's meta tags during a
    # crawl; purely a metadata URL, never a fetched/byte payload.
    preview_image: str | None = None

    # Per-website ingestion embedding lock (provider consistency). Persisted
    # when a website's knowledge fan-out first runs: the provider/model/
    # dimensions/version chosen for THIS website's ingestion. Every document
    # and every retry of that ingestion must resolve to exactly this identity;
    # a website is never silently re-locked to a different provider. Null when
    # ingestion has never run (or ran before locking existed).
    ingestion_embedding_provider: str | None = None
    ingestion_embedding_model: str | None = None
    ingestion_embedding_dimensions: int | None = None
    ingestion_embedding_version: str | None = None
    # A crawl may enqueue duplicate/out-of-order jobs.  Jobs carry this id and
    # must match it before they are allowed to write vectors.
    embedding_run: EmbeddingRun | None = None

    @property
    def embedding_identity(self) -> EmbeddingIdentity | None:
        """The locked ingestion `EmbeddingIdentity`, or `None` if unlocked."""
        return ingestion_embedding_identity_from_website(self)

    @classmethod
    def new(cls, *, tenant_id: str, name: str, url: str) -> "Website":
        now = utcnow()
        return cls(
            id=new_id(),
            tenant_id=tenant_id,
            name=name,
            url=url,
            created_at=now,
            updated_at=now,
        )

    @classmethod
    def from_doc(cls, doc: dict[str, Any]) -> "Website":
        doc = dict(doc)
        doc["id"] = str(doc.pop("_id"))
        return cls(**doc)

    def to_doc(self) -> dict[str, Any]:
        doc = self.model_dump(exclude={"id"})
        doc["_id"] = self.id
        return doc
