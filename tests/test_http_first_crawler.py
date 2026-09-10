"""Tests for the HTTP-first hybrid crawler (1 GiB worker plan).

Exercise: plain-HTTP pages never launch Chromium; JS-shell pages fall back per
URL; non-HTML/error/timeout responses fail without Chromium; redirects, size
caps and content sniffing are honoured; the production default picks the hybrid
fetcher; and the end-to-end crawl (robots + depth + priority) still behaves.
"""

import asyncio
from collections.abc import AsyncIterator, Callable

import httpx
import pytest
from backend.core.config import Settings
from backend.services.ingestion import (
    CrawlSession,
    FetchError,
    HttpContentVerdict,
    HybridPageFetcher,
    SsrFGuard,
    extract_http_content,
    fetch_http_page,
    judge_http_content,
)
from backend.services.ingestion.crawler import FetchedPage
from backend.services.ingestion.http_first import BrowserPageFetcher

from tests.crawl_helpers import FakePageFetcher
from tests.fakes import FakeDocumentRepository

SEED = "https://acme.example/"
MIN_CHARS = 100
MIN_WORDS = 12
SHELL_MIN_BYTES = 8000


@pytest.fixture
def guard(monkeypatch):
    g = SsrFGuard()

    async def fake_resolve(host: str) -> list[str]:
        return ["93.184.216.34"]

    monkeypatch.setattr(g, "resolve_async", fake_resolve)
    return g


def _pad_comment(html: str) -> str:
    spacer = "<!--" + ("x" * (SHELL_MIN_BYTES - len(html))) + "-->"
    return html.replace("</head>", spacer + "</head>")


def _mock_client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _html(body: str, *, title: str = "Docs", lang: str = "en") -> str:
    return (
        f"<!doctype html><html lang='{lang}'><head><title>{title}</title></head>"
        f"<body><main>{body}</main></body></html>"
    )


SSR_PAGE = _html(
    "<h1>Our product</h1><p>" + ("Product documentation " * 400) + "</p><a href='/guide'>Guide</a>"
)
GUIDE_PAGE = _html("<h1>Guide</h1><p>" + ("Step by step " * 40) + "</p>")
PRICING_PAGE = _html("<h1>Pricing</h1><p>" + ("Plans and prices " * 40) + "</p>")
JS_SHELL_PAGE = _pad_comment(
    _html(
        "<div id='root'></div><noscript>This site requires JavaScript to run.</noscript>",
        title="App",
    )
)
NOSCRIPT_ONLY_PAGE = _pad_comment(
    _html("<noscript>Please enable JavaScript to view this page.</noscript>", title="App")
)
REACT_NAMED_PAGE = _html(
    "<h1>Welcome</h1><p>" + ("Real content " * 40) + "</p><script src='react.js'></script>"
)
THIN_PAGE = _html("<div id='root'></div>")
NEXT_SHELL_PAGE = _pad_comment(_html("<div id='__next'></div>", title="App"))
NUXT_SHELL_PAGE = _pad_comment(_html("<div id='__nuxt'></div>", title="App"))
APP_MOUNT_SHELL_PAGE = _pad_comment(_html("<div id='app-mount'></div>", title="App"))
SHELL_MOUNTED_SSR_PAGE = _pad_comment(
    _html("<div id='__next'><p>" + ("Fully rendered server content " * 30) + "</p></div>")
)
PLACEHOLDER_CHROME_PAGE = _pad_comment(
    _html("<div id='app'><p>" + ("Loading... " * 10) + "</p></div>", title="App")
)


def _judge(page: str) -> HttpContentVerdict:
    return judge_http_content(
        page,
        min_content_chars=MIN_CHARS,
        min_content_words=MIN_WORDS,
        js_shell_min_bytes=SHELL_MIN_BYTES,
    )


# --------------------------------------------------------------------------
# judge_http_content
# --------------------------------------------------------------------------


def test_static_ssr_page_is_sufficient() -> None:
    assert _judge(SSR_PAGE) is HttpContentVerdict.SUFFICIENT


def test_framework_fingerprint_alone_never_triggers_fallback() -> None:
    assert _judge(REACT_NAMED_PAGE) is HttpContentVerdict.SUFFICIENT


def test_js_shell_with_root_container_requires_fallback() -> None:
    assert _judge(JS_SHELL_PAGE) is HttpContentVerdict.JS_REQUIRED


