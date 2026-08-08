"""Structured content extraction from crawled HTML (docs/06, Phase 4).

Uses BeautifulSoup's stdlib `html.parser` backend (no lxml build) to pull the
title, language, meta tags, canonical URL, headings, paragraphs, and internal
links out of a rendered page.
"""

from dataclasses import dataclass, field

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
