"""Tests for content-aware crawl prioritization (Phase 2, ING-01)."""

import pytest
from backend.services.ingestion import CrawlSession, SsrFGuard
from backend.services.ingestion.priority import score_crawl_candidate

from tests.crawl_helpers import FakePageFetcher
from tests.fakes import FakeDocumentRepository

SEED = "https://docs.acme.example/"


@pytest.fixture
def guard(monkeypatch):
    g = SsrFGuard()

    async def fake_resolve(host: str) -> list[str]:
        return ["93.184.216.34"]

    monkeypatch.setattr(g, "resolve_async", fake_resolve)
    return g


def _hub_home() -> str:
    """A link-dense navigation hub (many links, little <main> text)."""
    links = "".join(f'<a href="/docs/page-{i}">Page {i}</a>' for i in range(80))
    return (
        "<html><body><main><h1>Docs</h1><nav>" + links + "</nav><p>short</p></main></body></html>"
    )


def _content_page(title: str, body: str) -> str:
    return f"<html><body><main><h1>{title}</h1><p>{body}</p></main></body></html>"


def _session(fetcher, guard, **kwargs) -> CrawlSession:
    return CrawlSession(
        tenant_id="tenant-a",
        website_id="website-a",
        seed_url=SEED,
        fetcher=fetcher,
        documents=FakeDocumentRepository(),
        guard=guard,
        **kwargs,
    )


def test_score_prefers_content_leaf_over_hub():
    leaf = score_crawl_candidate(
        "https://x.example/docs/tutorial-getting-started", depth=2, max_depth=6
    )
    hub = score_crawl_candidate("https://x.example/", depth=0, max_depth=6)
    index = score_crawl_candidate("https://x.example/genindex/", depth=1, max_depth=6)
    assert leaf > hub
    assert leaf > index


def test_score_prefers_shallow_over_deep_when_equal():
    shallow = score_crawl_candidate("https://x.example/a/b", depth=2, max_depth=9)
    deep = score_crawl_candidate("https://x.example/a/b/c/d/e/f/g/h", depth=8, max_depth=9)
    assert shallow > deep


async def test_hub_pages_do_not_consume_the_entire_budget(guard):
    """A link-dense hub must not starve its content-rich leaf children."""
    pages = {SEED: _hub_home()}
    for i in range(30):
        pages[f"https://docs.acme.example/docs/page-{i}"] = _content_page(
            f"Page {i}", ("A content-rich tutorial page with plenty of text. " * 40)
        )
    fetcher = FakePageFetcher(pages)
    session = _session(fetcher, guard)
    await session.run()

    # At least one content leaf is stored (the hub deferred link-following).
    urls = {d.url for d in session._documents.documents.values()}
    leaves = [u for u in urls if u.startswith("https://docs.acme.example/docs/")]
    assert leaves


async def test_content_rich_candidates_prioritized_over_hub(guard):
    """A reference/tutorial URL is crawled before an index/landing sibling."""
    pages = {
        SEED: (
            "<html><body><main><h1>Home</h1><p>home</p>"
            '<a href="/reference/usage">Usage ref</a>'
            '<a href="/genindex/">Index</a>'
            "</main></body></html>"
        ),
        "https://docs.acme.example/reference/usage": _content_page(
            "Usage Ref", ("Reference body. " * 50)
        ),
        "https://docs.acme.example/genindex/": _content_page("Index", "index short"),
    }
    fetcher = FakePageFetcher(pages)
    session = _session(fetcher, guard)
    await session.run()

    urls = list(d.url for d in session._documents.documents.values())
    # Content leaf must appear before the hub index in visitation order.
    assert urls.index("https://docs.acme.example/reference/usage") < urls.index(
        "https://docs.acme.example/genindex/"
    )


async def test_leaf_pages_can_be_selected(guard):
    """Deep leaf pages (tutorial/howto) are discovered even under a budget."""
    pages = {
        SEED: (
            "<html><body><main><h1>Home</h1><p>home</p>"
            '<a href="/tutorial/getting-started">Tutorial</a>'
            "</main></body></html>"
        ),
        "https://docs.acme.example/tutorial/getting-started": _content_page(
            "Getting Started", ("Step by step. " * 60)
        ),
    }
    fetcher = FakePageFetcher(pages)
    session = _session(fetcher, guard)
    stored = await session.run()
    assert stored == 2
    urls = {d.url for d in session._documents.documents.values()}
    assert "https://docs.acme.example/tutorial/getting-started" in urls


