"""ARQ crawl job (Phase 4, ADR-002): ingest a tenant website into `documents`.

`enqueue_crawl_website` is the fast async enqueue path used by `CrawlService`
so API requests never block on worker plumbing; `crawl_website` is the
registered worker task. The worker runs one headless-Chromium crawl per job,
publishes progress to the `crawl_jobs` document, and lands the website on
`ready`/`failed`. Transient failures re-raise so ARQ retries (max_tries=3);
only the final attempt records a permanent `failed` state.
"""

import hashlib
import logging
from typing import Any

from arq.connections import ArqRedis
from redis.asyncio import ConnectionPool

from backend.core.config import get_settings
from backend.core.database import MongoDB
from backend.core.errors import InvalidUrlError
from backend.core.security import utcnow
from backend.models.audit_log import AUDIT_CRAWL_COMPLETED, AUDIT_CRAWL_FAILED, AuditLog
from backend.models.crawl_job import (
    CRAWL_ACTIVE_STATUSES,
    CRAWL_STATUS_COMPLETED,
    CRAWL_STATUS_FAILED,
    CRAWL_STATUS_PROCESSING,
    CRAWL_STATUS_RUNNING,
)
from backend.models.website import WEBSITE_STATUS_FAILED, WEBSITE_STATUS_READY
from backend.repositories import (
    MongoAuditLogRepository,
    MongoCrawlJobRepository,
    MongoDocumentRepository,
    MongoWebsiteRepository,
)
from backend.services.ingestion import BrowserPageFetcher, CrawlSession, SsrFGuard
from backend.services.ingestion.browser import crawl_semaphore

logger = logging.getLogger("webchat_ai")

_pool: ConnectionPool | None = None


def _arq_redis() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = ConnectionPool.from_url(get_settings().redis_url, decode_responses=True)
    return ArqRedis(connection_pool=_pool)


async def enqueue_crawl_website(crawl_job_id: str) -> None:
    """Enqueue a crawl job for the ARQ worker (ADR-002 task registry)."""
    await _arq_redis().enqueue_job("crawl_website", crawl_job_id)


async def crawl_website(ctx: dict[str, Any], crawl_job_id: str) -> dict[str, Any]:
    """Worker task: run one crawl job and record the outcome on the website."""
    db = MongoDB.db()
    return await _run_crawl_job(
        ctx,
        crawl_job_id,
        crawl_jobs=MongoCrawlJobRepository(db),
        documents=MongoDocumentRepository(db),
        websites=MongoWebsiteRepository(db),
        audit=MongoAuditLogRepository(db),
    )


async def _run_crawl_job(
    ctx: dict[str, Any],
    crawl_job_id: str,
    *,
    crawl_jobs: Any,
    documents: Any,
    websites: Any,
    audit: Any,
) -> dict[str, Any]:
    """Core worker logic, testable with fake repositories/fetcher injected.

    `ctx["crawler_fetcher"]` may supply a `PageFetcher` (used by tests to
    avoid launching Chromium); production uses `BrowserPageFetcher`.
    """
    job = await crawl_jobs.find_by_id_any(crawl_job_id)
    if job is None:
        logger.warning("crawl job %s not found; skipping", crawl_job_id)
        return {"status": "not_found"}
    if job.status not in CRAWL_ACTIVE_STATUSES:
        return {"status": job.status}

    website = await websites.find_by_id(job.tenant_id, job.website_id)
    if website is None:
        job.status = CRAWL_STATUS_FAILED
        job.error_message = "Website no longer exists."
        job.completed_at = utcnow()
        job.updated_at = utcnow()
        await crawl_jobs.update(job)
        return {"status": "failed"}

    job.status = CRAWL_STATUS_RUNNING
    job.started_at = job.started_at or utcnow()
    job.updated_at = utcnow()
    await crawl_jobs.update(job)

    async def on_progress(completed: int, total: int) -> None:
        job.pages_completed = completed
        job.pages_total = total
        job.updated_at = utcnow()
        await crawl_jobs.update(job)

    guard = SsrFGuard()
    fetcher = ctx.get("crawler_fetcher") or BrowserPageFetcher(guard=guard)
    session = CrawlSession(
        tenant_id=job.tenant_id,
        website_id=job.website_id,
        seed_url=website.url,
        fetcher=fetcher,
        documents=documents,
        guard=guard,
        on_progress=on_progress,
    )

    try:
        job.status = CRAWL_STATUS_PROCESSING
        job.updated_at = utcnow()
        await crawl_jobs.update(job)

        # Bounds how many browser sessions may hold a Chromium context at once
        # (memory safety): `max_jobs` allows many jobs in flight, but only
        # `crawl_max_concurrent` ever drive the shared headless browser.
        async with crawl_semaphore():
            stored = await session.run()
        job.errors = session.errors
        job.pages_completed = stored
        job.pages_total = max(job.pages_total, stored)
        job.status = CRAWL_STATUS_COMPLETED
        job.completed_at = utcnow()
        job.error_message = None
        job.updated_at = utcnow()
        await crawl_jobs.update(job)

        website.status = WEBSITE_STATUS_READY
        website.pages_indexed = await documents.count_by_website(
            job.tenant_id, job.website_id
        )
        website.last_crawled_at = job.completed_at
        website.checksum = await _site_checksum(documents, job.tenant_id, job.website_id)
        website.updated_at = utcnow()
        await websites.update(website)
        await audit.create(
            AuditLog.new(action=AUDIT_CRAWL_COMPLETED, tenant_id=job.tenant_id)
        )
        return {"status": "completed", "pages": stored}
    except InvalidUrlError as exc:
        # Deterministic failure: the seed is not crawlable (SSRF-blocked,
        # malformed, non-http scheme). Retrying cannot fix it, so fail the job
        # immediately and do NOT re-raise (ARQ would back off and retry).
        job.status = CRAWL_STATUS_FAILED
        job.completed_at = utcnow()
        job.error_message = f"{type(exc).__name__}: {exc}"
        job.updated_at = utcnow()
        await crawl_jobs.update(job)
        website.status = WEBSITE_STATUS_FAILED
        website.updated_at = utcnow()
        await websites.update(website)
        await audit.create(
            AuditLog.new(action=AUDIT_CRAWL_FAILED, tenant_id=job.tenant_id)
        )
        logger.warning("crawl job %s failed (permanent): %s", crawl_job_id, exc)
        return {"status": "failed"}
    except Exception as exc:
        job_try = int(ctx.get("job_try", 1))
        max_tries = int(ctx.get("max_tries", 3))
        if job_try >= max_tries:
            job.status = CRAWL_STATUS_FAILED
            job.completed_at = utcnow()
            job.error_message = f"{type(exc).__name__}: {exc}"
            job.updated_at = utcnow()
            await crawl_jobs.update(job)
            website.status = WEBSITE_STATUS_FAILED
            website.updated_at = utcnow()
            await websites.update(website)
            await audit.create(
                AuditLog.new(action=AUDIT_CRAWL_FAILED, tenant_id=job.tenant_id)
            )
        else:
            job.updated_at = utcnow()
            await crawl_jobs.update(job)
        logger.warning(
            "crawl job %s failed (try %s/%s): %s", crawl_job_id, job_try, max_tries, exc
        )
        raise


async def _site_checksum(
    documents: Any, tenant_id: str, website_id: str
) -> str:
    """Aggregate checksum over the website's stored documents (Phase 5 diff)."""
    digests = await documents.all_checksums(tenant_id, website_id)
    return hashlib.sha256("".join(sorted(digests)).encode("utf-8")).hexdigest()
