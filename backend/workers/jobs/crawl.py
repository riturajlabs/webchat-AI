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
from typing import Any, cast

from arq.connections import ArqRedis
from redis.asyncio import ConnectionPool

from backend.core import crawl_events
from backend.core.cache import CacheStore, RedisCacheStore
from backend.core.config import get_settings
from backend.core.database import MongoDB
from backend.core.errors import InvalidUrlError
from backend.core.logging import request_id_var, tenant_id_var
from backend.core.metrics import record_crawl_completed, record_crawl_failed, record_crawl_started
from backend.core.redis import get_redis
from backend.core.security import utcnow
from backend.models.audit_log import AUDIT_CRAWL_COMPLETED, AUDIT_CRAWL_FAILED, AuditLog
from backend.models.crawl_job import (
    CRAWL_ACTIVE_STATUSES,
    CRAWL_STATUS_COMPLETED,
    CRAWL_STATUS_FAILED,
    CRAWL_STATUS_PROCESSING,
    CRAWL_STATUS_RUNNING,
)
from backend.models.usage_record import USAGE_COUNTER_CRAWL_PAGES, usage_date_key
from backend.models.website import WEBSITE_STATUS_FAILED, WEBSITE_STATUS_READY
from backend.repositories import (
    MongoAuditLogRepository,
    MongoCrawlJobRepository,
    MongoDocumentRepository,
    MongoUsageRecordRepository,
    MongoVectorRepository,
    MongoWebsiteRepository,
)
from backend.services.ingestion import (
    BrowserPageFetcher,
    CrawlMemoryGuardError,
    CrawlSession,
    HybridPageFetcher,
    PageFetcher,
    SsrFGuard,
)
from backend.services.ingestion.browser import crawl_semaphore
from backend.services.ingestion.crawl_failure import (
    CrawlFailureClassification,
    safe_url_parts,
    user_facing_reason,
)
from backend.workers.jobs.knowledge import enqueue_process_website_documents

logger = logging.getLogger("webchat_ai")

_pool: ConnectionPool | None = None

# Terminal failure reasons that get a safe, user-facing sentence instead of the
# generic "No pages were fetched." (docs/CRAWL_EGRESS_HARDENING.md, Phase 5).
_SAFE_ZERO_PAGE_REASONS = frozenset(
    {
        CrawlFailureClassification.TARGET_BLOCKED.value,
        CrawlFailureClassification.TARGET_RATE_LIMITED.value,
    }
)


def _make_page_fetcher(ctx: dict[str, Any], guard: SsrFGuard) -> PageFetcher:
    """Pick the crawler fetcher: injected (tests) else HTTP-first hybrid.

    Production stays on plain HTTP/HTTPS by default and only opens the shared
    headless Chromium instance when a page is judged to need JavaScript.
    `CRAWL_HTTP_FIRST=false` restores the previous browser-only fetcher.
    """
    provided = ctx.get("crawler_fetcher")
    if provided is not None:
        return cast(PageFetcher, provided)
    if get_settings().crawl_http_first:
        return HybridPageFetcher(guard=guard)
    return BrowserPageFetcher(guard=guard)


def _arq_redis() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = ConnectionPool.from_url(get_settings().redis_url, decode_responses=True)
    return ArqRedis(connection_pool=_pool)


def _build_cache() -> CacheStore | None:
    """Build a RedisCacheStore for retrieval cache invalidation.

    Uses the shared singleton Redis client from ``core.redis`` so worker
    connections are pooled and closed on shutdown.  Returns ``None`` if
    Redis is unavailable — invalidation is best-effort and must never fail
    the crawl job.
    """
    try:
        # Audit R-01: the API writes retrieval entries under
        # `{redis_prefix}:rag:...` (see deps.get_rag_service). The worker must
        # invalidate that exact namespace, otherwise stale answers survive the
        # full TTL after every re-crawl.
        return RedisCacheStore(get_redis(), prefix=f"{get_settings().redis_prefix}:rag")
    except Exception:
        logger.warning("Could not build cache for crawl invalidation", exc_info=True)
        return None


