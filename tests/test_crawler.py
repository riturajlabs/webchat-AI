"""Unit tests for the BFS crawl engine (Phase 4 ingestion)."""

import hashlib

import pytest
from backend.services.ingestion import CrawlSession, FetchError, SsrFGuard
from tests.crawl_helpers import SAMPLE_ABOUT, SAMPLE_HTML, FakePageFetcher
from tests.fakes import FakeDocumentRepository

SEED = "https://acme.example/"


@pytest.fixture
def guard(monkeypatch):
    g = SsrFGuard()

    async def fake_resolve(host: str) -> list[str]:
        return ["93.184.216.34"]

    monkeypatch.setattr(g, "resolve_async", fake_resolve)
    return g


def _session(fetcher: FakePageFetcher, guard: SsrFGuard, **kwargs) -> CrawlSession:
    return CrawlSession(
        tenant_id="tenant-a",
        website_id="website-a",
        seed_url=SEED,
        fetcher=fetcher,
        documents=FakeDocumentRepository(),
        guard=guard,
        **kwargs,
    )


async def test_crawls_seed_and_follows_internal_links(guard) -> None:
    fetcher = FakePageFetcher({SEED: SAMPLE_HTML, "https://acme.example/about": SAMPLE_ABOUT})
    documents = FakeDocumentRepository()
    progress: list[tuple[int, int]] = []

    async def on_progress(completed: int, total: int) -> None:
        progress.append((completed, total))

    session = CrawlSession(
        tenant_id="tenant-a",
        website_id="website-a",
        seed_url=SEED,
        fetcher=fetcher,
        documents=documents,
        guard=guard,
        on_progress=on_progress,
    )
    stored = await session.run()

    assert stored == 2
    assert fetcher.closed is True
    assert {doc.url for doc in documents.documents.values()} == {
        SEED,
        "https://acme.example/about",
    }
    # The home page content is cleaned and stored with a SHA-256 checksum.
    home = next(doc for doc in documents.documents.values() if doc.url == SEED)
    assert "Welcome to Acme" in home.content
    assert home.title == "Acme Home"
    assert home.checksum == hashlib.sha256(home.content.encode("utf-8")).hexdigest()
    assert progress[0] == (0, 50)
    assert progress[-1] == (2, 50)


async def test_deduplicates_normalized_links(guard) -> None:
    # /about and /about?utm_source=ad#frag normalize to the same URL, so the
    # about page is fetched exactly once.
    pricing = "<html><body><main><h1>Pricing</h1><p>Plans.</p></main></body></html>"
    fetcher = FakePageFetcher(
        {
            SEED: SAMPLE_HTML,
            "https://acme.example/about": SAMPLE_ABOUT,
            "https://acme.example/pricing": pricing,
        }
    )
    session = _session(fetcher, guard)
    stored = await session.run()
    assert stored == 3
    assert session.errors == []


async def test_respects_max_depth(guard) -> None:
    page2 = "<html><body><main><h1>Page 2</h1><p>Deep page.</p></main></body></html>"
    home = (
        "<html><body><main>"
        "<h1>Home</h1><p>Home body.</p>"
        '<a href="/about">About</a>'
        "</main></body></html>"
    )
    about = (
        "<html><body><main>"
        "<h1>About</h1><p>About body.</p>"
        '<a href="/deep">Deep</a>'
        "</main></body></html>"
    )
    fetcher = FakePageFetcher(
        {
            SEED: home,
            "https://acme.example/about": about,
            "https://acme.example/deep": page2,
        }
    )
    session = CrawlSession(
        tenant_id="tenant-a",
        website_id="website-a",
        seed_url=SEED,
        fetcher=fetcher,
        documents=FakeDocumentRepository(),
        guard=guard,
        settings=_settings_with(max_depth=1),
    )
    stored = await session.run()
    assert stored == 2  # /deep is beyond depth 1 and never fetched
    assert "https://acme.example/deep" not in {d.url for d in session._documents.documents.values()}


