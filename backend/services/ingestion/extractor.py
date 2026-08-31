"""Structured content extraction from crawled HTML (docs/06, Phase 4).

Uses BeautifulSoup's stdlib `html.parser` backend (no lxml build) to pull the
title, language, meta tags, canonical URL, headings, paragraphs, and internal
links out of a rendered page.
"""

from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from backend.utils.url_validator import normalize_crawl_url

_HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")


@dataclass(frozen=True)
class ExtractedPage:
    """Structured view of one crawled page."""

    url: str
    title: str
    language: str
    meta: dict[str, str]
    canonical: str | None
    headings: list[str]
    paragraphs: list[str]
    links: list[str] = field(default_factory=list)


def extract_page(html: str, url: str) -> ExtractedPage:
    """Extract structured content from `html` (resolving links against `url`)."""
    soup = BeautifulSoup(html, "html.parser")

    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    language = str(soup.html.get("lang") or "") if soup.html else ""

    meta: dict[str, str] = {}
    for tag in soup.find_all("meta"):
        if tag.get("name"):
            meta[str(tag["name"]).lower()] = str(tag.get("content") or "").strip()
        elif tag.get("property"):
            meta[str(tag["property"]).lower()] = str(tag.get("content") or "").strip()

    canonical_tag = soup.find("link", rel="canonical")
    canonical = str(canonical_tag.get("href")).strip() if canonical_tag else None

    headings = [tag.get_text(" ", strip=True) for tag in soup.find_all(_HEADING_TAGS)]
    paragraphs = [tag.get_text(" ", strip=True) for tag in soup.find_all("p")]

    links: list[str] = []
    for tag in soup.find_all("a", href=True):
        normalized = normalize_crawl_url(str(tag["href"]), url)
        if normalized is not None and normalized not in links:
            links.append(normalized)

    return ExtractedPage(
        url=url,
        title=title,
        language=language,
        meta=meta,
        canonical=canonical,
        headings=headings,
        paragraphs=paragraphs,
        links=links,
    )


def pick_preview_image(meta: dict[str, str], page_url: str) -> str | None:
    """Choose a website preview image from page metadata, if any.

    Preference order: `og:image`, then `twitter:image`, then the page's own
    `/favicon.ico`. All candidates are Open Graph / meta URLs (never fetched
    here), so no new crawl/SSRF surface is introduced — we only surface a URL
    the page already advertises, or a same-origin favicon for a page we already
    crawled. Relative URLs are normalized against the page's own origin, and
    only http(s) URLs are accepted (data:/javascript:/etc. are skipped as
    non-images).
    """
    candidate = meta.get("og:image") or meta.get("twitter:image")
    if candidate:
        absolute = urljoin(page_url, candidate.strip())
        parsed = urlparse(absolute)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return None
        return absolute
    base = urlparse(page_url)
    if base.scheme not in ("http", "https") or not base.netloc:
        return None
    return f"{base.scheme}://{base.netloc}/favicon.ico"
