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
    # The thin pricing page is stored but flagged as insufficient content
    # (content-length validation), not silently dropped or embedded.
    assert any(e.url == "https://acme.example/pricing" for e in session.errors)


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


async def test_closes_fetcher_when_crawl_raises(guard) -> None:
    """INGEST-01: an unexpected mid-crawl failure still releases the browser.

    Only per-page *recoverable* errors (FetchError/InvalidUrlError) are caught
    inside the loop; clean_html/extract/upsert failures propagate to the worker.
    The fetcher (Chromium context) must be closed on that path too, otherwise a
    leaked context survives until process exit.
    """
    fetcher = FakePageFetcher({SEED: SAMPLE_HTML, "https://acme.example/about": SAMPLE_ABOUT})
    fetcher.fail("https://acme.example/about", RuntimeError("browser crashed"))
    session = _session(fetcher, guard)
    with pytest.raises(RuntimeError, match="browser crashed"):
        await session.run()
    assert fetcher.closed is True


async def test_skips_pages_without_extractable_content(guard) -> None:
    fetcher = FakePageFetcher(
        {SEED: "<html><head><title>X</title></head><body><script>void 0</script></body></html>"}
    )
    session = _session(fetcher, guard)
    stored = await session.run()
    # The empty page is stored as a failed document (dashboard visibility)
    # rather than dropped entirely: it is recorded as insufficient content.
    assert stored == 1
    assert any(e.url == SEED and "content" in e.message for e in session.errors)
    stored_doc = next(iter(session._documents.documents.values()))
    assert stored_doc.knowledge_status == "failed"


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


async def test_seeds_priority_url_paths_ahead_of_discovered_links(guard) -> None:
    """Configured authoritative paths are crawled before the page budget runs out.

    A link-dense homepage with many course links plus explicit priority paths
    (/admissions, /courses-apply) must store the priority pages first, even when
    the budget is tight enough that some discovered links are never reached.
    """
    links = "".join(f'<a href="/course/page-{i}">Course {i}</a>' for i in range(60))
    pages = {
        SEED: ("<html><body><main><h1>Home</h1><p>home body</p>" + links + "</main></body></html>"),
        "https://acme.example/admissions": (
            "<html><body><main><h1>Admissions</h1>"
            "<p>admission process body</p></main></body></html>"
        ),
        "https://acme.example/courses-apply": (
            "<html><body><main><h1>Apply</h1><p>apply body</p></main></body></html>"
        ),
    }
    for i in range(30):
        pages[f"https://acme.example/course/page-{i}"] = (
            "<html><body><main><h1>Page</h1><p>course body. </p></main></body></html>"
        )
    fetcher = FakePageFetcher(pages)
    session = CrawlSession(
        tenant_id="tenant-a",
        website_id="website-a",
        seed_url=SEED,
        fetcher=fetcher,
        documents=FakeDocumentRepository(),
        guard=guard,
        settings=_settings_with(max_pages=3, priority_paths=["/admissions", "/courses-apply"]),
    )
    stored = await session.run()
    assert stored == 3
    urls = [d.url for d in session._documents.documents.values()]
    assert urls[0] == SEED
    assert "https://acme.example/admissions" in urls
    assert "https://acme.example/courses-apply" in urls
    # Both priority pages come before any discovered course page.
    course_0 = "https://acme.example/course/page-0"
    assert (
        "https://acme.example/admissions" in urls and "https://acme.example/courses-apply" in urls
    )
    if course_0 in urls:
        assert urls.index("https://acme.example/admissions") < urls.index(course_0)


