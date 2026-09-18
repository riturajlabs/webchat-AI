"""Tests for Document source_type discriminator and crawl purge safety (Phase 1)."""

from unittest.mock import AsyncMock

import pytest
from backend.models.crawl_job import CrawlJob
from backend.models.document import (
    SOURCE_TYPE_FILE,
    SOURCE_TYPE_WEBSITE,
    Document,
)
from backend.models.knowledge_chunk import KnowledgeChunk
from backend.models.website import Website
from backend.services.ingestion import SsrFGuard
from backend.workers.jobs.crawl import _purge_removed_documents, _run_crawl_job, _site_checksum

from tests.crawl_helpers import FakePageFetcher
from tests.fakes import (
    FakeAuditLogRepository,
    FakeCrawlJobRepository,
    FakeDocumentRepository,
    FakeUsageRecordRepository,
    FakeVectorRepository,
    FakeWebsiteRepository,
)


def test_document_model_defaults_and_legacy_compatibility() -> None:
    """Legacy documents missing source_type deserialize cleanly as 'website'."""
    legacy_doc_dict = {
        "_id": "doc_legacy_1",
        "tenant_id": "tenant_1",
        "website_id": "site_1",
        "url": "https://example.com/about",
        "title": "About Us",
        "content": "About us text content",
        "checksum": "sha256_hash_1",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    doc = Document.from_doc(legacy_doc_dict)
    assert doc.id == "doc_legacy_1"
    assert doc.source_type == SOURCE_TYPE_WEBSITE
    assert doc.file_name is None
    assert doc.file_size_bytes is None
    assert doc.mime_type is None
    assert doc.storage_key is None
    assert doc.file_checksum_sha256 is None


def test_document_model_file_source_instantiation() -> None:
    """Document created with source_type='file' retains all file metadata."""
    doc = Document.new(
        tenant_id="tenant_1",
        website_id="site_1",
        url="file://upload/doc_123/pricing.pdf",
        title="pricing.pdf",
        content="Pricing information text...",
        checksum="content_checksum_123",
        source_type=SOURCE_TYPE_FILE,
        file_name="pricing.pdf",
        file_size_bytes=102400,
        mime_type="application/pdf",
        storage_key="gridfs_id_456",
        file_checksum_sha256="raw_file_sha256_789",
    )
    assert doc.source_type == SOURCE_TYPE_FILE
    assert doc.file_name == "pricing.pdf"
    assert doc.file_size_bytes == 102400
    assert doc.mime_type == "application/pdf"
    assert doc.storage_key == "gridfs_id_456"
    assert doc.file_checksum_sha256 == "raw_file_sha256_789"

    doc_dict = doc.to_doc()
    assert doc_dict["source_type"] == SOURCE_TYPE_FILE
    assert doc_dict["file_name"] == "pricing.pdf"
    assert doc_dict["file_size_bytes"] == 102400
    assert doc_dict["storage_key"] == "gridfs_id_456"
    assert doc_dict["file_checksum_sha256"] == "raw_file_sha256_789"

    restored = Document.from_doc(doc_dict)
    assert restored.source_type == SOURCE_TYPE_FILE
    assert restored.file_name == "pricing.pdf"
    assert restored.storage_key == "gridfs_id_456"


@pytest.mark.asyncio
async def test_crawl_purge_ignores_uploaded_files() -> None:
    """MANDATORY SAFETY: Website crawl reconciliation must NOT purge uploaded files."""
    doc_website_kept = Document.new(
        tenant_id="tenant_1",
        website_id="site_1",
        url="https://example.com/kept",
        title="Kept Page",
        content="Kept content",
        checksum="hash_kept",
        source_type=SOURCE_TYPE_WEBSITE,
    )
    doc_website_removed = Document.new(
        tenant_id="tenant_1",
        website_id="site_1",
        url="https://example.com/removed",
        title="Removed Page",
        content="Removed content",
        checksum="hash_removed",
        source_type=SOURCE_TYPE_WEBSITE,
    )
    doc_file_uploaded = Document.new(
        tenant_id="tenant_1",
        website_id="site_1",
        url="file://upload/doc_file/handbook.pdf",
        title="handbook.pdf",
        content="Handbook content",
        checksum="hash_file",
        source_type=SOURCE_TYPE_FILE,
        file_name="handbook.pdf",
        file_size_bytes=50000,
        storage_key="gridfs_storage_key_1",
    )

    documents_mock = AsyncMock()
    documents_mock.list_by_website.return_value = [
        doc_website_kept,
        doc_website_removed,
        doc_file_uploaded,
    ]
    documents_mock.delete_by_ids.return_value = 1

    vector_mock = AsyncMock()

    crawled_urls = ["https://example.com/kept"]
    errored_urls: list[str] = []

    purged_count = await _purge_removed_documents(
        documents=documents_mock,
        vector=vector_mock,
        tenant_id="tenant_1",
        website_id="site_1",
        crawled_urls=crawled_urls,
        errored_urls=errored_urls,
    )

    # Exactly 1 page should have been purged (the removed website page)
    assert purged_count == 1

    # Assert vector chunks deleted only for the removed website document
    vector_mock.delete_by_document.assert_called_once_with("tenant_1", doc_website_removed.id)

    # Assert delete_by_ids called ONLY for the removed website document
    documents_mock.delete_by_ids.assert_called_once_with("tenant_1", [doc_website_removed.id])


@pytest.mark.asyncio
async def test_site_checksum_filters_website_documents() -> None:
    """Site crawl checksum only includes website source documents."""
    documents_mock = AsyncMock()
    documents_mock.all_checksums.return_value = ["hash1", "hash2"]

    digest = await _site_checksum(documents_mock, "tenant_1", "site_1")

    assert isinstance(digest, str)
    documents_mock.all_checksums.assert_called_once_with(
        "tenant_1", "site_1", source_type="website"
    )


@pytest.fixture
def patch_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_resolve(self: SsrFGuard, host: str) -> list[str]:
        return ["93.184.216.34"]

    monkeypatch.setattr(SsrFGuard, "resolve_async", fake_resolve)


@pytest.mark.asyncio
async def test_crawl_purge_ordering_only_winner_executes_purge(patch_dns: None) -> None:
    """WK-01 regression test: Purge ordering invariant (FIND-02).

    Attempt A loses finish_if_active() -> purge is NOT executed.
    Attempt B wins finish_if_active() -> purge IS executed exactly once.
    Existing successful crawl path still purges removed website documents.
    """
    tenant_id = "tenant-a"
    seed_url = "https://acme.example/"
    vanished_url = "https://acme.example/vanished"

    websites = FakeWebsiteRepository()
    website = Website.new(tenant_id=tenant_id, name="Acme", url=seed_url)
    await websites.create(website)

    jobs = FakeCrawlJobRepository()
    job = CrawlJob.new(tenant_id=tenant_id, website_id=website.id)
    await jobs.create(job)
    website.crawl_job_id = job.id
    await websites.update(website)

    documents = FakeDocumentRepository()
    # 1. Existing kept document (already in knowledge base, will be re-crawled)
    kept_doc = Document.new(
        tenant_id=tenant_id,
        website_id=website.id,
        url=seed_url,
        title="Acme Home",
        content="Welcome to Acme",
        checksum="kept_checksum",
        source_type=SOURCE_TYPE_WEBSITE,
    )
    await documents.upsert(kept_doc)

    # 2. Existing vanished document (was in knowledge base, no longer on site)
    vanished_doc = Document.new(
        tenant_id=tenant_id,
        website_id=website.id,
        url=vanished_url,
        title="Old Page",
        content="Vanished content",
        checksum="vanished_checksum",
        source_type=SOURCE_TYPE_WEBSITE,
    )
    await documents.upsert(vanished_doc)

    # 3. Vector chunks for the vanished document
    vector = FakeVectorRepository()
    vanished_chunk = KnowledgeChunk.new(
        tenant_id=tenant_id,
        website_id=website.id,
        document_id=vanished_doc.id,
        chunk_text="Vanished content",
        embedding=[0.25] * 4,
        chunk_index=0,
    )
    await vector.insert_chunks([vanished_chunk])

    audit = FakeAuditLogRepository()
    usage = FakeUsageRecordRepository()

    # The crawler fetcher only returns the seed URL - vanished_url is gone!
    fetcher = FakePageFetcher({seed_url: "<html><body>Welcome to Acme</body></html>"})
    ctx: dict[str, object] = {"crawler_fetcher": fetcher, "job_try": 1, "max_tries": 3}

    # Pre-condition: both documents and the vanished chunk exist
    assert await documents.find_by_id(tenant_id, kept_doc.id) is not None
    assert await documents.find_by_id(tenant_id, vanished_doc.id) is not None
    assert len(await vector.list_chunks(tenant_id, website.id)) == 1

    # --- ATTEMPT A: Loses finish_if_active() ---
    # Wrap jobs repository so finish_if_active returns False (simulating losing the terminal race)
    class LosingJobsRepo:
        def __init__(self, real_repo: FakeCrawlJobRepository) -> None:
            self._real = real_repo
            self.calls: list[str] = []

        async def find_by_id_any(self, jid: str) -> CrawlJob | None:
            return await self._real.find_by_id_any(jid)

        async def update(self, j: CrawlJob) -> None:
            await self._real.update(j)

        async def finish_if_active(self, *args: object, **kwargs: object) -> bool:
            self.calls.append("finish_if_active")
            return False  # Attempt A loses the terminal race!

    losing_jobs = LosingJobsRepo(jobs)

    result_a = await _run_crawl_job(
        ctx,
        job.id,
        crawl_jobs=losing_jobs,
        documents=documents,
        websites=websites,
        audit=audit,
        usage=usage,
        vector=vector,
    )

    # Attempt A completed crawling but lost terminal status
    assert result_a["status"] == "completed"
    assert len(losing_jobs.calls) == 1
    # STATE-BASED VERIFICATION: purge was NOT executed by Attempt A!
    # vanished_doc still exists in documents repository!
    assert await documents.find_by_id(tenant_id, vanished_doc.id) is not None
    # vanished_chunk still exists in vector repository!
    chunks_after_a = await vector.list_chunks(tenant_id, website.id)
    assert len(chunks_after_a) == 1
    assert chunks_after_a[0].document_id == vanished_doc.id

    # --- ATTEMPT B: Wins finish_if_active() ---
    # Attempt B uses the real repository where finish_if_active succeeds (won=True)
    fetcher_b = FakePageFetcher({seed_url: "<html><body>Welcome to Acme</body></html>"})
    ctx_b: dict[str, object] = {"crawler_fetcher": fetcher_b, "job_try": 1, "max_tries": 3}

    result_b = await _run_crawl_job(
        ctx_b,
        job.id,
        crawl_jobs=jobs,
        documents=documents,
        websites=websites,
        audit=audit,
        usage=usage,
        vector=vector,
    )

    # Attempt B completed and won
    assert result_b["status"] == "completed"
    # STATE-BASED VERIFICATION: purge WAS executed by Attempt B!
    # vanished_doc is now PURGED from documents repository!
    assert await documents.find_by_id(tenant_id, vanished_doc.id) is None
    # vanished_chunk is now PURGED from vector repository!
    assert await vector.list_chunks(tenant_id, website.id) == []
    # Kept document remains in documents repository!
    crawled_after_b = await documents.list_by_website(tenant_id, website.id)
    assert any(d.url == seed_url for d in crawled_after_b)
    assert not any(d.url == vanished_url for d in crawled_after_b)

    # --- ATTEMPT C: Stale duplicate after already terminal ---
    # Running again when job is already terminal (active=False)
    fetcher_c = FakePageFetcher({seed_url: "<html><body>Welcome to Acme</body></html>"})
    ctx_c: dict[str, object] = {"crawler_fetcher": fetcher_c, "job_try": 1, "max_tries": 3}
    result_c = await _run_crawl_job(
        ctx_c,
        job.id,
        crawl_jobs=jobs,
        documents=documents,
        websites=websites,
        audit=audit,
        usage=usage,
        vector=vector,
    )
    assert result_c["status"] == "completed"
    # Purge was executed exactly once (only by Attempt B)
    crawled_after_c = await documents.list_by_website(tenant_id, website.id)
    assert any(d.url == seed_url for d in crawled_after_c)
