"""Pydantic v2 request/response schemas for the crawl API (Phase 4)."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class StartCrawlResponse(BaseModel):
    crawl_job_id: str
    website_id: str
    status: str
    created_at: datetime


class CrawlJobErrorOut(BaseModel):
    url: str
    message: str


class CrawlJobOut(BaseModel):
    id: str
    website_id: str
    status: str
    pages_total: int
    pages_completed: int
    errors: list[CrawlJobErrorOut]
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_job(cls, job: Any) -> "CrawlJobOut":
        return cls(
            id=job.id,
            website_id=job.website_id,
            status=job.status,
            pages_total=job.pages_total,
            pages_completed=job.pages_completed,
            errors=[CrawlJobErrorOut(url=e.url, message=e.message) for e in job.errors],
            started_at=job.started_at,
            completed_at=job.completed_at,
            error_message=job.error_message,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )
