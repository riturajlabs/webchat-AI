"""Tests for Document source_type discriminator and crawl purge safety (Phase 1)."""

from unittest.mock import AsyncMock

import pytest
from backend.models.document import (
    SOURCE_TYPE_FILE,
    SOURCE_TYPE_WEBSITE,
    Document,
)
from backend.workers.jobs.crawl import _purge_removed_documents, _site_checksum


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