async def test_generic_website_crawls_correctly(guard):
    """A plain corporate site still crawls fine (no <article> assumed)."""
    pages = {
        SEED: (
            "<html><body><main><h1>Home</h1><p>welcome to acme the best company</p>"
            '<a href="/about">About</a><a href="/pricing">Pricing</a>'
            "</main></body></html>"
        ),
        "https://docs.acme.example/about": _content_page("About", "We make software for teams."),
        "https://docs.acme.example/pricing": _content_page("Pricing", "Simple plans for everyone."),
    }
    fetcher = FakePageFetcher(pages)
    session = _session(fetcher, guard)
    stored = await session.run()
    assert stored == 3
    urls = {d.url for d in session._documents.documents.values()}
    assert urls == {
        SEED,
        "https://docs.acme.example/about",
        "https://docs.acme.example/pricing",
    }


async def test_max_pages_still_respected(guard):
    pages = {SEED: _hub_home()}
    for i in range(20):
        pages[f"https://docs.acme.example/docs/page-{i}"] = _content_page(
            f"Page {i}", ("body " * 50)
        )
    fetcher = FakePageFetcher(pages)
    session = _session(fetcher, guard, settings=_settings_with(max_pages=3))
    stored = await session.run()
    assert stored == 3


async def test_max_depth_still_respected(guard):
    pages = {
        SEED: (
            '<html><body><main><h1>H</h1><p>home</p><a href="/level1">L1</a></main></body></html>'
        ),
        "https://docs.acme.example/level1": (
            '<html><body><main><h1>L1</h1><p>l1</p><a href="/level2">L2</a></main></body></html>'
        ),
        "https://docs.acme.example/level2": _content_page("L2", "l2"),
    }
    fetcher = FakePageFetcher(pages)
    session = _session(fetcher, guard, settings=_settings_with(max_depth=1))
    stored = await session.run()
    assert stored == 2
    assert "https://docs.acme.example/level2" not in {
        d.url for d in session._documents.documents.values()
    }


async def test_domain_restrictions_remain_intact(guard):
    pages = {
        SEED: (
            "<html><body><main><h1>H</h1><p>home</p>"
            '<a href="https://other.example/offsite">Offsite</a>'
            '<a href="/docs/leaf">Leaf</a></main></body></html>'
        ),
        "https://docs.acme.example/docs/leaf": _content_page("Leaf", "leaf content"),
    }
    fetcher = FakePageFetcher(pages)
    session = _session(fetcher, guard)
    await session.run()
    urls = {d.url for d in session._documents.documents.values()}
    assert "https://other.example/offsite" not in urls


async def test_robots_and_ssrf_protections_remain_intact(guard):
    robots = "User-agent: *\nDisallow: /private\nAllow: /\n"
    pages = {
        SEED: (
            "<html><body><main><h1>H</h1><p>home</p>"
            '<a href="/private/secret">Secret</a>'
            '<a href="/tutorial/x">X</a></main></body></html>'
        ),
        "https://docs.acme.example/robots.txt": robots,
        "https://docs.acme.example/private/secret": _content_page("Secret", "secret"),
        "https://docs.acme.example/tutorial/x": _content_page("X", "tutorial content"),
    }
    fetcher = FakePageFetcher(pages)
    session = _session(fetcher, guard)
    await session.run()
    urls = {d.url for d in session._documents.documents.values()}
    assert "https://docs.acme.example/private/secret" not in urls
    assert "https://docs.acme.example/tutorial/x" in urls


async def test_deterministic_ordering_when_scores_equal(guard):
    """Equal-score candidates fall back to discovery order (depth, then seq)."""
    pages = {
        SEED: (
            "<html><body><main><h1>H</h1><p>home</p>"
            '<a href="/a/x">A</a><a href="/b/y">B</a></main></body></html>'
        ),
        "https://docs.acme.example/a/x": _content_page("AX", "a x content"),
        "https://docs.acme.example/b/y": _content_page("BY", "b y content"),
    }
    fetcher = FakePageFetcher(pages)
    session = _session(fetcher, guard)
    await session.run()
    urls = [d.url for d in session._documents.documents.values()]
    # /a/x discovered before /b/y => stays ordered when scores tie.
    assert urls.index("https://docs.acme.example/a/x") < urls.index("https://docs.acme.example/b/y")


async def test_no_duplicate_urls(guard):
    pages = {
        SEED: (
            "<html><body><main><h1>H</h1><p>home</p>"
            '<a href="/docs/leaf?utm_source=ad#f">Leaf</a>'
            '<a href="/docs/leaf">Leaf2</a></main></body></html>'
        ),
        "https://docs.acme.example/docs/leaf": _content_page("Leaf", "leaf body"),
    }
    fetcher = FakePageFetcher(pages)
    session = _session(fetcher, guard)
    stored = await session.run()
    urls = [d.url for d in session._documents.documents.values()]
    assert stored == len(urls) == 2
    assert len({u for u in urls}) == len(urls)


def _settings_with(*, max_pages: int | None = None, max_depth: int | None = None):
    from backend.core.config import Settings

    values: dict = {"environment": "test"}
    if max_pages is not None:
        values["crawl_max_pages"] = max_pages
    if max_depth is not None:
        values["crawl_max_depth"] = max_depth
    return Settings(_env_file=None, **values)
