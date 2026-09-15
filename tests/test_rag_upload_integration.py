"""End-to-end integration tests for uploaded knowledge files into the RAG vector store."""

import hashlib

import pytest
from backend.models.document import SOURCE_TYPE_FILE, Document
from backend.models.knowledge_chunk import (
    KNOWLEDGE_STATUS_PENDING,
    KNOWLEDGE_STATUS_READY,
)
from backend.models.website import Website
from backend.services.ingestion.file_extractor import extract_text_from_file
from backend.services.knowledge.processor import KnowledgeProcessor

from tests.fakes import (
    FakeAuditLogRepository,
    FakeDocumentRepository,
    FakeEmbeddingClient,
    FakeKnowledgeChunkRepository,
    FakeUsageRecordRepository,
    FakeVectorRepository,
    FakeWebsiteRepository,
)


@pytest.mark.asyncio
async def test_uploaded_file_rag_ingestion_and_retrieval() -> None:
    # 1. Setup in-memory repositories
    documents_repo = FakeDocumentRepository()
    vector_repo = FakeVectorRepository()
    chunks_repo = FakeKnowledgeChunkRepository(vector_repo)
    websites_repo = FakeWebsiteRepository()
    audit_repo = FakeAuditLogRepository()
    embedder = FakeEmbeddingClient()
    usage_repo = FakeUsageRecordRepository()

    processor = KnowledgeProcessor(
        documents=documents_repo,
        vector=vector_repo,
        chunks=chunks_repo,
        websites=websites_repo,
        audit=audit_repo,
        embedder=embedder,
        usage=usage_repo,
    )

    tenant_id = "tenant-rag-1"
    website_id = "site-rag-1"

    website = Website.new(
        tenant_id=tenant_id,
        url=f"https://{website_id}.example.com/",
        name="RAG Test Site",
    )
    websites_repo.websites[website.id] = website

    # 2. Simulate text extraction from an uploaded file
    filename = "security_protocol.txt"
    file_bytes = (
        b"PROJECT OBSIDIAN: The primary quantum security encryption key is "
        b"stored in vault 99-Omega located in the Geneva underground facility. "
        b"All access requests must be signed by the project security committee."
    )
    extracted = extract_text_from_file(filename, file_bytes, "text/plain")

    text_checksum = hashlib.sha256(extracted.text.encode("utf-8")).hexdigest()
    file_checksum = hashlib.sha256(file_bytes).hexdigest()

    doc_id = "doc-upload-101"
    storage_key = "gridfs-oid-101"

    doc = Document.new(
        tenant_id=tenant_id,
        website_id=website.id,
        url=f"file://upload/{doc_id}/{filename}",
        title=filename,
        content=extracted.text,
        checksum=text_checksum,
        source_type=SOURCE_TYPE_FILE,
        file_name=filename,
        file_size_bytes=len(file_bytes),
        mime_type="text/plain",
        storage_key=storage_key,
        file_checksum_sha256=file_checksum,
    )
    doc.id = doc_id
    doc.knowledge_status = KNOWLEDGE_STATUS_PENDING
    await documents_repo.upsert(doc)

    # 3. Process document via KnowledgeProcessor (exact worker job path)
    result = await processor.process_document(doc.id)
    assert result["status"] == "processed"
    assert result["chunks"] >= 1

    # 4. Verify document state was updated to completed/ready
    updated_doc = await documents_repo.find_by_id(tenant_id, doc.id)
    assert updated_doc is not None
    assert updated_doc.knowledge_status == KNOWLEDGE_STATUS_READY
    assert updated_doc.knowledge_chunks >= 1

    # 5. Verify chunks were stored in vector repository
    stored_chunks = vector_repo.by_document(tenant_id, doc.id)
    assert len(stored_chunks) >= 1
    chunk = stored_chunks[0]
    assert "PROJECT OBSIDIAN" in chunk.chunk_text
    assert chunk.metadata["source_url"] == f"file://upload/{doc_id}/{filename}"
    assert chunk.metadata["title"] == filename

    # 6. Verify vector similarity search retrieves the uploaded chunk
    query_vector = (await embedder.embed(["Where is the encryption key?"]))[0]
    search_results = await vector_repo.similarity_search(
        tenant_id=tenant_id,
        website_id=website.id,
        query_embedding=query_vector,
        top_k=3,
    )
    assert len(search_results) >= 1
    top_hit = search_results[0]
    assert top_hit.chunk.document_id == doc.id
    assert "vault 99-Omega" in top_hit.chunk.chunk_text

    # 7. Strict multi-tenant isolation check: tenant-attacker gets 0 results
    attacker_results = await vector_repo.similarity_search(
        tenant_id="tenant-attacker",
        website_id=website.id,
        query_embedding=query_vector,
        top_k=3,
    )
    assert len(attacker_results) == 0

    # 8. Checksum skip: re-processing with same checksum skips re-embedding
    skip_result = await processor.process_document(doc.id)
    assert skip_result["status"] == "unchanged"


