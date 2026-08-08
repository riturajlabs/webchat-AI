"""Crawl job document model (docs/05-Backend-Schema.md §8 + ADR-002).

A crawl job records one ingestion run for a website. The API creates it in
`pending`, the ARQ worker moves it through `running` -> `processing` and lands
on `completed` or `failed`, publishing progress along the way so the dashboard
can render a live progress indicator.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.core.security import new_id, utcnow

CRAWL_STATUS_PENDING = "pending"
CRAWL_STATUS_RUNNING = "running"
CRAWL_STATUS_PROCESSING = "processing"
CRAWL_STATUS_COMPLETED = "completed"
CRAWL_STATUS_FAILED = "failed"

CRAWL_ACTIVE_STATUSES = {
    CRAWL_STATUS_PENDING,
    CRAWL_STATUS_RUNNING,
    CRAWL_STATUS_PROCESSING,
}

CRAWL_STATUSES = CRAWL_ACTIVE_STATUSES | {CRAWL_STATUS_COMPLETED, CRAWL_STATUS_FAILED}


class CrawlJobError(BaseModel):
    """A per-URL failure collected during a crawl run."""

    url: str
    message: str


class CrawlJob(BaseModel):
    """A single ingestion run for a tenant-owned website."""

    model_config = ConfigDict(extra="allow")

    id: str
    tenant_id: str
    website_id: str
    status: str = CRAWL_STATUS_PENDING
    pages_total: int = 0
    pages_completed: int = 0
    errors: list[CrawlJobError] = Field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    schema_version: int = 1

    @classmethod
    def new(cls, *, tenant_id: str, website_id: str) -> "CrawlJob":
        now = utcnow()
        return cls(
            id=new_id(),
            tenant_id=tenant_id,
            website_id=website_id,
            created_at=now,
            updated_at=now,
        )

    @classmethod
    def from_doc(cls, doc: dict[str, Any]) -> "CrawlJob":
        doc = dict(doc)
        doc["id"] = str(doc.pop("_id"))
        return cls(**doc)

    def to_doc(self) -> dict[str, Any]:
        doc = self.model_dump(exclude={"id"})
        doc["_id"] = self.id
        return doc
