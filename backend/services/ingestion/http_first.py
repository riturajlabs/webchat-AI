"""HTTP-first page fetch with headless-Chromium fallback (1 GiB worker plan).

Most public pages are served as static HTML, so the crawler can extract
documents without ever loading the heavyweight Playwright stack (one browser
plus one context per crawl job is several hundred MiB resident). This module
provides a plain `httpx`/BeautifulSoup fetch path plus a conservative JS
detector: only pages that are large and lack meaningful cleaned text *and*
carry explicit shell markers (an application-root container or a "enable
JavaScript" noscript notice) are re-fetched through headless Chromium.

The `HybridPageFetcher` satisfies the crawler's `PageFetcher` protocol and is
the production default (`CRAWL_HTTP_FIRST=true`); Chromium objects are created
lazily on the first JS-required page and always released in `close()`.
"""

import asyncio
import codecs
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from urllib.parse import urljoin

import httpx

from backend.core.config import Settings, get_settings
from backend.core.metrics import record_crawl_fetch_failure
from backend.services.ingestion.browser import BrowserPageFetcher
from backend.services.ingestion.cleaner import clean_html
from backend.services.ingestion.crawl_failure import (
    CrawlFailureClassification,
    classify_http_status,
    classify_network_error,
    is_http_recoverable,
    safe_url_parts,
)
from backend.services.ingestion.crawler import FetchedPage, FetchError
from backend.services.ingestion.extractor import extract_page
from backend.services.ingestion.ssrf_guard import SsrFGuard

logger = logging.getLogger("webchat_ai")

# Chromium/Playwright abort navigation after 20 redirects; we follow the same
# policy so sites with long legitimate chains behave as they did on the old
# browser path.
_MAX_REDIRECTS = 20
_REDIRECT_CODES = (301, 302, 303, 307, 308)

# Classifications that may be retried over HTTP (bounded) before the browser
# fallback; 403 is deliberately missing (Phase 3, TRD).
_HTTP_RETRYABLE = frozenset(
    {
        CrawlFailureClassification.TARGET_RATE_LIMITED.value,
        CrawlFailureClassification.TARGET_SERVER_ERROR.value,
        CrawlFailureClassification.RETRYABLE_NETWORK_ERROR.value,
        CrawlFailureClassification.CRAWL_TIMEOUT.value,
    }
)

_HTML_MEDIA_TYPES = frozenset({"text/html", "application/xhtml+xml"})
# Sitemaps, robots.txt and plain-text listings are fetched (robots.txt must be
# followed; XML sitemaps were accepted by the browser path too).
_ACCEPT_MEDIA_TYPES = frozenset({"text/plain", "text/xml", "application/xml"})

_ACCEPT_HEADER = "text/html,application/xhtml+xml,text/plain;q=0.9"

# A JS shell exposes an empty application-root element whose id is one of these
# names (plain old roots plus the common Next.js/Nuxt/VueMount conventions).
_SHELL_ID_RE = re.compile(
    r"<[a-z][^>]*\bid\s*=\s*[\"']"
    r"(?:__next|__nuxt|app-mount|application-root|app-root|app-shell|root|app)[\"']",
    re.IGNORECASE,
)

_NOSCRIPT_BLOCK_RE = re.compile(r"<noscript[^>]*>(.*?)</noscript>", re.IGNORECASE | re.DOTALL)
# Explicit "this site needs JavaScript" messaging, not framework fingerprints.
_JS_REQUIRED_PHRASE_RE = re.compile(
    r"(?:requires?|needs?|must\s+be\s+enabled|enable|is\s+disabled|no\s+javascript)"
    r"[^a-z]{0,12}javascript"
    r"|javascript[^a-z]{0,20}(?:must\s+be\s+enabled|required|is\s+required|is\s+disabled)",
    re.IGNORECASE,
)

_HTTP_CHARSET_RE = re.compile(r"charset\s*=\s*[\"']?([\w.-]+)", re.IGNORECASE)
_META_CHARSET_RE = re.compile(
    r"<meta[^>]*\bcharset\s*=\s*[\"']?([\w.-]+)"
    r"|<meta[^>]*\bhttp-equiv\s*=\s*[\"']?content-type[\"']?[^>]*\bcontent\s*=\s*[\"'][^\"']*"
    r"\bcharset=([\w.-]+)",
    re.IGNORECASE,
)

_WORD_RE = re.compile(r"\b\w{2,}\b")


class HttpContentVerdict(Enum):
    """Whether a plain-HTTP response already carries usable content."""

    SUFFICIENT = "sufficient"
    JS_REQUIRED = "js_required"


@dataclass(frozen=True)
class HTTPFetchResult:
    """A fetched HTTP response plus its content verdict."""

    final_url: str
    html: str
    content_type: str | None
    status_code: int
    verdict: HttpContentVerdict


@dataclass(frozen=True)
class ExtractionResult:
    """Structured view of an HTTP-fetched page (text + extractor fields)."""

    url: str
    title: str
    language: str
    meta: dict[str, str]
    canonical: str | None
    headings: list[str]
    paragraphs: list[str]
    links: list[str]
    text: str
    text_length: int


def _charset_from_content_type(content_type: str) -> str | None:
    """Return the charset declared in the HTTP `Content-Type` header, if any."""
    match = _HTTP_CHARSET_RE.search(content_type)
    return match.group(1) if match else None


def _charset_from_bom(raw: bytes) -> str | None:
    """Return an encoding implied by a byte-order mark, if present."""
    for bom, encoding in (
        (codecs.BOM_UTF8, "utf-8-sig"),
        (codecs.BOM_UTF32_LE, "utf-32"),
        (codecs.BOM_UTF32_BE, "utf-32"),
        (codecs.BOM_UTF16_LE, "utf-16"),
        (codecs.BOM_UTF16_BE, "utf-16"),
    ):
        if raw.startswith(bom):
            return encoding
    return None


def _charset_from_html(raw: bytes) -> str | None:
    """Return the charset declared in the document's `<meta>` tags, if any."""
    head = raw[:4096].decode("latin-1", errors="replace")
    match = _META_CHARSET_RE.search(head)
    if match is None:
        return None
    return match.group(1) or match.group(2)


def _decode_html(raw: bytes, content_type: str) -> str:
    """Decode raw bytes to text, preferring the least-ambiguous source.

    Resolution order: BOM > HTTP Content-Type charset > HTML `<meta>` charset >
    UTF-8. Declared names are canonicalized with ``codecs.lookup`` so aliases
    (``iso-8859-1``, ``utf8``, ...) work; unknown or malformed names fall back
    to UTF-8. Normal UTF-8 responses decode exactly as before.
    """
    name = (
        _charset_from_bom(raw)
        or _charset_from_content_type(content_type)
        or _charset_from_html(raw)
    )
    try:
        encoding = codecs.lookup(name).name if name else "utf-8"
    except LookupError:
        encoding = "utf-8"
    return raw.decode(encoding, errors="replace")


def _accepted_media(media: str, html: str) -> bool:
    """True when `media` (lowercased) is worth storing instead of rejecting."""
    if media in _HTML_MEDIA_TYPES or media in _ACCEPT_MEDIA_TYPES:
        return True
    if media.startswith("text/"):
        return True
    # Missing/opaque content types are sniffed: only markup-looking bodies are
    # accepted so binary downloads never reach the extractor.
    if media in {"", "application/octet-stream"}:
        return html.lstrip().startswith("<")
    return False


def _noscript_js_required(html: str) -> bool:
    """True when a <noscript> block explicitly says JavaScript is required."""
    return any(
        _JS_REQUIRED_PHRASE_RE.search(block) is not None
        for block in _NOSCRIPT_BLOCK_RE.findall(html)
    )


def _meaningful(text: str, *, min_content_chars: int, min_content_words: int) -> bool:
    """True when cleaned text is both long enough and word-substantive.

    Prevents a page of placeholder chrome (e.g. repeated "Loading..." / login
    menu strings) from being mistaken for meaningful server-rendered content.
    """
    stripped = text.strip()
    if len(stripped) < min_content_chars:
        return False
    return len(_WORD_RE.findall(stripped)) >= min_content_words


