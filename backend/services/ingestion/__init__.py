"""Ingestion engine: SSRF guard, browser, extraction, cleaning and crawling.

Phase 4 builds the website-to-documents pipeline. It never touches embeddings
or AI - Phase 5 (`reindex_website`) consumes the checksummed `documents`.
"""

from backend.services.ingestion.browser import BrowserPageFetcher
from backend.services.ingestion.cleaner import clean_html
from backend.services.ingestion.crawler import (
    CrawlSession,
    FetchedPage,
    FetchError,
    PageFetcher,
)
from backend.services.ingestion.extractor import ExtractedPage, extract_page, pick_preview_image
from backend.services.ingestion.ssrf_guard import SsrFGuard

__all__ = [
    "BrowserPageFetcher",
    "CrawlSession",
    "ExtractedPage",
    "FetchError",
    "FetchedPage",
    "PageFetcher",
    "SsrFGuard",
    "clean_html",
    "extract_page",
    "pick_preview_image",
]