async def enqueue_crawl_website(crawl_job_id: str) -> None:
    """Enqueue a crawl job for the ARQ worker (ADR-002 task registry)."""
    await _arq_redis().enqueue_job("crawl_website", crawl_job_id)


async def crawl_website(ctx: dict[str, Any], crawl_job_id: str) -> dict[str, Any]:
    """Worker task: run one crawl job and record the outcome on the website."""
    db = MongoDB.db()
    cache = _build_cache()
    return await _run_crawl_job(
        ctx,
        crawl_job_id,
        crawl_jobs=MongoCrawlJobRepository(db),
        documents=MongoDocumentRepository(db),
        vector=MongoVectorRepository(db),
        websites=MongoWebsiteRepository(db),
        audit=MongoAuditLogRepository(db),
        usage=MongoUsageRecordRepository(db),
        enqueue_knowledge=enqueue_process_website_documents,
        cache=cache,
    )


async def _run_crawl_job(
    ctx: dict[str, Any],
    crawl_job_id: str,
    *,
    crawl_jobs: Any,
    documents: Any,
    websites: Any,
    audit: Any,
    usage: Any = None,
    enqueue_knowledge: Any = None,
    cache: CacheStore | None = None,
    vector: Any = None,
) -> dict[str, Any]:
    """Correlate worker logs to the job and tenant, then run the crawl (OBS-02).

    The ARQ worker executes each job in its own task (``create_task`` copies
    the context), so the values cannot leak across jobs; the finally-reset
    mirrors ``RequestIDMiddleware`` and keeps the call site's context clean.
    The tenant context is set inside ``_run_crawl_job_impl`` once the job is
    loaded; capturing it here (even as a no-op) lets us restore it on the way
    out instead of leaving the job's tenant behind on the caller's context.
    """
    request_token = request_id_var.set(f"job:{crawl_job_id}")
    tenant_token = tenant_id_var.set(tenant_id_var.get())
    try:
        return await _run_crawl_job_impl(
            ctx,
            crawl_job_id,
            crawl_jobs=crawl_jobs,
            documents=documents,
            websites=websites,
            audit=audit,
            usage=usage,
            enqueue_knowledge=enqueue_knowledge,
            cache=cache,
            vector=vector,
        )
    finally:
        request_id_var.reset(request_token)
        tenant_id_var.reset(tenant_token)


