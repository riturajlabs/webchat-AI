"""BFS crawl engine for the ingestion worker (Phase 4, ADR-002).

Walks the tenant's website breadth-first from the seed URL, honouring the
crawl caps (max pages, max depth), robots.txt, per-page SSRF validation
(`SsrFGuard`), same-site link scoping, and URL normalization (fragments and
tracking parameters are stripped so pages differing only in attribution are
not crawled twice). Each fetched page is extracted, cleaned and upserted into
the `documents` collection with a SHA-256 content checksum (the Phase 5 change
detector).
"""

import hashlib
import logging
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

from backend.core.config import Settings, get_settings
from backend.core.errors import InvalidUrlError
from backend.models.crawl_job import CrawlJobError
from backend.models.document import Document
from backend.models.knowledge_chunk import KNOWLEDGE_STATUS_FAILED
from backend.repositories import DocumentRepository
from backend.services.ingestion.cleaner import clean_html
from backend.services.ingestion.extractor import extract_page, pick_preview_image
from backend.services.ingestion.ssrf_guard import SsrFGuard
from backend.utils.robots import RobotsTxt
from backend.utils.url_validator import normalize_crawl_url, validate_hostname

logger = logging.getLogger("webchat_ai")

_MAX_RECORDED_ERRORS = 50

INSUFFICIENT_CONTENT_REASON = "Insufficient content"


class FetchError(Exception):
    """A page could not be fetched (timeout, network error, blocked request)."""


@dataclass(frozen=True)
class FetchedPage:
    """A successfully loaded page and its final URL (post-redirects)."""

    url: str
    html: str


class PageFetcher(Protocol):
    """Minimal fetch surface the crawler needs (Playwright or fake)."""

    async def fetch(self, url: str) -> FetchedPage: ...

    async def close(self) -> None: ...


ProgressCallback = Callable[[int, int], Awaitable[None]]
PhaseCallback = Callable[[str], Awaitable[None]]


class CrawlSession:
    """Executes one crawl job's page walk; callers own error recording."""

    def __init__(
        self,
        *,
        tenant_id: str,
        website_id: str,
        seed_url: str,
        fetcher: PageFetcher,
        documents: DocumentRepository,
        guard: SsrFGuard | None = None,
        robots: RobotsTxt | None = None,
        on_progress: ProgressCallback | None = None,
        on_fetching: PhaseCallback | None = None,
        on_extracting: PhaseCallback | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._tenant_id = tenant_id
        self._website_id = website_id
        self._seed_url = seed_url
        self._fetcher = fetcher
        self._documents = documents
        self._guard = guard or SsrFGuard()
        self._robots = robots
        self._on_progress = on_progress
        self._on_fetching = on_fetching
        self._on_extracting = on_extracting
        self._settings = settings or get_settings()
        self.errors: list[CrawlJobError] = []
        # URLs successfully persisted during run(); consumed by post-crawl
        # reconciliation so pages removed from the site can be purged (R-02).
        self.stored_urls: list[str] = []
        # Open Graph / Twitter preview image captured from the seed (home) page.
        self.preview_image: str | None = None

    async def run(self) -> int:
        """Crawl the site and persist cleaned pages. Returns pages stored."""
        seed = normalize_crawl_url(self._seed_url, self._seed_url)
        if seed is None:
            raise InvalidUrlError("The website URL is not crawlable.")
        await self._guard.validate_async(seed)
        seed_host = self._site_host(seed)
        if self._robots is None:
            self._robots = await self._fetch_robots(seed)

        max_pages = self._settings.crawl_max_pages
        max_depth = self._settings.crawl_max_depth
        queue: deque[tuple[str, int]] = deque([(seed, 0)])
        visited: set[str] = set()
        stored = 0
        if self._on_progress is not None:
            await self._on_progress(0, max_pages)

        while queue and stored < max_pages:
            url, depth = queue.popleft()
            normalized = normalize_crawl_url(url, url) or url
            if normalized in visited:
                continue
            visited.add(normalized)
            if not self._robots.is_allowed(urlparse(normalized).path or "/"):
                continue
            try:
                if self._on_fetching is not None:
                    await self._on_fetching(normalized)
                page = await self._fetcher.fetch(normalized)
            except (FetchError, InvalidUrlError) as exc:
                self._record_error(normalized, str(exc))
                continue

            # Response size limit: the browser truncates rendered HTML at this
            # ceiling; any fetcher that still returns a larger page is skipped.
            if len(page.html) > self._settings.crawl_max_html_bytes:
                self._record_error(normalized, "Response exceeded the size limit.")
                continue

            extracted = extract_page(page.html, page.url)
            final_url = normalize_crawl_url(page.url, page.url) or page.url
            if self._on_extracting is not None:
                await self._on_extracting(final_url)
            if stored == 0 and self.preview_image is None:
                self.preview_image = pick_preview_image(extracted.meta, page.url)
            content = clean_html(page.html, max_chars=self._settings.crawl_max_content_bytes)
            checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
            document = Document.new(
                tenant_id=self._tenant_id,
                website_id=self._website_id,
                url=final_url,
                title=extracted.title or final_url,
                content=content,
                checksum=checksum,
                language=extracted.language,
            )
            # Content-length validation: pages with no (or too little) cleaned
            # text cannot be embedded usefully, so they are stored as failed
            # documents the dashboard can surface and the owner can re-crawl
            # (instead of being silently dropped or embedded into junk).
            if len(content.strip()) < self._settings.knowledge_min_content_chars:
                document.knowledge_status = KNOWLEDGE_STATUS_FAILED
                document.knowledge_failure_reason = INSUFFICIENT_CONTENT_REASON
                self._record_error(final_url, INSUFFICIENT_CONTENT_REASON)
            await self._documents.upsert(document)
            stored += 1
            self.stored_urls.append(final_url)
            if self._on_progress is not None:
                await self._on_progress(stored, max_pages)

            if depth < max_depth:
                for link in extracted.links:
                    if self._site_host(link) != seed_host:
                        continue
                    try:
                        validate_hostname(urlparse(link).hostname or "")
                    except InvalidUrlError:
                        continue
                    candidate = normalize_crawl_url(link, link)
                    if candidate is not None and candidate not in visited:
                        queue.append((candidate, depth + 1))

        await self._fetcher.close()
        return stored

    # ------------------------------------------------------------ internals

    async def _fetch_robots(self, seed: str) -> RobotsTxt:
        """Fetch and parse robots.txt through the same SSRF-guarded fetcher."""
        parsed = urlparse(seed)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        try:
            page = await self._fetcher.fetch(robots_url)
        except (FetchError, InvalidUrlError):
            return RobotsTxt.allow_all()
        return RobotsTxt.parse(page.html)

    def _record_error(self, url: str, message: str) -> None:
        if len(self.errors) >= _MAX_RECORDED_ERRORS:
            return
        self.errors.append(CrawlJobError(url=url, message=message))

    @staticmethod
    def _site_host(url: str) -> str:
        """Hostname with a leading `www.` stripped (www == bare host)."""
        host = (urlparse(url).hostname or "").lower()
        return host[4:] if host.startswith("www.") else host