def test_js_required_noscript_message_triggers_fallback() -> None:
    assert _judge(NOSCRIPT_ONLY_PAGE) is HttpContentVerdict.JS_REQUIRED


def test_small_page_never_falls_back_even_with_shell_marker() -> None:
    assert _judge(THIN_PAGE) is HttpContentVerdict.SUFFICIENT


def test_shell_marker_with_real_content_stays_http() -> None:
    page = _pad_comment(_html("<div id='root'><p>" + ("Fully rendered text " * 30) + "</p></div>"))
    assert _judge(page) is HttpContentVerdict.SUFFICIENT


def test_next_js_shell_requires_fallback() -> None:
    assert _judge(NEXT_SHELL_PAGE) is HttpContentVerdict.JS_REQUIRED


def test_nuxt_shell_requires_fallback() -> None:
    assert _judge(NUXT_SHELL_PAGE) is HttpContentVerdict.JS_REQUIRED


def test_app_mount_shell_requires_fallback() -> None:
    assert _judge(APP_MOUNT_SHELL_PAGE) is HttpContentVerdict.JS_REQUIRED


def test_next_ssr_page_with_real_content_never_falls_back() -> None:
    assert _judge(SHELL_MOUNTED_SSR_PAGE) is HttpContentVerdict.SUFFICIENT


def test_placeholder_chrome_races_never_falls_back_as_content() -> None:
    assert _judge(PLACEHOLDER_CHROME_PAGE) is HttpContentVerdict.JS_REQUIRED


# --------------------------------------------------------------------------
# fetch_http_page
# --------------------------------------------------------------------------


async def test_fetch_returns_static_html(guard) -> None:
    client = _mock_client(
        lambda request: httpx.Response(
            200, content=SSR_PAGE.encode(), headers={"Content-Type": "text/html"}
        )
    )
    result = await fetch_http_page(
        SEED,
        client=client,
        guard=guard,
        max_html_bytes=5_000_000,
        min_content_chars=MIN_CHARS,
        min_content_words=MIN_WORDS,
        js_shell_min_bytes=SHELL_MIN_BYTES,
    )
    await client.aclose()
    assert result.final_url == SEED
    assert result.status_code == 200
    assert result.verdict is HttpContentVerdict.SUFFICIENT
    assert "Product documentation" in result.html


async def test_follows_redirects_and_tracks_final_url(guard) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return httpx.Response(302, headers={"Location": "/home"})
        return httpx.Response(200, content=SSR_PAGE.encode(), headers={"Content-Type": "text/html"})

    client = _mock_client(handler)
    result = await fetch_http_page(
        "https://acme.example/",
        client=client,
        guard=guard,
        max_html_bytes=5_000_000,
        min_content_chars=MIN_CHARS,
        min_content_words=MIN_WORDS,
        js_shell_min_bytes=SHELL_MIN_BYTES,
    )
    await client.aclose()
    assert result.final_url == "https://acme.example/home"
    assert "Product documentation" in result.html


async def test_redirect_loop_raises_fetch_error(guard) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": request.url.path})

    client = _mock_client(handler)
    with pytest.raises(FetchError, match="Too many redirects"):
        await fetch_http_page(
            SEED,
            client=client,
            guard=guard,
            max_html_bytes=5_000_000,
            min_content_chars=MIN_CHARS,
            min_content_words=MIN_WORDS,
            js_shell_min_bytes=SHELL_MIN_BYTES,
        )
    await client.aclose()


async def test_redirect_chain_of_20_succeeds(guard) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/20":
            return httpx.Response(
                200, content=SSR_PAGE.encode(), headers={"Content-Type": "text/html"}
            )
        return httpx.Response(302, headers={"Location": f"/{int(request.url.path[1:]) + 1}"})

    client = _mock_client(handler)
    result = await fetch_http_page(
        "https://acme.example/0",
        client=client,
        guard=guard,
        max_html_bytes=5_000_000,
        min_content_chars=MIN_CHARS,
        min_content_words=MIN_WORDS,
        js_shell_min_bytes=SHELL_MIN_BYTES,
    )
    await client.aclose()
    assert result.final_url == "https://acme.example/20"
    assert result.verdict is HttpContentVerdict.SUFFICIENT
    assert "Product documentation" in result.html