async def test_respects_max_pages_cap(guard) -> None:
    pages = {SEED: SAMPLE_HTML, "https://acme.example/about": SAMPLE_ABOUT}
    fetcher = FakePageFetcher(pages)
    session = CrawlSession(
        tenant_id="tenant-a",
        website_id="website-a",
        seed_url=SEED,
        fetcher=fetcher,
        documents=FakeDocumentRepository(),
        guard=guard,
        settings=_settings_with(max_pages=1),
    )
    stored = await session.run()
    assert stored == 1


async def test_skips_off_site_links(guard) -> None:
    pages = {
        SEED: SAMPLE_HTML,  # contains https://evil.example/hijack
        "https://acme.example/about": SAMPLE_ABOUT,
    }
    fetcher = FakePageFetcher(pages)
    session = _session(fetcher, guard)
    stored = await session.run()
    assert stored == 2
    hijacked = {d.url for d in session._documents.documents.values()}
    assert "https://evil.example/hijack" not in hijacked


async def test_respects_robots_disallow(guard) -> None:
    robots = "User-agent: *\nDisallow: /private\nDisallow: /admin\nAllow: /\n"
    fetcher = FakePageFetcher(
        {
            SEED: "<html><body><main><h1>Home</h1><p>Home.</p>"
            '<a href="/private/secret">Secret</a>'
            '<a href="/about">About</a></main></body></html>',
            "https://acme.example/robots.txt": robots,
            "https://acme.example/private/secret": "<html><body>hidden</body></html>",
            "https://acme.example/about": SAMPLE_ABOUT,
        }
    )
    session = _session(fetcher, guard)
    stored = await session.run()
    assert stored == 2  # home + about; /private/secret is robots-blocked
    urls = {d.url for d in session._documents.documents.values()}
    assert "https://acme.example/private/secret" not in urls


async def test_records_fetch_failures_and_continues(guard) -> None:
    fetcher = FakePageFetcher({SEED: SAMPLE_HTML, "https://acme.example/about": SAMPLE_ABOUT})
    fetcher.fail("https://acme.example/about", FetchError("timeout"))
    session = _session(fetcher, guard)
    stored = await session.run()
    assert stored == 1
    assert any(e.url == "https://acme.example/about" for e in session.errors)


async def test_skips_pages_without_extractable_content(guard) -> None:
    fetcher = FakePageFetcher(
        {SEED: "<html><head><title>X</title></head><body><script>void 0</script></body></html>"}
    )
    session = _session(fetcher, guard)
    stored = await session.run()
    assert stored == 0
    assert any(e.url == SEED and "content" in e.message for e in session.errors)


async def test_skips_pages_exceeding_response_size_limit(guard) -> None:
    oversized = SAMPLE_ABOUT + ("x" * 10_000)
    fetcher = FakePageFetcher({SEED: SAMPLE_HTML, "https://acme.example/about": oversized})
    session = CrawlSession(
        tenant_id="tenant-a",
        website_id="website-a",
        seed_url=SEED,
        fetcher=fetcher,
        documents=FakeDocumentRepository(),
        guard=guard,
        settings=_settings_with(max_html_bytes=1_000),
    )
    stored = await session.run()
    assert stored == 1  # only the seed is stored; /about exceeds the limit
    assert {d.url for d in session._documents.documents.values()} == {SEED}
    assert any(
        e.url == "https://acme.example/about" and "size limit" in e.message for e in session.errors
    )


def _settings_with(
    *,
    max_pages: int | None = None,
    max_depth: int | None = None,
    max_html_bytes: int | None = None,
):
    """A settings stub carrying only the crawl knobs the session reads."""
    from backend.core.config import Settings

    values: dict = {"environment": "test"}
    if max_pages is not None:
        values["crawl_max_pages"] = max_pages
    if max_depth is not None:
        values["crawl_max_depth"] = max_depth
    if max_html_bytes is not None:
        values["crawl_max_html_bytes"] = max_html_bytes
    return Settings(_env_file=None, **values)