def judge_http_content(
    html: str,
    *,
    min_content_chars: int,
    min_content_words: int,
    js_shell_min_bytes: int,
) -> HttpContentVerdict:
    """Decide whether `html` from plain HTTP needs a Chromium re-fetch.

    Conservative by design: the fallback fires only when the document is
    substantial (>= `js_shell_min_bytes`), carries shell evidence (an
    application-root container element or an explicit noscript JS notice), yet
    yields very little *meaningful* cleaned text (fewer than
    `min_content_chars` characters or `min_content_words` words). Static/SSR
    pages, thin pages, and pages without shell markers always stay on the HTTP
    path, and framework fingerprints alone never trigger a fallback.
    """
    if len(html) < js_shell_min_bytes:
        return HttpContentVerdict.SUFFICIENT
    has_shell = _SHELL_ID_RE.search(html) is not None
    if not has_shell and not _noscript_js_required(html):
        return HttpContentVerdict.SUFFICIENT
    text = clean_html(html).strip()
    if _meaningful(text, min_content_chars=min_content_chars, min_content_words=min_content_words):
        return HttpContentVerdict.SUFFICIENT
    return HttpContentVerdict.JS_REQUIRED


def extract_http_content(html: str, url: str) -> ExtractionResult:
    """Extract structured content + cleaned text from an HTTP-fetched page."""
    page = extract_page(html, url)
    text = clean_html(html)
    return ExtractionResult(
        url=url,
        title=page.title,
        language=page.language,
        meta=dict(page.meta),
        canonical=page.canonical,
        headings=list(page.headings),
        paragraphs=list(page.paragraphs),
        links=list(page.links),
        text=text,
        text_length=len(text.strip()),
    )


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """Parse a `Retry-After` seconds value (HTTP-date replies fall back to None)."""
    value = response.headers.get("retry-after")
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


async def fetch_http_page(
    url: str,
    *,
    client: httpx.AsyncClient,
    guard: SsrFGuard,
    max_html_bytes: int | None = None,
    min_content_chars: int | None = None,
    min_content_words: int | None = None,
    js_shell_min_bytes: int | None = None,
    user_agent: str | None = None,
    overall_timeout_seconds: float | None = None,
    attempt: int = 1,
) -> HTTPFetchResult:
    """Fetch one URL over plain HTTP/HTTPS with redirect + size + type limits.

    Every hop (including redirect targets) is validated by `guard` so no request
    ever leaves the SSRF boundary. Bodies are streamed and truncated at
    `max_html_bytes`; responses that are too large, non-HTML, or >= 400 raise
    `FetchError` without ever touching Chromium.

    A wall-clock deadline (default: `crawl_navigation_timeout_ms`, the same
    budget the browser path applied to a whole navigation) caps the entire
    fetch, redirects included, so a slow-drip server can never keep a crawl
    page open indefinitely; per-operation timeouts on the client are preserved.
    Up to ``_MAX_REDIRECTS`` (20, matching the browser path) are followed.
    """
    settings = get_settings()
    if max_html_bytes is None:
        max_html_bytes = settings.crawl_max_html_bytes
    if min_content_chars is None:
        min_content_chars = settings.crawl_http_min_content_chars
    if min_content_words is None:
        min_content_words = settings.crawl_http_min_content_words
    if js_shell_min_bytes is None:
        js_shell_min_bytes = settings.crawl_http_js_shell_min_bytes
    if user_agent is None:
        user_agent = settings.crawl_browser_user_agent
    if overall_timeout_seconds is None:
        overall_timeout_seconds = settings.crawl_navigation_timeout_ms / 1000.0

    headers = {"User-Agent": user_agent, "Accept": _ACCEPT_HEADER}

    try:
        async with asyncio.timeout(overall_timeout_seconds):
            current = await guard.validate_async(url)
            response: httpx.Response | None = None
            for hop in range(_MAX_REDIRECTS + 1):
                request = client.build_request("GET", current, headers=headers)
                try:
                    response = await client.send(request, stream=True, follow_redirects=False)
                except httpx.HTTPError as exc:
                    raise _http_fetch_failure(
                        f"Could not reach {url}: {exc.__class__.__name__}",
                        url=url,
                        classification=classify_network_error(exc),
                        recoverable=True,
                        attempt=attempt,
                    ) from exc
                if response.status_code >= 400:
                    await response.aclose()
                    classification = classify_http_status(response.status_code)
                    error_host, error_path = safe_url_parts(url)
                    logger.warning(
                        "crawl_http_error hostname=%s path=%s status=%d classification=%s",
                        error_host,
                        error_path,
                        response.status_code,
                        classification.value,
                    )
                    raise _http_fetch_failure(
                        f"HTTP {response.status_code} for {url}.",
                        url=url,
                        classification=classification,
                        status_code=response.status_code,
                        recoverable=is_http_recoverable(response.status_code),
                        attempt=attempt,
                        retry_after_seconds=_retry_after_seconds(response),
                    )
                location = response.headers.get("location")
                if response.status_code in _REDIRECT_CODES and location:
                    await response.aclose()
                    if hop == _MAX_REDIRECTS:
                        raise _http_fetch_failure(
                            f"Too many redirects for {url}.",
                            url=url,
                            classification=CrawlFailureClassification.UNKNOWN_FAILURE,
                            attempt=attempt,
                        )
                    current = await guard.validate_async(urljoin(current, location))
                    continue
                break
            assert response is not None

            content_type = response.headers.get("content-type", "")
            chunks: list[bytes] = []
            size = 0
            try:
                async for chunk in response.aiter_bytes():
                    if size >= max_html_bytes:
                        break
                    room = max_html_bytes - size
                    data = chunk[:room]
                    chunks.append(data)
                    size += len(data)
            except httpx.HTTPError as exc:
                raise _http_fetch_failure(
                    f"Interrupted while reading {url}: {exc.__class__.__name__}",
                    url=url,
                    classification=classify_network_error(exc),
                    recoverable=True,
                    attempt=attempt,
                ) from exc
            finally:
                await response.aclose()

            raw = b"".join(chunks)
            html = _decode_html(raw, content_type)
            media = content_type.split(";", 1)[0].strip().lower()
            if not _accepted_media(media, html):
                raise _http_fetch_failure(
                    f"Unsupported content type {media or 'unknown'} for {url}.",
                    url=url,
                    classification=CrawlFailureClassification.UNSUPPORTED_CONTENT,
                    attempt=attempt,
                )
            verdict = (
                judge_http_content(
                    html,
                    min_content_chars=min_content_chars,
                    min_content_words=min_content_words,
                    js_shell_min_bytes=js_shell_min_bytes,
                )
                if media in _HTML_MEDIA_TYPES
                else HttpContentVerdict.SUFFICIENT
            )
            return HTTPFetchResult(
                final_url=current,
                html=html,
                content_type=media or None,
                status_code=response.status_code,
                verdict=verdict,
            )
    except TimeoutError:
        raise _http_fetch_failure(
            f"Timed out loading {url}.",
            url=url,
            classification=CrawlFailureClassification.CRAWL_TIMEOUT,
            recoverable=True,
            attempt=attempt,
        ) from None


