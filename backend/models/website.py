"""Website document model (docs/05-Backend-Schema.md §5 + ADR-005 §5.1)."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from backend.core.security import new_id, utcnow

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
    pages_indexed: int = 0
    last_crawled_at: datetime | None = None
    checksum: str | None = None
    created_at: datetime
    updated_at: datetime
    schema_version: int = 1

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