async def _run_crawl_job_impl(
    ctx: dict[str, Any],
    crawl_job_id: str,
    *,
    crawl_jobs: Any,
    documents: Any,
    websites: Any,
    audit: Any,
    usage: Any = None,
    enqueue_knowledge: Any = None,
    cache: CacheStore | None = None,
    vector: Any = None,
) -> dict[str, Any]:
    """Core worker logic, testable with fake repositories/fetcher injected.

    `ctx["crawler_fetcher"]` may supply a `PageFetcher` (used by tests to
    avoid launching Chromium); production uses the HTTP-first `HybridPageFetcher`.
    """
    job = await crawl_jobs.find_by_id_any(crawl_job_id)
    if job is None:
        logger.warning("crawl job %s not found; skipping", crawl_job_id)
        return {"status": "not_found"}
    if job.status not in CRAWL_ACTIVE_STATUSES:
        return {"status": job.status}
    tenant_id_var.set(job.tenant_id)

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
    await crawl_events.publish_started(job.id)
    record_crawl_started()
    logger.info(
        "crawl_started job_id=%s tenant_id=%s website_id=%s",
        job.id,
        job.tenant_id,
        job.website_id,
    )

    async def on_progress(completed: int, total: int) -> None:
        job.pages_completed = completed
        job.pages_total = total
        job.updated_at = utcnow()
        await crawl_jobs.update(job)
        await crawl_events.publish_progress(
            job.id,
            pages_completed=completed,
            pages_total=total,
        )

    guard = SsrFGuard()
    fetcher = _make_page_fetcher(ctx, guard)

    async def on_fetching(url: str) -> None:
        await crawl_events.publish_fetching(
            job.id,
            current_url=url,
            pages_completed=job.pages_completed,
            pages_total=job.pages_total,
        )

    async def on_extracting(url: str) -> None:
        await crawl_events.publish_extracting(job.id, url=url)

    session = CrawlSession(
        tenant_id=job.tenant_id,
        website_id=job.website_id,
        seed_url=website.url,
        fetcher=fetcher,
        documents=documents,
        guard=guard,
        on_progress=on_progress,
        on_fetching=on_fetching,
        on_extracting=on_extracting,
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
        if stored == 0:
            job.errors = session.errors
            job.pages_completed = 0
            job.status = CRAWL_STATUS_FAILED
            job.completed_at = utcnow()
            first_error = session.errors[0] if session.errors else None
            # Phase 5 (egress hardening): score the outcome from the FIRST useful
            # failure - the URL and classification that prove the target (not the
            # worker) rejected automated crawling. Never expose network/egress
            # internals to the dashboard.
            classification = first_error.classification if first_error is not None else None
            if classification in _SAFE_ZERO_PAGE_REASONS:
                job.error_message = user_facing_reason(CrawlFailureClassification(classification))
                failure_reason = classification
            else:
                job.error_message = "No pages were fetched."
                failure_reason = "no_pages"
            job.updated_at = utcnow()
            await crawl_jobs.update(job)
            await crawl_events.publish_failed(job.id, error=job.error_message)

            existing_pages = await documents.count_by_website(job.tenant_id, job.website_id)
            if existing_pages == 0:
                website.status = WEBSITE_STATUS_FAILED
                website.pages_indexed = 0
            else:
                website.status = WEBSITE_STATUS_READY
                website.pages_indexed = existing_pages
                # Surface that the previous knowledge base survives a blocked
                # refresh (existing documents are never deleted by a zero-page
                # recrawl).
                job.error_message = (
                    f"{job.error_message} Your existing knowledge base is still available."
                )
            website.updated_at = utcnow()
            await websites.update(website)

            await audit.create(AuditLog.new(action=AUDIT_CRAWL_FAILED, tenant_id=job.tenant_id))
            record_crawl_failed(reason=failure_reason)
            elapsed = (
                (job.completed_at - job.started_at).total_seconds()
                if job.started_at is not None
                else 0.0
            )
            if failure_reason in _SAFE_ZERO_PAGE_REASONS and first_error is not None:
                host, path = safe_url_parts(first_error.url)
                event_name = (
                    "crawl_target_blocked"
                    if failure_reason == CrawlFailureClassification.TARGET_BLOCKED.value
                    else "crawl_target_rate_limited"
                )
                logger.warning(
                    "%s job_id=%s tenant_id=%s website_id=%s hostname=%s path=%s "
                    "status_code=%s method=%s attempt=%s existing_pages=%d elapsed_seconds=%.2f "
                    "pages_stored=0",
                    event_name,
                    crawl_job_id,
                    job.tenant_id,
                    job.website_id,
                    host,
                    path,
                    first_error.status_code if first_error.status_code is not None else "",
                    first_error.method or "",
                    first_error.attempt if first_error.attempt is not None else "",
                    existing_pages,
                    elapsed,
                )
            if failure_reason in _SAFE_ZERO_PAGE_REASONS:
                logger.warning(
                    "crawl_finished job_id=%s tenant_id=%s website_id=%s status=failed "
                    "reason=%s pages_stored=%d pages_total=%d elapsed_seconds=%.2f",
                    crawl_job_id,
                    job.tenant_id,
                    job.website_id,
                    failure_reason,
                    0,
                    job.pages_total,
                    elapsed,
                )
            else:
                logger.info(
                    "crawl_finished job_id=%s tenant_id=%s website_id=%s status=failed "
                    "reason=%s pages_stored=%d pages_total=%d elapsed_seconds=%.2f",
                    crawl_job_id,
                    job.tenant_id,
                    job.website_id,
                    failure_reason,
                    0,
                    job.pages_total,
                    elapsed,
                )
            if session.errors:
                first_error_log = session.errors[0]
                logger.warning(
                    "crawl_failed job_id=%s tenant_id=%s reason=%s "
                    "first_error_url=%s first_error=%s classification=%s errors=%d",
                    crawl_job_id,
                    job.tenant_id,
                    failure_reason,
                    first_error_log.url,
                    first_error_log.message,
                    first_error_log.classification or "",
                    len(session.errors),
                )
            else:
                logger.warning(
                    "crawl_failed job_id=%s tenant_id=%s reason=%s errors=0",
                    crawl_job_id,
                    job.tenant_id,
                    failure_reason,
                )
            return {"status": "failed", "pages": 0}
        # Audit R-02: incremental crawls only upsert discovered pages, so
        # documents whose URL vanished from the site must be reconciled away
        # (including their embedded chunks). Best-effort: a reconciliation
        # failure must not fail an otherwise successful crawl.
        await _purge_removed_documents(
            documents=documents,
            vector=vector,
            tenant_id=job.tenant_id,
            website_id=job.website_id,
            crawled_urls=session.stored_urls,
            errored_urls=[error.url for error in session.errors],
        )
        job.errors = session.errors
        job.pages_completed = stored
        job.pages_total = max(job.pages_total, stored)
        job.status = CRAWL_STATUS_COMPLETED
        job.completed_at = utcnow()
        job.error_message = None
        job.updated_at = utcnow()
        await crawl_jobs.update(job)
        await crawl_events.publish_completed(
            job.id, pages_completed=stored, pages_total=job.pages_total, chunks=0
        )

        website.status = WEBSITE_STATUS_READY
        website.pages_indexed = await documents.count_by_website(job.tenant_id, job.website_id)
        website.last_crawled_at = job.completed_at
        website.checksum = await _site_checksum(documents, job.tenant_id, job.website_id)
        if session.preview_image is not None:
            website.preview_image = session.preview_image
        website.updated_at = utcnow()
        await websites.update(website)
        await audit.create(AuditLog.new(action=AUDIT_CRAWL_COMPLETED, tenant_id=job.tenant_id))
        # ADR-005 §5.5: roll up the pages this crawl successfully indexed.
        # Best-effort: usage-tracking outages must not fail the crawl job.
        await _record_crawl_pages(
            usage=usage,
            tenant_id=job.tenant_id,
            website_id=job.website_id,
            count=stored,
        )
        if enqueue_knowledge is not None:
            # Phase 5 handoff: fan the freshly crawled documents out as
            # per-document embedding jobs (ADR-002 task registry). The website
            # is marked `ready` here; `knowledge_chunks` is updated as each
            # document's embedding lands.
            await enqueue_knowledge(job.website_id)
        # Invalidate retrieval cache for this website so stale search results
        # from the previous crawl are not served.  Best-effort: cache outage
        # must never fail the crawl job.
        if cache is not None:
            try:
                prefix = f"{job.tenant_id}:{job.website_id}:"
                await cache.delete_by_prefix("retrieval", prefix)
                await cache.delete_by_prefix("lexical", prefix)
            except Exception:
                logger.warning(
                    "Failed to invalidate retrieval cache for website %s",
                    job.website_id,
                    exc_info=True,
                )
        record_crawl_completed()
        elapsed = (job.completed_at - job.started_at).total_seconds()
        logger.info(
            "crawl_completed job_id=%s tenant_id=%s website_id=%s pages=%d",
            job.id,
            job.tenant_id,
            job.website_id,
            stored,
        )
        if session.blocked_host_aborted:
            logger.warning(
                "crawl_finished job_id=%s tenant_id=%s website_id=%s status=completed "
                "reason=blocked_host_aborted pages_stored=%d pages_total=%d "
                "elapsed_seconds=%.2f",
                crawl_job_id,
                job.tenant_id,
                job.website_id,
                stored,
                job.pages_total,
                elapsed,
            )
        else:
            logger.info(
                "crawl_finished job_id=%s tenant_id=%s website_id=%s status=completed "
                "reason=success pages_stored=%d pages_total=%d elapsed_seconds=%.2f",
                crawl_job_id,
                job.tenant_id,
                job.website_id,
                stored,
                job.pages_total,
                elapsed,
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
        await crawl_events.publish_failed(job.id, error=str(exc))
        website.status = WEBSITE_STATUS_FAILED
        website.updated_at = utcnow()
        await websites.update(website)
        await audit.create(AuditLog.new(action=AUDIT_CRAWL_FAILED, tenant_id=job.tenant_id))
        record_crawl_failed(reason="invalid_url")
        logger.warning(
            "crawl_failed job_id=%s tenant_id=%s reason=permanent: %s",
            crawl_job_id,
            job.tenant_id,
            exc,
        )
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
            await crawl_events.publish_failed(job.id, error=str(exc))
            website.status = WEBSITE_STATUS_FAILED
            website.updated_at = utcnow()
            await websites.update(website)
            await audit.create(AuditLog.new(action=AUDIT_CRAWL_FAILED, tenant_id=job.tenant_id))
        else:
            job.updated_at = utcnow()
            await crawl_jobs.update(job)
        if isinstance(exc, CrawlMemoryGuardError):
            # FIND-01: surface memory-guard aborts distinctly in metrics and
            # logs so a deployment without a measurable budget is not mistaken
            # for run-of-the-mill site errors. Retry semantics are unchanged:
            # ARQ retries until max_tries, then the job/website land on failed.
            record_crawl_failed(reason="memory_guard")
            logger.warning(
                "crawl_failed job_id=%s tenant_id=%s try=%s/%s reason=memory_guard "
                "current_mb=%d ceiling_mb=%d source=%s limit_mb=%s",
                crawl_job_id,
                job.tenant_id,
                job_try,
                max_tries,
                exc.current_mb,
                exc.ceiling_mb,
                exc.source,
                exc.limit_mb if exc.limit_mb is not None else "unset",
            )
        else:
            record_crawl_failed(reason="exception")
            logger.warning(
                "crawl_failed job_id=%s tenant_id=%s try=%s/%s: %s",
                crawl_job_id,
                job.tenant_id,
                job_try,
                max_tries,
                exc,
            )
        raise


async def _purge_removed_documents(
    *,
    documents: Any,
    vector: Any,
    tenant_id: str,
    website_id: str,
    crawled_urls: list[str],
    errored_urls: list[str],
) -> int:
    """Delete documents (and their chunks) whose URLs left the site (R-02).

    Compares stored document URLs against the URLs crawled in this run. Pages
    that errored *this* run are forgiven — a transient fetch failure must not
    purge good content. Best-effort: any failure is logged and swallowed so
    the crawl job still completes.
    """
    try:
        keep = set(crawled_urls)
        forgive = set(errored_urls)
        stored = await documents.list_by_website(tenant_id, website_id)
        stale = [doc for doc in stored if doc.url not in keep and doc.url not in forgive]
        for document in stale:
            if vector is not None:
                await vector.delete_by_document(tenant_id, document.id)
        if stale:
            await documents.delete_by_ids(tenant_id, [doc.id for doc in stale])
            logger.info(
                "purged %s removed page(s) from the knowledge base (tenant=%s website=%s)",
                len(stale),
                tenant_id,
                website_id,
            )
        return len(stale)
    except Exception:
        logger.warning(
            "stale-document reconciliation failed (website=%s)",
            website_id,
            exc_info=True,
        )
        return 0


async def _site_checksum(documents: Any, tenant_id: str, website_id: str) -> str:
    """Aggregate checksum over the website's stored documents (Phase 5 diff)."""
    digests = await documents.all_checksums(tenant_id, website_id)
    return hashlib.sha256("".join(sorted(digests)).encode("utf-8")).hexdigest()


async def _record_crawl_pages(
    *,
    usage: Any,
    tenant_id: str,
    website_id: str,
    count: int,
) -> None:
    """Increment the daily `crawl_pages` counter after a successful crawl.

    Best-effort: a usage-tracking outage must never fail the crawl job, so any
    exception from the rollup repo is logged and dropped (mirrors the chat
    pipeline's `chat_stage("persist.usage")` policy).
    """
    if usage is None or count <= 0:
        return
    try:
        await usage.increment(
            tenant_id=tenant_id,
            website_id=website_id,
            date=usage_date_key(),
            counters={USAGE_COUNTER_CRAWL_PAGES: count},
        )
    except Exception as exc:  # noqa: BLE001 - best-effort usage tracking
        logger.warning(
            "usage rollup increment failed (counter=crawl_pages): %s",
            exc,
        )