def _default_http_client() -> httpx.AsyncClient:
    """Per-fetcher `httpx.AsyncClient`; tests inject their own factory."""
    settings = get_settings()
    return httpx.AsyncClient(timeout=httpx.Timeout(settings.crawl_navigation_timeout_ms / 1000.0))


def _http_fetch_failure(
    message: str,
    *,
    url: str,
    classification: CrawlFailureClassification,
    status_code: int | None = None,
    recoverable: bool = False,
    attempt: int = 1,
    retry_after_seconds: float | None = None,
) -> FetchError:
    """Build a classified, metrics-recorded HTTP `FetchError` (egress hardening).

    Every failed HTTP attempt is counted in `crawl_fetch_failures_total`
    (classification/status/method labels only, bounded cardinality), and the
    resulting error carries the metadata the worker, dashboard and retry loop
    need without parsing message text.
    """
    record_crawl_fetch_failure(
        classification=classification.value,
        status_code=status_code,
        method="http",
    )
    return FetchError(
        message,
        recoverable=recoverable,
        classification=classification.value,
        status_code=status_code,
        method="http",
        attempt=attempt,
        retry_after_seconds=retry_after_seconds,
    )


def _http_retry_delay_seconds(
    failure: FetchError,
    *,
    attempt: int,
    settings: Settings,
) -> float:
    """Bounded delay before the NEXT HTTP attempt for a retryable failure.

    - 429: honour `Retry-After` (seconds) capped at `crawl_retry_max_wait_seconds`;
      without a usable header, retry immediately (bounded by the attempt cap).
    - 5xx: exponential backoff `base * 2**(attempt-1)`, capped.
    - timeouts/network: retry immediately (still bounded by the attempt cap).
    """
    if failure.classification == CrawlFailureClassification.TARGET_RATE_LIMITED.value:
        if failure.retry_after_seconds is not None:
            return max(
                0.0,
                min(failure.retry_after_seconds, settings.crawl_retry_max_wait_seconds),
            )
        return 0.0
    if failure.classification == CrawlFailureClassification.TARGET_SERVER_ERROR.value:
        base = max(0.0, settings.crawl_retry_backoff_base_seconds)
        cap = max(base, settings.crawl_retry_backoff_cap_seconds)
        return float(min(base * (2 ** max(0, attempt - 1)), cap))
    # Timeout / network errors: retry immediately (attempt cap still bounds us).
    return 0.0


