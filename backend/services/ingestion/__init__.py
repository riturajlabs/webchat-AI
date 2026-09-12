"""Ingestion engine: SSRF guard, browser, extraction, cleaning and crawling.

Phase 4 builds the website-to-documents pipeline. It never touches embeddings
or AI - Phase 5 (`reindex_website`) consumes the checksummed `documents`.
"""

from backend.services.ingestion.browser import BrowserPageFetcher
from backend.services.ingestion.cleaner import clean_html
from backend.services.ingestion.crawl_failure import CrawlFailureClassification
from backend.services.ingestion.crawler import (
    CrawlMemoryGuardError,
    CrawlSession,
    FetchedPage,
    FetchError,
    PageFetcher,
)
from backend.services.ingestion.extractor import ExtractedPage, extract_page, pick_preview_image
from backend.services.ingestion.http_first import (
    HttpContentVerdict,
    HTTPFetchResult,
    HybridPageFetcher,
    extract_http_content,
    fetch_http_page,
    judge_http_content,
)
from backend.services.ingestion.ssrf_guard import SsrFGuard

__all__ = [
    "BrowserPageFetcher",
    "CrawlFailureClassification",
    "CrawlMemoryGuardError",
    "CrawlSession",
    "ExtractedPage",
    "FetchError",
    "FetchedPage",
    "HTTPFetchResult",
    "HybridPageFetcher",
    "HttpContentVerdict",
    "PageFetcher",
    "SsrFGuard",
    "clean_html",
    "extract_http_content",
    "extract_page",
    "fetch_http_page",
    "judge_http_content",
    "pick_preview_image",
]
