#!/usr/bin/env python3
"""Phase 2 (ING-01 / ING-02) real end-to-end validation driver.

Runs the real ingestion + retrieval pipeline against the live stack
(MongoDB + Redis through the app's own repositories/services) using a real
headless-Chromium crawl, real provider embeddings (gemini via the app config),
and the real RAG service. It does NOT go through the HTTP API/auth layer; it
exercises the exact production modules under test (crawler priority queue,
embedding client pacing/429 handling, processor status model, vector search +
generation) on a small public content-rich documentation site.

Usage:
    .venv/bin/python scripts/e2e_phase2_ingestion.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(_PROJECT_ROOT / ".env.development"))

from backend.ai.registry import (  # noqa: E402
    build_embedding_fallback,
    build_generation_fallback,
    build_ingestion_embedding_client,
)
from backend.core.config import get_settings  # noqa: E402
from backend.core.database import MongoDB  # noqa: E402
from backend.core.redis import get_redis  # noqa: E402
from backend.models.tenant import Tenant  # noqa: E402
from backend.models.website import Website  # noqa: E402
from backend.repositories import (  # noqa: E402
    MongoAuditLogRepository,
    MongoChatMessageRepository,
    MongoChatSessionRepository,
    MongoDocumentRepository,
    MongoKnowledgeChunkRepository,
    MongoTenantRepository,
    MongoUsageRecordRepository,
    MongoWebsiteRepository,
)
from backend.repositories.vector import get_vector_repository  # noqa: E402
from backend.services.chat.rag_service import RagService  # noqa: E402
from backend.services.ingestion import BrowserPageFetcher, CrawlSession, SsrFGuard  # noqa: E402
from backend.services.ingestion.browser import close_browser, crawl_semaphore  # noqa: E402
from backend.services.knowledge.processor import KnowledgeProcessor  # noqa: E402

SEED = os.environ.get("E2E_SEED", "https://click.palletsprojects.com/en/stable/")
MAX_PAGES = 40
MAX_DEPTH = 3
TENANT = "e2e-phase2-tenant"
WEBSITE = "e2e-phase2-site"

QUESTIONS: list[tuple[str, str]] = [
    ("What is Click?", "positive"),
    ("How do I create a simple command with Click?", "positive"),
    ("How do I add an option with a flag?", "positive"),
    ("How do I prompt the user for input?", "positive"),
    ("How do I define a group command?", "positive"),
    ("How do I set a default value for an option?", "positive"),
    ("How do I read values from the environment?", "positive"),
    ("What is the difference between options and arguments?", "positive"),
    ("How do I pass arguments to a command?", "positive"),
    ("How can I control what is echoed to the terminal?", "positive"),
    ("What is the weather in Paris today?", "negative"),
    ("How do I bake a chocolate cake?", "negative"),
]


class Metrics:
    def __init__(self) -> None:
        self.crawl_started = 0.0
        self.crawl_elapsed = 0.0
        self.pages_stored = 0
        self.crawl_errors: list[str] = []
        self.crawled_urls: list[str] = []
        self.processed = 0
        self.skipped = 0
        self.failed = 0
        self.rate_limited = 0
        self.insufficient = 0
        self.embed_elapsed = 0.0
        self.questions: list[dict[str, Any]] = []


async def _warm_settings() -> None:
    s = get_settings()
    s.crawl_max_pages = MAX_PAGES
    s.crawl_max_depth = MAX_DEPTH
    # Bounded embedding fan-out (the ING-02 knob under test) stays at its
    # configured value; we only clamp the crawl bounds for a fast E2E.
    print(
        f"[config] crawl_max_pages={s.crawl_max_pages} crawl_max_depth={s.crawl_max_depth} "
        f"embed_concurrent={s.embedding_max_concurrent_batches} "
        f"embed_retry_base_ms={s.embedding_retry_base_delay_ms}"
    )


async def _seed_tenant_website(db: Any, metrics: Metrics) -> None:
    tenants = MongoTenantRepository(db)
    websites = MongoWebsiteRepository(db)
    existing = await tenants.find_by_id(TENANT)
    if existing is None:
        await tenants.create(Tenant.new(company_name="Phase 2 E2E"))
        print("[seed] created tenant", TENANT)
    website = await websites.find_by_id(TENANT, WEBSITE)
    if website is None:
        website = Website.new(tenant_id=TENANT, name="Click Docs E2E", url=SEED)
        website.id = WEBSITE
        await websites.create(website)
        print("[seed] created website", WEBSITE, SEED)


async def _crawl(db: Any, metrics: Metrics) -> None:
    documents = MongoDocumentRepository(db)
    guard = SsrFGuard()
    fetcher = BrowserPageFetcher(guard=guard)
    session = CrawlSession(
        tenant_id=TENANT,
        website_id=WEBSITE,
        seed_url=SEED,
        fetcher=fetcher,
        documents=documents,
        guard=guard,
    )
    metrics.crawl_started = time.monotonic()
    async with crawl_semaphore():
        stored = await session.run()
    metrics.crawl_elapsed = time.monotonic() - metrics.crawl_started
    metrics.pages_stored = stored
    metrics.crawled_urls = list(session.stored_urls)
    metrics.crawl_errors = [str(e) for e in session.errors]
    print(
        f"[crawl] stored={stored} elapsed={metrics.crawl_elapsed:.1f}s errors={len(session.errors)}"
    )
    for u in sorted(metrics.crawled_urls):
        print("        ", u)


async def _embed(db: Any, metrics: Metrics) -> None:
    documents = MongoDocumentRepository(db)
    chunks = MongoKnowledgeChunkRepository(db)
    websites = MongoWebsiteRepository(db)
    audit = MongoAuditLogRepository(db)
    usage = MongoUsageRecordRepository(db)
    embedder = build_ingestion_embedding_client()
    processor = KnowledgeProcessor(
        documents=documents,
        vector=get_vector_repository(db),
        chunks=chunks,
        websites=websites,
        audit=audit,
        embedder=embedder,
        usage=usage,
    )
    docs = await documents.list_by_website(TENANT, WEBSITE)
    # Content-rich pages only (thin boilerplate pages are expected to fail with
    # "Insufficient content" - the processor's permanent-failure rule).
    started = time.monotonic()
    outcomes: dict[str, int] = {}
    detail: dict[str, list[str]] = {}
    for doc in docs:
        result = await processor.process_document(doc.id)
        status = result.get("status", "unknown")
        outcomes[status] = outcomes.get(status, 0) + 1
        detail.setdefault(status, []).append(doc.url)
        if status == "processed":
            metrics.processed += 1
        elif status == "skipped_unchanged":
            metrics.skipped += 1
        elif status == "failed":
            metrics.failed += 1
            doc = await documents.find_by_id(TENANT, doc.id)
            if doc is not None and doc.knowledge_status == "rate_limited":
                metrics.rate_limited += 1
        elif status == "insufficient_content":
            metrics.insufficient += 1
        print(f"  [{status:>18}] {doc.url}")
    metrics.embed_elapsed = time.monotonic() - started
    print(f"[embed] outcomes={json.dumps(outcomes)} elapsed={metrics.embed_elapsed:.1f}s")


async def _ask(rag: RagService, tenant_id: str, website_id: str, metrics: Metrics) -> None:
    for question, category in QUESTIONS:
        t0 = time.perf_counter()
        events = []
        async for event in rag.stream_answer(
            tenant_id=tenant_id,
            website_id=website_id,
            question=question,
            visitor_id="e2e-phase2-visitor",
        ):
            events.append(event)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        done = next((e for e in events if e.get("event") == "done"), None)
        sources = next((e for e in events if e.get("event") == "sources"), None)
        if done is None:
            error = next((e for e in events if e.get("event") == "error"), None)
            metrics.questions.append(
                {
                    "q": question,
                    "category": category,
                    "latency_ms": latency_ms,
                    "fallback": True,
                    "sources": 0,
                    "source_urls": [],
                    "error": error,
                }
            )
            print(f"  [error] {question[:50]!r} -> {error}")
            continue
        fallback = bool(done["data"].get("fallback"))
        source_list = (
            [s["url"] for s in sources["data"]["sources"]]
            if sources and sources.get("data")
            else []
        )
        confidence = done["data"].get("confidence_score")
        metrics.questions.append(
            {
                "q": question,
                "category": category,
                "latency_ms": latency_ms,
                "fallback": fallback,
                "sources": len(source_list),
                "source_urls": source_list,
                "confidence": confidence,
            }
        )
        print(
            f"  [{category:<8}] fallback={fallback!s:<5} srcs={len(source_list):<2} "
            f"lat={latency_ms:6.0f}ms conf={confidence} :: {question[:60]!r}"
        )


async def main() -> None:
    await _warm_settings()
    db = MongoDB.db()
    metrics = Metrics()
    await _seed_tenant_website(db, metrics)
    try:
        await _crawl(db, metrics)
        await _embed(db, metrics)
        cache = None
        try:
            from backend.core.cache import RedisCacheStore

            cache = RedisCacheStore(get_redis(), prefix=f"{get_settings().redis_prefix}:rag")
        except Exception:
            pass
        rag = RagService(
            websites=MongoWebsiteRepository(db),
            vector=get_vector_repository(db),
            embedder=build_embedding_fallback(
                max_retries=get_settings().chat_embedding_max_retries
            ),
            generation=build_generation_fallback(),
            sessions=MongoChatSessionRepository(db),
            messages=MongoChatMessageRepository(db),
            usage=MongoUsageRecordRepository(db),
            cache=cache,
        )
        await _ask(rag, TENANT, WEBSITE, metrics)
    finally:
        await close_browser()

    report = {
        "seed": SEED,
        "max_pages": MAX_PAGES,
        "max_depth": MAX_DEPTH,
        "crawl": {
            "pages_stored": metrics.pages_stored,
            "elapsed_s": round(metrics.crawl_elapsed, 2),
            "error_count": len(metrics.crawl_errors),
            "errors": metrics.crawl_errors[:20],
            "urls": metrics.crawled_urls,
        },
        "embedding": {
            "processed": metrics.processed,
            "skipped_unchanged": metrics.skipped,
            "failed": metrics.failed,
            "rate_limited": metrics.rate_limited,
            "insufficient": metrics.insufficient,
            "elapsed_s": round(metrics.embed_elapsed, 2),
        },
        "rag": {
            "questions": metrics.questions,
            "fallback_rate": round(
                sum(1 for q in metrics.questions if q.get("fallback"))
                / max(1, len(metrics.questions)),
                4,
            ),
        },
    }
    out = Path(_PROJECT_ROOT / ".audit-tmp" / "PHASE2_E2E_RESULTS.json")
    out.parent.mkdir(exist_ok=True)
    await asyncio.to_thread(out.write_text, json.dumps(report, indent=2))
    print("\n[report] written to", out)


if __name__ == "__main__":
    asyncio.run(main())
