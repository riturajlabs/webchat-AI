"""Playwright headless-Chromium lifecycle for the ARQ crawler (ADR-002).

One browser is launched per worker process and reused across crawl jobs via
isolated browser contexts (the crawler owns one context per job and closes it
in a `finally`). A semaphore bounds how many jobs can hold an open page at once
so `max_jobs` never translates into N Chromium instances (memory safety).
"""

import asyncio
from typing import Any

from playwright.async_api import Browser, BrowserContext, async_playwright

from backend.core.config import get_settings
from backend.services.ingestion.crawler import FetchedPage, FetchError
from backend.services.ingestion.ssrf_guard import SsrFGuard

_playwright: Any = None
_browser: Browser | None = None
_semaphore: asyncio.Semaphore | None = None


def crawl_semaphore() -> asyncio.Semaphore:
    """Semaphore limiting concurrent in-flight crawl jobs (per process)."""
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(get_settings().crawl_max_concurrent)
    return _semaphore


async def get_browser() -> Browser:
    """Return the shared headless Chromium instance (lazily launched)."""
    global _playwright, _browser
    if _browser is not None and _browser.is_connected():
        return _browser
    settings = get_settings()
    args = ["--disable-dev-shm-usage"]
    if settings.crawl_no_sandbox:
        args.append("--no-sandbox")
    _playwright = await async_playwright().start()
    _browser = await _playwright.chromium.launch(headless=True, args=args)
    return _browser


async def close_browser() -> None:
    """Tear down the shared browser (called on worker shutdown)."""
    global _playwright, _browser
    if _browser is not None:
        await _browser.close()
        _browser = None
    if _playwright is not None:
        await _playwright.stop()
        _playwright = None


class BrowserPageFetcher:
    """`PageFetcher` backed by headless Chromium (one context per crawl job).

    Every navigation, sub-resource and redirect hop is routed through the
    `SsrFGuard`: non-http(s) and SSRF-unsafe requests are aborted before the
    browser connects (ADR-008).
    """

    def __init__(
        self,
        *,
        guard: SsrFGuard,
        user_agent: str | None = None,
        timeout_ms: int | None = None,
        max_html_bytes: int | None = None,
    ) -> None:
        self._guard = guard
        self._user_agent = user_agent or get_settings().crawl_browser_user_agent
        self._timeout_ms = timeout_ms or get_settings().crawl_navigation_timeout_ms
        self._max_html_bytes = max_html_bytes or get_settings().crawl_max_html_bytes
        self._context: BrowserContext | None = None

    async def fetch(self, url: str) -> FetchedPage:
        await self._guard.validate_async(url)
        context = await self._ensure_context()
        page = await context.new_page()
        try:
            await self._install_route_guard(page)
            response = await page.goto(url, wait_until="domcontentloaded", timeout=self._timeout_ms)
            if response is None:
                raise FetchError(f"No response for {url}.")
            if response.status >= 400:
                raise FetchError(f"HTTP {response.status} for {url}.")
            # Response size limit: cap the serialized DOM so a pathological page
            # never floods the worker's memory (docs/06, Phase 4 resource limits).
            html = await page.content()
            if len(html) > self._max_html_bytes:
                html = html[: self._max_html_bytes]
            return FetchedPage(url=page.url, html=html)
        except FetchError:
            raise
        except Exception as exc:  # Playwright failures (timeout, net::ERR_*)
            raise FetchError(f"Could not load {url}: {type(exc).__name__}") from exc
        finally:
            await page.close()

    async def close(self) -> None:
        if self._context is not None:
            await self._context.close()
            self._context = None

    # ------------------------------------------------------------ internals

    async def _ensure_context(self) -> BrowserContext:
        if self._context is None:
            browser = await get_browser()
            self._context = await browser.new_context(
                user_agent=self._user_agent,
                viewport={"width": 1280, "height": 900},
                java_script_enabled=True,
            )
        return self._context

    async def _install_route_guard(self, page: Any) -> None:
        async def on_route(route: Any) -> None:
            target = route.request.url
            if not target.startswith(("http://", "https://")):
                await route.abort()
                return
            try:
                await self._guard.validate_async(target)
            except Exception:
                await route.abort()
                return
            try:
                await route.continue_()
            except Exception:
                # The page may already be closed mid-navigation.
                return

        await page.route("**/*", on_route)