async def test_priority_url_paths_are_same_origin_only(guard) -> None:
    """Off-origin priority paths are rejected; priority paths dedupe against the seed."""
    pages = {
        SEED: (
            "<html><body><main><h1>Home</h1><p>home body</p>"
            '<a href="/about">About</a></main></body></html>'
        ),
        "https://acme.example/about": SAMPLE_ABOUT,
    }
    # /about is both a priority path and a discovered link; the seed itself is a
    # priority path that must not be re-queued.
    fetcher = FakePageFetcher(pages)
    session = CrawlSession(
        tenant_id="tenant-a",
        website_id="website-a",
        seed_url=SEED,
        fetcher=fetcher,
        documents=FakeDocumentRepository(),
        guard=guard,
        settings=_settings_with(
            max_pages=5,
            priority_paths=["/about", "", "https://evil.example/x", SEED],
        ),
    )
    stored = await session.run()
    assert stored == 2
    assert {d.url for d in session._documents.documents.values()} == {
        SEED,
        "https://acme.example/about",
    }


async def test_raises_when_memory_ceiling_exceeded(guard, monkeypatch) -> None:
    """FIND-01: crossing the worker ceiling raises CrawlMemoryGuardError.

    The crawl aborts recoverably (the guard excises the silent-continue path)
    and the fetcher is still released so Chromium does not leak past the abort.
    """
    import backend.services.ingestion.crawler as crawler_mod
    from backend.services.ingestion.crawler import CrawlMemoryGuardError

    fetcher = FakePageFetcher({SEED: SAMPLE_HTML, "https://acme.example/about": SAMPLE_ABOUT})
    # RSS reads as far above the 10 MiB ceiling, so the crawl aborts up-front.
    monkeypatch.setattr(crawler_mod, "_current_rss_mb", lambda: 100)
    session = CrawlSession(
        tenant_id="tenant-a",
        website_id="website-a",
        seed_url=SEED,
        fetcher=fetcher,
        documents=FakeDocumentRepository(),
        guard=guard,
        settings=_settings_with(max_rss_mb=10),
    )
    with pytest.raises(CrawlMemoryGuardError) as exc_info:
        await session.run()
    assert session.memory_pressure_aborted is True
    assert exc_info.value.current_mb == 100
    assert exc_info.value.ceiling_mb == 10
    assert exc_info.value.source in {"cgroup_v2", "cgroup_v1", "process_tree", "unavailable"}
    # Browser/context cleanup still happens on the guard abort path.
    assert fetcher.closed is True
    assert any("memory" in e.message for e in session.errors)


async def test_memory_guard_fails_open_when_unmeasurable(guard, monkeypatch) -> None:
    """FIND-01: an unreadable footprint never wedges the crawl (fail-open)."""
    import backend.services.ingestion.crawler as crawler_mod

    fetcher = FakePageFetcher({SEED: SAMPLE_HTML, "https://acme.example/about": SAMPLE_ABOUT})
    # 0 MiB signals "cannot measure"; the crawl must continue, not abort.
    monkeypatch.setattr(crawler_mod, "_current_rss_mb", lambda: 0)
    session = _session(fetcher, guard, settings=_settings_with(max_rss_mb=100))
    stored = await session.run()
    assert stored == 2
    assert session.memory_pressure_aborted is False


async def test_memory_ceiling_disabled_by_default(guard, monkeypatch) -> None:
    """With crawl_max_rss_mb=0 the memory check never triggers."""
    import backend.services.ingestion.crawler as crawler_mod

    fetcher = FakePageFetcher({SEED: SAMPLE_HTML, "https://acme.example/about": SAMPLE_ABOUT})
    monkeypatch.setattr(crawler_mod, "_current_rss_mb", lambda: 10**9)
    session = _session(fetcher, guard, settings=_settings_with(max_rss_mb=0))
    stored = await session.run()
    assert stored == 2
    assert session.memory_pressure_aborted is False


def _settings_with(
    *,
    max_pages: int | None = None,
    max_depth: int | None = None,
    max_html_bytes: int | None = None,
    max_rss_mb: int | None = None,
    priority_paths: list[str] | None = None,
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
    if max_rss_mb is not None:
        values["crawl_max_rss_mb"] = max_rss_mb
    if priority_paths is not None:
        values["crawl_priority_url_paths"] = priority_paths
    return Settings(_env_file=None, **values)