async def test_redirect_chain_of_21_raises(guard) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": f"/{int(request.url.path[1:]) + 1}"})

    client = _mock_client(handler)
    with pytest.raises(FetchError, match="Too many redirects"):
        await fetch_http_page(
            "https://acme.example/0",
            client=client,
            guard=guard,
            max_html_bytes=5_000_000,
            min_content_chars=MIN_CHARS,
            min_content_words=MIN_WORDS,
            js_shell_min_bytes=SHELL_MIN_BYTES,
        )
    await client.aclose()


async def test_http_error_raises_fetch_error(guard) -> None:
    client = _mock_client(lambda request: httpx.Response(404))
    with pytest.raises(FetchError, match="HTTP 404"):
        await fetch_http_page(SEED, client=client, guard=guard, max_html_bytes=5_000_000)
    await client.aclose()


async def test_non_html_content_is_rejected(guard) -> None:
    client = _mock_client(
        lambda request: httpx.Response(
            200, content=b"%PDF-1.4", headers={"Content-Type": "application/pdf"}
        )
    )
    with pytest.raises(FetchError, match="Unsupported content type"):
        await fetch_http_page(SEED, client=client, guard=guard, max_html_bytes=5_000_000)
    await client.aclose()


async def test_binary_octet_stream_without_markup_is_rejected(guard) -> None:
    client = _mock_client(
        lambda request: httpx.Response(
            200, content=b"\x89PNG\r\n", headers={"Content-Type": "application/octet-stream"}
        )
    )
    with pytest.raises(FetchError, match="Unsupported content type"):
        await fetch_http_page(SEED, client=client, guard=guard, max_html_bytes=5_000_000)
    await client.aclose()


async def test_response_body_truncated_at_cap(guard) -> None:
    body = _html("<p>" + ("word " * 2000) + "</p>")
    client = _mock_client(
        lambda request: httpx.Response(
            200, content=body.encode(), headers={"Content-Type": "text/html"}
        )
    )
    result = await fetch_http_page(SEED, client=client, guard=guard, max_html_bytes=500)
    await client.aclose()
    assert len(result.html) <= 500


async def test_respects_declared_charset(guard) -> None:
    body = "<html><body><p>caf\xe9</p></body></html>"
    client = _mock_client(
        lambda request: httpx.Response(
            200,
            content=body.encode("latin-1"),
            headers={"Content-Type": "text/html; charset=iso-8859-1"},
        )
    )
    result = await fetch_http_page(SEED, client=client, guard=guard, max_html_bytes=5_000_000)
    await client.aclose()
    assert "café" in result.html


async def test_meta_charset_is_honoured(guard) -> None:
    body = "<html><head><meta charset='iso-8859-1'></head><body><p>caf\xe9</p></body></html>"
    client = _mock_client(
        lambda request: httpx.Response(
            200,
            content=body.encode("latin-1"),
            headers={"Content-Type": "text/html"},
        )
    )
    result = await fetch_http_page(SEED, client=client, guard=guard, max_html_bytes=5_000_000)
    await client.aclose()
    assert "café" in result.html


async def test_missing_charset_falls_back_to_utf8(guard) -> None:
    body = "<html><body><p>café</p></body></html>"
    client = _mock_client(
        lambda request: httpx.Response(
            200,
            content=body.encode("utf-8"),
            headers={"Content-Type": "text/html"},
        )
    )
    result = await fetch_http_page(SEED, client=client, guard=guard, max_html_bytes=5_000_000)
    await client.aclose()
    assert "café" in result.html


async def test_utf8_bom_is_stripped(guard) -> None:
    body = "\ufeff<html><body><p>café</p></body></html>".encode("utf-8")
    client = _mock_client(
        lambda request: httpx.Response(
            200,
            content=body,
            headers={"Content-Type": "text/html"},
        )
    )
    result = await fetch_http_page(SEED, client=client, guard=guard, max_html_bytes=5_000_000)
    await client.aclose()
    assert "café" in result.html
    assert "\ufeff" not in result.html


