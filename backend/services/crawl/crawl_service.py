"""Crawl orchestration business logic (Phase 4, ADR-002).

`start_crawl` validates the tenant-owned website, rejects overlapping crawls,
creates a `pending` crawl job, and enqueues the ARQ `crawl_website` task. The
worker owns the heavy lifting (browser, extraction, storage); this service
only gates and records the run.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from backend.core.config import Settings, get_settings
from backend.core.errors import (
    CrawlConflictError,
    CrawlJobNotFoundError,
    WebsiteNotFoundError,
)
from backend.core.security import utcnow
from backend.models.audit_log import AUDIT_CRAWL_STARTED, AuditLog
from backend.models.crawl_job import CrawlJob
from backend.models.website import WEBSITE_STATUS_CRAWLING
from backend.repositories import (
    AuditLogRepository,
    CrawlJobRepository,
    WebsiteRepository,
)
from backend.services.auth import Principal
from backend.services.billing import UsageService

EnqueueFn = Callable[[str], Awaitable[None]]


@dataclass(frozen=True)
class StartCrawlResult:
    """Response for a successful crawl kick-off."""

    job: CrawlJob


class CrawlService:
    """Encapsulates every crawl-job workflow (tenant-scoped)."""

    def __init__(
        self,
        *,
        crawl_jobs: CrawlJobRepository,
        websites: WebsiteRepository,
        audit: AuditLogRepository,
        enqueue: EnqueueFn,
        settings: Settings | None = None,
        usage: UsageService | None = None,
    ) -> None:
        self._crawl_jobs = crawl_jobs
        self._websites = websites
        self._audit = audit
        self._enqueue = enqueue
        self._settings = settings or get_settings()
        # Phase 13 billing: raises `LimitReachedError` before queueing when the
        # tenant already sits at `max_documents` or has exhausted its monthly
        # `max_crawl_pages`. Optional for callers/tests without usage gating.
        self._usage = usage

    async def start_crawl(
        self,
        *,
        principal: Principal,
        website_id: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> CrawlJob:
        """Queue a crawl run for a tenant-owned website.

        Raises `WebsiteNotFoundError` when the website does not exist and
        `CrawlConflictError` when a crawl is already running for it.
        """
        website = await self._websites.find_by_id(principal.tenant_id, website_id)
        if website is None:
            raise WebsiteNotFoundError("Website not found.")
        # Fast-path only: `find_active_for_website` is a cheap first-409, NOT the
        # correctness mechanism (FIND-02). The authoritative single-flight gate is
        # the atomic unique insert in `create`; two racing requests can both pass
        # this read, but only one `crawl_jobs` row (and thus one crawl) is ever
        # created. A manual re-crawl after a completed job passes through without
        # blocking (job is terminal -> `active=False`).
        active = await self._crawl_jobs.find_active_for_website(principal.tenant_id, website_id)
        if active is not None:
            raise CrawlConflictError("A crawl is already in progress for this website.")
        if self._usage is not None:
            # Phase 13 billing: reject before the job is created/queued.
            await self._usage.check_limit(principal.tenant_id, event_type="documents")
            await self._usage.check_limit(principal.tenant_id, event_type="crawl_pages")

        # Authoritative single-flight gate: `MongoCrawlJobRepository.create`
        # translates the unique partial-index violation into CrawlConflictError;
        # a genuine database fault still propagates as such.
        job = CrawlJob.new(tenant_id=principal.tenant_id, website_id=website_id)
        await self._crawl_jobs.create(job)
        await self._audit.create(
            AuditLog.new(
                action=AUDIT_CRAWL_STARTED,
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )
        await self._enqueue(job.id)

        # Record crawl ownership on the website: the worker fences its terminal
        # READY/FAILED write on this exact `crawl_job_id` (FIND-02).
        website.crawl_job_id = job.id
        website.status = WEBSITE_STATUS_CRAWLING
        website.updated_at = utcnow()
        await self._websites.update(website)
        return job

    async def get_crawl_job(self, tenant_id: str, job_id: str) -> CrawlJob:
        """Return a crawl job owned by the tenant, if it exists."""
        job = await self._crawl_jobs.find_by_id(tenant_id, job_id)
        if job is None:
            raise CrawlJobNotFoundError("Crawl job not found.")
        return job


__all__ = ["CrawlService", "StartCrawlResult"]
