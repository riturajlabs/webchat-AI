"""Playwright headless-Chromium lifecycle for the ARQ crawler (ADR-002).

One browser is launched per worker process and reused across crawl jobs via
isolated browser contexts (the crawler owns one context per job and closes it
in a `finally`). A semaphore bounds how many jobs can hold an open page at once
so `max_jobs` never translates into N Chromium instances (memory safety).
"""

import asyncio
import logging
from typing import Any

from playwright.async_api import Browser, BrowserContext, async_playwright

from backend.core.config import get_settings
from backend.core.errors import InvalidUrlError
from backend.core.metrics import record_crawl_fetch_failure
from backend.services.ingestion.crawl_failure import (
    CrawlFailureClassification,
    classify_http_status,
    classify_network_error,
    safe_url_parts,
)
from backend.services.ingestion.crawler import FetchedPage, FetchError
from backend.services.ingestion.ssrf_guard import SsrFGuard

logger = logging.getLogger("webchat_ai")

_playwright: Any = None
_browser: Browser | None = None
_semaphore: asyncio.Semaphore | None = None
# ARCH-02: the lazy browser launch is racy without a lock - two coroutines
# seeing `_browser is None` would each start a separate Chromium process.
_launch_lock: asyncio.Lock | None = None


def _browser_lock() -> asyncio.Lock:
    global _launch_lock
    if _launch_lock is None:
        _launch_lock = asyncio.Lock()
    return _launch_lock


def crawl_semaphore() -> asyncio.Semaphore:
    """Semaphore limiting concurrent in-flight crawl jobs (per process)."""
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(get_settings().crawl_max_concurrent)
    return _semaphore


async def get_browser() -> Browser:
    """Return the shared headless Chromium instance (lazily launched).

    The launch is serialized with an ``asyncio.Lock`` (ARCH-02) so concurrent
    first callers share one browser instead of each starting their own.
    """
    global _playwright, _browser
    if _browser is not None and _browser.is_connected():
        return _browser
    async with _browser_lock():
        # Double-checked: while we waited for the lock another coroutine may
        # have completed the launch.
        if _browser is not None and _browser.is_connected():
            return _browser
        settings = get_settings()
        args = ["--disable-dev-shm-usage"]
        if settings.crawl_no_sandbox:
            args.append("--no-sandbox")
        logger.info(
            "crawl_browser_launch no_sandbox=%s browser_args=%s",
            settings.crawl_no_sandbox,
            args,
        )
        _playwright = await async_playwright().start()
        try:
            _browser = await _playwright.chromium.launch(headless=True, args=args)
        except Exception as exc:  # noqa: BLE001 - surfaces the real launch error
            logger.warning(
                "crawl_browser_launch_failed error_type=%s error=%s",
                type(exc).__name__,
                exc,
            )
            raise
        logger.info("crawl_browser_launch_success")
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
        logger.info("crawl_browser_fetch_start url=%s", url)
        # Egress hardening (Phase 3): browser-setup failures (launch, context,
        # new_page) are classified separately from target HTTP failures so a
        # worker/Chromium problem never masquerades as a hostile website.
        try:
            context = await self._ensure_context()
            page = await context.new_page()
        except (FetchError, InvalidUrlError):
            raise
        except Exception as exc:  # Playwright launch/context failures
            message = f"Could not load {url}: {type(exc).__name__}: {exc}"
            logger.warning(
                "crawl_browser_launch_failed url=%s error_type=%s error=%s",
                url,
                type(exc).__name__,
                exc,
            )
            record_crawl_fetch_failure(
                classification=CrawlFailureClassification.BROWSER_LAUNCH_FAILURE.value,
                method="browser",
            )
            raise FetchError(
                message,
                classification=CrawlFailureClassification.BROWSER_LAUNCH_FAILURE.value,
                method="browser",
            ) from exc
        try:
            await self._install_route_guard(page)
            logger.info("crawl_browser_navigation url=%s", url)
            response = await page.goto(url, wait_until="domcontentloaded", timeout=self._timeout_ms)
            if response is None:
                raise FetchError(
                    f"No response for {url}.",
                    classification=CrawlFailureClassification.RETRYABLE_NETWORK_ERROR.value,
                    method="browser",
                )
            if response.status >= 400:
                http_error_host, http_error_path = safe_url_parts(url)
                logger.warning(
                    "crawl_browser_http_error hostname=%s path=%s status=%d",
                    http_error_host,
                    http_error_path,
                    response.status,
                )
                record_crawl_fetch_failure(
                    classification=classify_http_status(response.status).value,
                    status_code=response.status,
                    method="browser",
                )
                raise FetchError(
                    f"HTTP {response.status} for {url}.",
                    classification=classify_http_status(response.status).value,
                    status_code=response.status,
                    method="browser",
                )
            # Response size limit: cap the serialized DOM so a pathological page
            # never floods the worker's memory (docs/06, Phase 4 resource limits).
            html = await page.content()
            if len(html) > self._max_html_bytes:
                html = html[: self._max_html_bytes]
            logger.info(
                "crawl_browser_success url=%s final_url=%s html_bytes=%d",
                url,
                page.url,
                len(html),
            )
            return FetchedPage(url=page.url, html=html)
        except FetchError:
            raise
        except InvalidUrlError:
            raise
        except Exception as exc:  # navigation/content failures (timeout, net::ERR_*)
            message = f"Could not load {url}: {type(exc).__name__}: {exc}"
            logger.warning(
                "crawl_browser_failure url=%s error_type=%s error=%s",
                url,
                type(exc).__name__,
                exc,
            )
            classification = classify_network_error(exc)
            record_crawl_fetch_failure(
                classification=classification.value,
                method="browser",
            )
            raise FetchError(
                message,
                classification=classification.value,
                method="browser",
            ) from exc
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