async def test_slow_drip_body_fails_by_wall_clock_deadline(guard) -> None:
    class DripStream(httpx.AsyncByteStream):
        def __init__(self) -> None:
            self._gen = self._drip()

        async def _drip(self) -> AsyncIterator[bytes]:
            while True:
                await asyncio.sleep(0.05)
                yield b"<p>drip</p>"

        def __aiter__(self) -> AsyncIterator[bytes]:
            return self._gen.__aiter__()

        async def aclose(self) -> None:
            await self._gen.aclose()

    client = _mock_client(
        lambda request: httpx.Response(
            200, stream=DripStream(), headers={"Content-Type": "text/html"}
        )
    )
    with pytest.raises(FetchError, match="Timed out loading"):
        await fetch_http_page(
            SEED,
            client=client,
            guard=guard,
            max_html_bytes=5_000_000,
            overall_timeout_seconds=0.01,
        )
    await client.aclose()


# --------------------------------------------------------------------------
# extract_http_content
# --------------------------------------------------------------------------


def test_extract_http_content_normalizes_links() -> None:
    html = _html(
        "<p>Hello.</p>"
        "<a href='/about?utm_source=ad#frag'>About</a>"
        "<a href='https://acme.example/pricing'>Pricing</a>",
        title="Acme",
    )
    extracted = extract_http_content(html, SEED)
    assert extracted.title == "Acme"
    assert "https://acme.example/about" in extracted.links
    assert "https://acme.example/pricing" in extracted.links
    assert extracted.text_length > 0
    assert "https://acme.example/about?utm_source=ad#frag" not in extracted.links


# --------------------------------------------------------------------------
# HybridPageFetcher
# --------------------------------------------------------------------------


def _never_browser() -> None:
    raise AssertionError("Chromium must not be launched for static pages.")


async def _hybrid(guard, handler, monkeypatch) -> tuple[HybridPageFetcher, httpx.AsyncClient]:
    monkeypatch.setattr("backend.services.ingestion.browser.get_browser", _never_browser)
    client = _mock_client(handler)
    fetcher = HybridPageFetcher(guard=guard, http_client_factory=lambda: client)
    return fetcher, client


