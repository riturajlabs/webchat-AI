"""Shared helpers for crawling tests (fake fetcher + crawl service env)."""

from dataclasses import dataclass

from backend.services.crawl import CrawlService
from backend.services.ingestion import FetchedPage, FetchError
from backend.services.website import WebsiteService

from tests.fakes import (
    FakeAuditLogRepository,
    FakeCrawlJobRepository,
    FakeDocumentRepository,
    FakeWebsiteRepository,
    FakeWidgetRepository,
)


class FakePageFetcher:
    """Serves a canned URL->HTML map (missing/failing URLs raise `FetchError`)."""

    def __init__(self, pages: dict[str, str] | None = None) -> None:
        self.pages: dict[str, str] = dict(pages or {})
        self.failures: dict[str, Exception] = {}
        self.closed = False

    async def fetch(self, url: str) -> FetchedPage:
        if url in self.failures:
            raise self.failures[url]
        if url not in self.pages:
            raise FetchError(f"Not found: {url}")
        return FetchedPage(url=url, html=self.pages[url])

    async def close(self) -> None:
        self.closed = True

    def fail(self, url: str, error: Exception) -> None:
        self.failures[url] = error


@dataclass
class CrawlEnv:
    crawl_jobs: FakeCrawlJobRepository
    documents: FakeDocumentRepository
    websites: FakeWebsiteRepository
    widgets: FakeWidgetRepository
    audit: FakeAuditLogRepository
    enqueued: list[str]
    service: CrawlService


def build_crawl_env(usage=None) -> CrawlEnv:
    """A fake-backed CrawlService wired to a recording enqueue callable."""
    crawl_jobs = FakeCrawlJobRepository()
    documents = FakeDocumentRepository()
    websites = FakeWebsiteRepository()
    widgets = FakeWidgetRepository()
    audit = FakeAuditLogRepository()
    enqueued: list[str] = []

    async def enqueue(job_id: str) -> None:
        enqueued.append(job_id)

    service = CrawlService(
        crawl_jobs=crawl_jobs,
        websites=websites,
        audit=audit,
        enqueue=enqueue,
        usage=usage,
    )
    return CrawlEnv(
        crawl_jobs=crawl_jobs,
        documents=documents,
        websites=websites,
        widgets=widgets,
        audit=audit,
        enqueued=enqueued,
        service=service,
    )


def build_website_service(
    env: CrawlEnv,
    usage=None,
) -> WebsiteService:
    """A fake-backed WebsiteService sharing the same website/audit fakes."""
    return WebsiteService(
        websites=env.websites,
        widgets=env.widgets,
        audit=env.audit,
        usage=usage,
    )


SAMPLE_HTML = """<!doctype html>
<html lang="en">
<head>
  <title>Acme Home</title>
  <meta name="description" content="Acme helps teams.">
  <link rel="canonical" href="https://acme.example/">
</head>
<body>
  <nav><a href="/pricing">Pricing</a></nav>
  <main>
    <h1>Welcome to Acme</h1>
    <p>Acme builds tools for teams.</p>
    <a href="/about">About us</a>
    <a href="/about?utm_source=ad#frag">About (tracked)</a>
    <a href="https://evil.example/hijack">External</a>
    <a href="mailto:hi@acme.example">Mail</a>
  </main>
</body>
</html>"""

SAMPLE_ABOUT = """<!doctype html>
<html lang="en">
<head><title>About Acme</title></head>
<body>
  <main>
    <h1>About</h1>
    <p>Founded in 2020.</p>
  </main>
</body>
</html>"""