@pytest.mark.asyncio
async def test_uploaded_pdf_rag_ingestion() -> None:
    documents_repo = FakeDocumentRepository()
    vector_repo = FakeVectorRepository()
    chunks_repo = FakeKnowledgeChunkRepository(vector_repo)
    websites_repo = FakeWebsiteRepository()
    audit_repo = FakeAuditLogRepository()
    embedder = FakeEmbeddingClient()
    usage_repo = FakeUsageRecordRepository()

    processor = KnowledgeProcessor(
        documents=documents_repo,
        vector=vector_repo,
        chunks=chunks_repo,
        websites=websites_repo,
        audit=audit_repo,
        embedder=embedder,
        usage=usage_repo,
    )

    tenant_id = "tenant-rag-2"
    website_id = "site-rag-2"

    website = Website.new(
        tenant_id=tenant_id,
        url=f"https://{website_id}.example.com/",
        name="PDF Site",
    )
    websites_repo.websites[website.id] = website

    # PDF with more than 100 characters to pass knowledge_min_content_chars
    pdf_text = (
        "Enterprise Architecture Report 2026: This document provides detailed "
        "operational guidelines for managing distributed cluster nodes and storage."
    )
    stream_content = f"BT\n/F1 18 Tf\n50 700 Td\n({pdf_text}) Tj\nET"

    pdf_bytes = f"""%PDF-1.4
1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj
2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj
3 0 obj << /Type /Page /Parent 2 0 R
  /Resources << /Font << /F1 4 0 R >> >>
  /MediaBox [0 0 612 792] /Contents 5 0 R >> endobj
4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj
5 0 obj << /Length {len(stream_content)} >> stream
{stream_content}
endstream endobj
xref
0 6
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000244 00000 n 
0000000325 00000 n 
trailer << /Root 1 0 R /Size 6 >>
startxref
500
%%EOF""".encode("latin-1")

    filename = "report.pdf"
    extracted = extract_text_from_file(filename, pdf_bytes, "application/pdf")
    doc_id = "doc-pdf-202"

    doc = Document.new(
        tenant_id=tenant_id,
        website_id=website.id,
        url=f"file://upload/{doc_id}/{filename}",
        title=filename,
        content=extracted.text,
        checksum=hashlib.sha256(extracted.text.encode("utf-8")).hexdigest(),
        source_type=SOURCE_TYPE_FILE,
        file_name=filename,
        file_size_bytes=len(pdf_bytes),
        mime_type="application/pdf",
        storage_key="gridfs-pdf-202",
        file_checksum_sha256=hashlib.sha256(pdf_bytes).hexdigest(),
    )
    doc.id = doc_id
    await documents_repo.upsert(doc)

    res = await processor.process_document(doc.id)
    assert res["status"] == "processed"

    chunks = vector_repo.by_document(tenant_id, doc.id)
    assert len(chunks) >= 1
    assert "Enterprise Architecture Report" in chunks[0].chunk_text