async def test_static_pages_never_touch_chromium(guard, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        page = PRICING_PAGE if request.url.path == "/pricing" else SSR_PAGE
        return httpx.Response(200, content=page.encode(), headers={"Content-Type": "text/html"})

    fetcher, _ = await _hybrid(guard, handler, monkeypatch)
    first = await fetcher.fetch(SEED)
    second = await fetcher.fetch("https://acme.example/pricing")
    await fetcher.close()
    assert "Product documentation" in first.html
    assert "Plans and prices" in second.html
    assert fetcher._browser_fetcher is None


async def test_one_js_page_only_falls_back_for_that_url(guard, monkeypatch) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = JS_SHELL_PAGE if request.url.path == "/" else GUIDE_PAGE
        return httpx.Response(200, content=page.encode(), headers={"Content-Type": "text/html"})

    class FakeBrowser:
        closed = False

        async def fetch(self, url: str) -> FetchedPage:
            calls.append(url)
            return FetchedPage(url=url, html=GUIDE_PAGE)

        async def close(self) -> None:
            self.closed = True

    monkeypatch.setattr("backend.services.ingestion.browser.get_browser", _never_browser)
    client = _mock_client(handler)
    fetcher = HybridPageFetcher(guard=guard, http_client_factory=lambda: client)
    browser = FakeBrowser()
    monkeypatch.setattr(
        "backend.services.ingestion.http_first.BrowserPageFetcher",
        lambda *, guard: browser,
    )

    shell_page = await fetcher.fetch(SEED)
    static_page = await fetcher.fetch("https://acme.example/about")
    await fetcher.close()

    assert calls == [SEED]
    assert shell_page.url == SEED
    assert "Step by step" in static_page.html
    assert browser.closed is True


async def test_fetch_failure_does_not_launch_chromium(guard, monkeypatch) -> None:
    monkeypatch.setattr("backend.services.ingestion.browser.get_browser", _never_browser)
    client = _mock_client(lambda request: httpx.Response(500))
    fetcher = HybridPageFetcher(guard=guard, http_client_factory=lambda: client)
    with pytest.raises(FetchError, match="HTTP 500"):
        await fetcher.fetch(SEED)
    await fetcher.close()
    assert fetcher._browser_fetcher is None


# --------------------------------------------------------------------------
# Production fetcher selection (worker wiring)
# --------------------------------------------------------------------------


def test_worker_defaults_to_hybrid_fetcher(guard, monkeypatch) -> None:
    from backend.workers.jobs.crawl import _make_page_fetcher

    class StubSettings:
        crawl_http_first = True

    monkeypatch.setattr("backend.workers.jobs.crawl.get_settings", lambda: StubSettings())
    fetcher = _make_page_fetcher({}, guard)
    assert isinstance(fetcher, HybridPageFetcher)
    assert isinstance(fetcher, BrowserPageFetcher) is False
    assert isinstance(fetcher, FakePageFetcher) is False


def test_worker_falls_back_to_browser_fetcher_when_disabled(guard, monkeypatch) -> None:
    from backend.workers.jobs.crawl import _make_page_fetcher

    class StubSettings:
        crawl_http_first = False

    monkeypatch.setattr("backend.workers.jobs.crawl.get_settings", lambda: StubSettings())
    fetcher = _make_page_fetcher({}, guard)
    assert isinstance(fetcher, BrowserPageFetcher)


def test_injected_fetcher_always_wins(guard, monkeypatch) -> None:
    from backend.workers.jobs.crawl import _make_page_fetcher

    fake = FakePageFetcher({SEED: SSR_PAGE})
    assert _make_page_fetcher({"crawler_fetcher": fake}, guard) is fake


# --------------------------------------------------------------------------
# End-to-end crawl through the hybrid fetcher
# --------------------------------------------------------------------------


def _crawl_settings(**overrides) -> Settings:
    values = {"environment": "test", "crawl_max_pages": 10, "crawl_max_depth": 2}
    values.update(overrides)
    return Settings(_env_file=None, **values)


async def test_crawl_session_honours_robots_depth_and_static_extraction(guard, monkeypatch) -> None:
    requested: list[str] = []

    ABOUT_PAGE = _html("<h1>About</h1><p>" + ("About text " * 40) + "</p>")
    SEED_PAGE = _html(
        "<h1>Acme</h1><p>" + ("Welcome text " * 40) + "</p>"
        "<a href='/guide'>Guide</a><a href='/about'>About</a><a href='/private'>Private</a>"
    )
    GALLERY_PAGE = _html(
        "<h1>Gallery</h1><p>" + ("Gallery text " * 40) + "</p>"
        "<a href='/deep'>Deep</a><a href='/private'>Private</a>"
    )
    GUIDE_PAGE = _html(
        "<h1>Guide</h1><p>" + ("Step by step " * 40) + "</p><a href='/gallery'>Gallery</a>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200,
                content="User-agent: *\nDisallow: /private\n",
                headers={"Content-Type": "text/plain"},
            )
        if request.url.path == "/":
            return httpx.Response(
                200, content=SEED_PAGE.encode(), headers={"Content-Type": "text/html"}
            )
        if request.url.path == "/guide":
            return httpx.Response(
                200, content=GUIDE_PAGE.encode(), headers={"Content-Type": "text/html"}
            )
        if request.url.path == "/about":
            return httpx.Response(
                200, content=ABOUT_PAGE.encode(), headers={"Content-Type": "text/html"}
            )
        if request.url.path == "/gallery":
            return httpx.Response(
                200, content=GALLERY_PAGE.encode(), headers={"Content-Type": "text/html"}
            )
        if request.url.path == "/pricing":
            return httpx.Response(
                200, content=PRICING_PAGE.encode(), headers={"Content-Type": "text/html"}
            )
        if request.url.path == "/deep":
            return httpx.Response(
                200, content=GUIDE_PAGE.encode(), headers={"Content-Type": "text/html"}
            )
        return httpx.Response(404)

    monkeypatch.setattr("backend.services.ingestion.browser.get_browser", _never_browser)
    client = _mock_client(handler)
    fetcher = HybridPageFetcher(guard=guard, http_client_factory=lambda: client)
    documents = FakeDocumentRepository()
    session = CrawlSession(
        tenant_id="tenant-a",
        website_id="website-a",
        seed_url=SEED,
        fetcher=fetcher,
        documents=documents,
        guard=guard,
        settings=_crawl_settings(
            crawl_priority_url_paths=["/pricing"],
            crawl_max_depth=2,
        ),
    )
    stored = await session.run()
    await client.aclose()

    assert stored == 5
    assert {doc.url for doc in documents.documents.values()} == {
        SEED,
        "https://acme.example/guide",
        "https://acme.example/about",
        "https://acme.example/gallery",
        "https://acme.example/pricing",
    }
    assert "/private" not in requested
    assert "/deep" not in requested