class HybridPageFetcher:
    """`PageFetcher` that prefers plain HTTP and falls back to Chromium per URL.

    Playwright is the memory-heavy half of the ingest stack (one shared browser
    plus one context per crawl job); the hybrid keeps it unopened unless a page
    is actually judged to need JavaScript, which makes the worker viable on the
    1 GiB Railway plan when concurrency is capped. All browser objects are
    created lazily on the first JS-required page and released in `close()`.
    """

    def __init__(
        self,
        *,
        guard: SsrFGuard,
        http_client_factory: Callable[[], httpx.AsyncClient] = _default_http_client,
        sleep_fn: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._guard = guard
        self._http_client_factory = http_client_factory
        self._sleep_fn = sleep_fn
        self._http_client: httpx.AsyncClient | None = None
        self._browser_fetcher: BrowserPageFetcher | None = None

    async def fetch(self, url: str) -> FetchedPage:
        await self._guard.validate_async(url)
        settings = get_settings()
        max_attempts = max(1, settings.crawl_http_max_attempts)
        attempt = 0
        last_http: FetchError | None = None
        while True:
            attempt += 1
            host, path = safe_url_parts(url)
            logger.info(
                "crawl_fetch_attempt hostname=%s path=%s method=http attempt=%d",
                host,
                path,
                attempt,
            )
            try:
                result = await fetch_http_page(
                    url,
                    client=self._get_http(),
                    guard=self._guard,
                    attempt=attempt,
                )
            except FetchError as exc:
                last_http = exc
                if not exc.recoverable:
                    raise
                # 403/429/5xx/network/timeout may fall back to the browser, but
                # 429/5xx/network/timeout get a BOUNDED HTTP retry first (403 is
                # never retried over HTTP per Phase 3). No retry storms.
                if exc.classification in _HTTP_RETRYABLE and attempt < max_attempts:
                    delay = _http_retry_delay_seconds(exc, attempt=attempt, settings=settings)
                    if delay > 0:
                        retry_host, retry_path = safe_url_parts(url)
                        logger.info(
                            "crawl_http_retry hostname=%s path=%s attempt=%d "
                            "delay_seconds=%.2f classification=%s",
                            retry_host,
                            retry_path,
                            attempt,
                            delay,
                            exc.classification,
                        )
                        await self._sleep_fn(delay)
                    continue
                # Do not retry HTTP further: fall back to the browser exactly once.
                break
            if result.verdict is HttpContentVerdict.JS_REQUIRED:
                js_host, js_path = safe_url_parts(url)
                logger.info(
                    "js_content_required hostname=%s path=%s using chromium fallback",
                    js_host,
                    js_path,
                )
                return await self._get_browser_fetcher().fetch(url)
            return FetchedPage(url=result.final_url, html=result.html)
        fallback_host, fallback_path = safe_url_parts(url)
        logger.info(
            "crawl_browser_fallback_start hostname=%s path=%s classification=%s",
            fallback_host,
            fallback_path,
            last_http.classification if last_http is not None else None,
        )
        return await self._get_browser_fetcher().fetch(url)

    def _get_http(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = self._http_client_factory()
        return self._http_client

    def _get_browser_fetcher(self) -> BrowserPageFetcher:
        if self._browser_fetcher is None:
            self._browser_fetcher = BrowserPageFetcher(guard=self._guard)
        return self._browser_fetcher

    async def close(self) -> None:
        if self._browser_fetcher is not None:
            await self._browser_fetcher.close()
            self._browser_fetcher = None
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None
