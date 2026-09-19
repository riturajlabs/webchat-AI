"""Regression tests for file upload quota semantics and Free-plan limits.

Verifies:
A. Website crawl documents (source_type="website") do not consume uploaded-file quota.
B. First valid file upload after website crawl succeeds.
C. Free-plan limit blocks uploads when actual file quota is genuinely exhausted.
D. Cross-tenant usage cannot affect another tenant's quota.
E. Existing upload limits remain intact (types, sizes, batches, isolation).
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from backend.core.errors import (
    AppError,
    DocumentTooLargeError,
    DuplicateFileError,
    LimitReachedError,
    WebsiteNotFoundError,
)
from backend.models.document import (
    SOURCE_TYPE_FILE,
    SOURCE_TYPE_WEBSITE,
    Document,
)
from backend.models.plan import PLAN_FREE
from backend.models.tenant import Tenant
from backend.models.website import Website
from backend.services.auth import Principal
from backend.services.billing.usage_service import UsageService
from backend.services.knowledge.knowledge_service import KnowledgeService

from tests.fakes import (
    FakeAuditLogRepository,
    FakeDocumentRepository,
    FakeStorageService,
    FakeTenantRepository,
    FakeUsageEventRepository,
    FakeWebsiteRepository,
)


@dataclass
class RecordingEnqueue:
    document_ids: list[str] = field(default_factory=list)

    async def __call__(self, document_id: str) -> None:
        self.document_ids.append(document_id)


class FakeVectorRepository:
    def __init__(self) -> None:
        self.deleted_docs: list[tuple[str, str]] = []

    async def delete_by_document(self, tenant_id: str, document_id: str) -> int:
        self.deleted_docs.append((tenant_id, document_id))
        return 1


NOW = datetime(2026, 9, 17, 12, 0, 0, tzinfo=UTC)
VALID_FILE_CONTENT = (
    b"This is a valid test documentation text file with sufficient character count for extraction."
)


def _make_principal(tenant_id: str, user_id: str = "user-1") -> Principal:
    return Principal(
        user_id=user_id,
        tenant_id=tenant_id,
        role="owner",
        name="Alice",
        email=f"{user_id}@{tenant_id}.com",
        email_verified=True,
        status="active",
        created_at=NOW,
    )


def _build_env():
    tenants = FakeTenantRepository()
    websites = FakeWebsiteRepository()
    documents = FakeDocumentRepository()
    audit = FakeAuditLogRepository()
    enqueue = RecordingEnqueue()
    storage = FakeStorageService()
    vector = FakeVectorRepository()
    events = FakeUsageEventRepository()

    usage = UsageService(
        events=events,
        tenants=tenants,
        websites=websites,
        documents=documents,
        subscriptions=None,
        now=lambda: NOW,
    )

    service = KnowledgeService(
        websites=websites,
        documents=documents,
        audit=audit,
        enqueue=enqueue,
        storage=storage,
        vector=vector,
        usage=usage,
    )

    return {
        "tenants": tenants,
        "websites": websites,
        "documents": documents,
        "usage": usage,
        "service": service,
        "storage": storage,
    }


async def _seed_free_tenant(env, tenant_id: str) -> Tenant:
    tenant = Tenant.new(company_name="Test Company")
    tenant.id = tenant_id
    tenant.plan = PLAN_FREE
    await env["tenants"].create(tenant)
    return tenant


# ============================================================================
# TEST A: Website crawl documents do not consume uploaded-file quota
# ============================================================================


@pytest.mark.asyncio
async def test_a_crawl_documents_do_not_consume_uploaded_file_quota() -> None:
    env = _build_env()
    tenant_id = "tenant-a"
    await _seed_free_tenant(env, tenant_id)

    site = Website.new(tenant_id=tenant_id, name="Docs", url="https://docs.example.com")
    await env["websites"].create(site)

    # Simulate crawl: 15 website pages stored (exceeding Free plan's max_documents=10)
    for i in range(15):
        doc = Document.new(
            tenant_id=tenant_id,
            website_id=site.id,
            url=f"https://docs.example.com/page-{i}",
            title=f"Page {i}",
            content=f"Content for crawled page {i}",
            checksum=f"hash-{i}",
            source_type=SOURCE_TYPE_WEBSITE,
        )
        await env["documents"].upsert(doc)

    # Verify document repo counts
    all_docs = await env["documents"].count_by_tenant(tenant_id)
    assert all_docs == 15

    file_docs = await env["documents"].count_by_tenant(tenant_id, source_type=SOURCE_TYPE_FILE)
    assert file_docs == 0

    # Usage service checks limit for documents (should pass, used is 0, limit is 10)
    await env["usage"].check_limit(tenant_id, event_type="documents", quantity=1)

    snapshot = await env["usage"].get_current_usage(tenant_id)
    assert snapshot.documents == 0
    metric = next(m for m in snapshot.metrics if m.metric == "documents")
    assert metric.used == 0
    assert metric.limit == 10
    assert metric.percent == 0.0


# ============================================================================
# TEST B: First valid file upload after website crawl succeeds
# ============================================================================


@pytest.mark.asyncio
async def test_b_first_file_upload_after_website_crawl_succeeds() -> None:
    env = _build_env()
    tenant_id = "tenant-b"
    await _seed_free_tenant(env, tenant_id)

    site = Website.new(tenant_id=tenant_id, name="Docs", url="https://docs.example.com")
    await env["websites"].create(site)

    # 12 crawled website documents exist
    for i in range(12):
        doc = Document.new(
            tenant_id=tenant_id,
            website_id=site.id,
            url=f"https://docs.example.com/page-{i}",
            title=f"Page {i}",
            content=f"Crawled content {i}",
            checksum=f"c-hash-{i}",
            source_type=SOURCE_TYPE_WEBSITE,
        )
        await env["documents"].upsert(doc)

    principal = _make_principal(tenant_id)

    # Upload first valid file document
    files = [("user_guide.txt", VALID_FILE_CONTENT, "text/plain")]
    result = await env["service"].upload_files(
        principal=principal,
        website_id=site.id,
        files=files,
    )

    assert len(result) == 1
    assert result[0].file_name == "user_guide.txt"
    assert result[0].source_type == SOURCE_TYPE_FILE

    # Current usage documents count should now be exactly 1
    snapshot = await env["usage"].get_current_usage(tenant_id)
    assert snapshot.documents == 1
    metric = next(m for m in snapshot.metrics if m.metric == "documents")
    assert metric.used == 1
    assert metric.limit == 10


# ============================================================================
# TEST C: Existing Free-plan document limit still blocks when quota exhausted
# ============================================================================


@pytest.mark.asyncio
async def test_c_free_plan_document_limit_blocks_when_exhausted() -> None:
    env = _build_env()
    tenant_id = "tenant-c"
    await _seed_free_tenant(env, tenant_id)

    site = Website.new(tenant_id=tenant_id, name="Docs", url="https://docs.example.com")
    await env["websites"].create(site)

    principal = _make_principal(tenant_id)

    # Upload 10 file documents (reaching the Free plan limit of 10)
    for i in range(10):
        content = f"Unique valid content for document {i} to exceed extraction threshold.".encode()
        await env["service"].upload_files(
            principal=principal,
            website_id=site.id,
            files=[(f"file_{i}.txt", content, "text/plain")],
        )

    assert (await env["usage"].get_current_usage(tenant_id)).documents == 10

    # Attempting to upload an 11th file must raise LimitReachedError
    with pytest.raises(LimitReachedError) as exc_info:
        await env["service"].upload_files(
            principal=principal,
            website_id=site.id,
            files=[
                ("file_11.txt", b"Content that should be rejected by quota limit.", "text/plain")
            ],
        )

    assert exc_info.value.status_code == 429
    assert exc_info.value.code == "LIMIT_REACHED"
    assert "Free plan limit for documents has been reached" in str(exc_info.value.message)


# ============================================================================
# TEST D: Cross-tenant usage cannot affect another tenant's quota
# ============================================================================


@pytest.mark.asyncio
async def test_d_cross_tenant_isolation_preserves_quota() -> None:
    env = _build_env()
    tenant_a = "tenant-d-alpha"
    tenant_b = "tenant-d-beta"

    await _seed_free_tenant(env, tenant_a)
    await _seed_free_tenant(env, tenant_b)

    site_a = Website.new(tenant_id=tenant_a, name="Site A", url="https://a.example.com")
    site_b = Website.new(tenant_id=tenant_b, name="Site B", url="https://b.example.com")
    await env["websites"].create(site_a)
    await env["websites"].create(site_b)

    principal_b = _make_principal(tenant_b, user_id="user-b")

    # Tenant B exhausts their 10 document quota
    for i in range(10):
        content = (
            f"Tenant B document content {i} with sufficient text length for ingestion.".encode()
        )
        await env["service"].upload_files(
            principal=principal_b,
            website_id=site_b.id,
            files=[(f"b_doc_{i}.txt", content, "text/plain")],
        )

    # Tenant B is exhausted
    assert (await env["usage"].get_current_usage(tenant_b)).documents == 10

    # Tenant A still has 0 used documents and can upload freely
    assert (await env["usage"].get_current_usage(tenant_a)).documents == 0

    principal_a = _make_principal(tenant_a, user_id="user-a")
    res_a = await env["service"].upload_files(
        principal=principal_a,
        website_id=site_a.id,
        files=[("a_doc_1.txt", VALID_FILE_CONTENT, "text/plain")],
    )
    assert len(res_a) == 1
    assert (await env["usage"].get_current_usage(tenant_a)).documents == 1


# ============================================================================
# TEST E: Existing upload limits remain intact
# ============================================================================


@pytest.mark.asyncio
async def test_e_existing_upload_limits_remain_intact() -> None:
    env = _build_env()
    tenant_id = "tenant-e"
    await _seed_free_tenant(env, tenant_id)

    site = Website.new(tenant_id=tenant_id, name="Docs", url="https://docs.example.com")
    await env["websites"].create(site)

    principal = _make_principal(tenant_id)

    # 1. Unsupported file extension
    with pytest.raises(AppError) as exc_info:
        await env["service"].upload_files(
            principal=principal,
            website_id=site.id,
            files=[("malicious.exe", b"executable payload content...", "application/octet-stream")],
        )
    assert "Unsupported file type" in str(exc_info.value.message)

    # 2. File size exceeds 10 MB
    large_payload = b"A" * (10 * 1024 * 1024 + 1)
    with pytest.raises(DocumentTooLargeError):
        await env["service"].upload_files(
            principal=principal,
            website_id=site.id,
            files=[("huge.txt", large_payload, "text/plain")],
        )

    # 3. Batch size exceeds 5 files
    too_many_files = [(f"doc_{i}.txt", VALID_FILE_CONTENT, "text/plain") for i in range(6)]
    with pytest.raises(AppError) as exc_info:
        await env["service"].upload_files(
            principal=principal,
            website_id=site.id,
            files=too_many_files,
        )
    assert "Maximum of 5 files allowed" in str(exc_info.value.message)

    # 4. In-batch duplicate file
    with pytest.raises(DuplicateFileError):
        await env["service"].upload_files(
            principal=principal,
            website_id=site.id,
            files=[
                ("doc_a.txt", VALID_FILE_CONTENT, "text/plain"),
                ("doc_b.txt", VALID_FILE_CONTENT, "text/plain"),
            ],
        )

    # 5. Tenant isolation (cannot upload to another tenant's website)
    other_tenant_principal = _make_principal("other-tenant", user_id="other-user")
    with pytest.raises(WebsiteNotFoundError):
        await env["service"].upload_files(
            principal=other_tenant_principal,
            website_id=site.id,
            files=[("doc.txt", VALID_FILE_CONTENT, "text/plain")],
        )
