"""HTTP tests for knowledge file upload, download, and delete endpoints."""

import io
from dataclasses import dataclass, field

import pytest
from backend.api.deps import get_auth_service, get_knowledge_service
from backend.core.config import get_settings
from backend.core.errors import LimitReachedError, StorageFileNotFoundError
from backend.main import create_app
from backend.models.audit_log import AUDIT_KNOWLEDGE_DELETED, AUDIT_KNOWLEDGE_UPLOADED
from backend.models.document import SOURCE_TYPE_FILE, SOURCE_TYPE_WEBSITE, Document
from backend.models.website import Website
from backend.services.knowledge import KnowledgeService
from fastapi.testclient import TestClient

from tests.auth_helpers import build_auth_env
from tests.fakes import (
    FakeAuditLogRepository,
    FakeDocumentRepository,
    FakeWebsiteRepository,
)
from tests.http_helpers import register_verified_account

_ACCOUNT_SEQ = 0


@dataclass
class RecordingEnqueue:
    document_ids: list[str] = field(default_factory=list)

    async def __call__(self, document_id: str) -> None:
        self.document_ids.append(document_id)


class FakeStorageService:
    def __init__(self) -> None:
        self.files: dict[tuple[str, str], bytes] = {}
        self._seq = 0

    async def upload(
        self,
        *,
        tenant_id: str,
        website_id: str,
        document_id: str,
        filename: str,
        content: bytes,
        mime_type: str,
    ) -> str:
        self._seq += 1
        storage_key = f"fake-key-{self._seq}"
        self.files[(tenant_id, storage_key)] = content
        return storage_key

    async def download(
        self,
        *,
        tenant_id: str,
        storage_key: str,
    ) -> bytes:
        if (tenant_id, storage_key) not in self.files:
            raise StorageFileNotFoundError("File not found.")
        return self.files[(tenant_id, storage_key)]

    async def delete(
        self,
        *,
        tenant_id: str,
        storage_key: str,
    ) -> bool:
        if (tenant_id, storage_key) in self.files:
            del self.files[(tenant_id, storage_key)]
            return True
        return False


class FakeVectorRepository:
    def __init__(self) -> None:
        self.deleted_docs: list[tuple[str, str]] = []

    async def delete_by_document(self, tenant_id: str, document_id: str) -> int:
        self.deleted_docs.append((tenant_id, document_id))
        return 1


class FakeUsageService:
    def __init__(self) -> None:
        self.limit_exceeded = False

    async def check_limit(
        self, tenant_id: str, *, event_type: str, quantity: int = 1
    ) -> None:
        if self.limit_exceeded:
            raise LimitReachedError(
                "Subscription document limit reached.", extra={"metric": event_type}
            )


@dataclass
class UploadEnv:
    websites: FakeWebsiteRepository
    documents: FakeDocumentRepository
    audit: FakeAuditLogRepository
    enqueue: RecordingEnqueue
    storage: FakeStorageService
    vector: FakeVectorRepository
    usage: FakeUsageService
    service: KnowledgeService


def build_upload_env() -> UploadEnv:
    websites = FakeWebsiteRepository()
    documents = FakeDocumentRepository()
    audit = FakeAuditLogRepository()
    enqueue = RecordingEnqueue()
    storage = FakeStorageService()
    vector = FakeVectorRepository()
    usage = FakeUsageService()
    service = KnowledgeService(
        websites=websites,
        documents=documents,
        audit=audit,
        enqueue=enqueue,
        storage=storage,
        vector=vector,
        usage=usage,
    )
    return UploadEnv(
        websites=websites,
        documents=documents,
        audit=audit,
        enqueue=enqueue,
        storage=storage,
        vector=vector,
        usage=usage,
        service=service,
    )


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    get_settings.cache_clear()
    auth_env = build_auth_env()
    upload_env = build_upload_env()
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: auth_env.service
    app.dependency_overrides[get_knowledge_service] = lambda: upload_env.service
    with TestClient(app) as test_client:
        yield test_client, upload_env, auth_env
    get_settings.cache_clear()


def _register(test_client: TestClient) -> tuple[dict[str, str], str]:
    global _ACCOUNT_SEQ
    _ACCOUNT_SEQ += 1
    body = register_verified_account(
        test_client,
        name="Alice",
        email=f"alice_upload{_ACCOUNT_SEQ}@example.com",
    )
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    return headers, body["user"]["tenant_id"]


def _make_website(tenant_id: str, website_id: str = "site-1") -> Website:
    return Website.new(
        tenant_id=tenant_id,
        url=f"https://{website_id}.example.com/",
        name="Test Site",
    )


def test_upload_single_txt_file_success(client) -> None:
    test_client, env, _ = client
    headers, tenant_id = _register(test_client)
    site = _make_website(tenant_id, "site-1")
    env.websites.websites[site.id] = site

    file_content = b"This is a valid test documentation text file with more than 50 characters."
    files = [("files", ("test.txt", io.BytesIO(file_content), "text/plain"))]

    resp = test_client.post(
        f"/api/knowledge/websites/{site.id}/documents/upload",
        headers=headers,
        files=files,
    )

    assert resp.status_code == 201
    data = resp.json()
    assert data["website_id"] == site.id
    assert len(data["uploaded"]) == 1
    item = data["uploaded"][0]
    assert item["file_name"] == "test.txt"
    assert item["status"] == "pending"
    assert item["char_count"] == len(file_content.decode("utf-8"))

    # Assert document is persisted with file fields
    doc = env.documents.documents[item["id"]]
    assert doc.source_type == SOURCE_TYPE_FILE
    assert doc.file_name == "test.txt"
    assert doc.file_size_bytes == len(file_content)
    assert doc.storage_key is not None
    assert doc.file_checksum_sha256 is not None
    assert doc.url.startswith(f"file://upload/{doc.id}/test.txt")

    # Assert enqueued
    assert doc.id in env.enqueue.document_ids

    # Assert storage holds the binary
    stored_bytes = env.storage.files[(tenant_id, doc.storage_key)]
    assert stored_bytes == file_content

    # Assert audit log
    actions = [log.action for log in env.audit.logs]
    assert AUDIT_KNOWLEDGE_UPLOADED in actions


def test_upload_multiple_files_batch(client) -> None:
    test_client, env, _ = client
    headers, tenant_id = _register(test_client)
    site = _make_website(tenant_id, "site-batch")
    env.websites.websites[site.id] = site

    txt_content = b"First documentation file with sufficient text for processing validation."
    md_content = b"# Markdown Guide\n\nSecond documentation file with enough content."

    files = [
        ("files", ("one.txt", io.BytesIO(txt_content), "text/plain")),
        ("files", ("two.md", io.BytesIO(md_content), "text/markdown")),
    ]

    resp = test_client.post(
        f"/api/knowledge/websites/{site.id}/documents/upload",
        headers=headers,
        files=files,
    )

    assert resp.status_code == 201
    data = resp.json()
    assert len(data["uploaded"]) == 2
    assert len(env.enqueue.document_ids) == 2


def test_upload_exceeds_max_files_batch_rejected(client) -> None:
    test_client, env, _ = client
    headers, tenant_id = _register(test_client)
    site = _make_website(tenant_id, "site-exceed")
    env.websites.websites[site.id] = site

    content = b"Content for testing batch size limit validation exceeding max count."
    files = [
        ("files", (f"file_{i}.txt", io.BytesIO(content), "text/plain"))
        for i in range(6)
    ]

    resp = test_client.post(
        f"/api/knowledge/websites/{site.id}/documents/upload",
        headers=headers,
        files=files,
    )

    assert resp.status_code == 400
    assert "Maximum of 5 files allowed" in resp.json()["error"]["message"]


def test_upload_duplicate_file_in_batch_rejected(client) -> None:
    test_client, env, _ = client
    headers, tenant_id = _register(test_client)
    site = _make_website(tenant_id, "site-batch-dupe")
    env.websites.websites[site.id] = site

    identical_content = b"Identical binary content duplicated in the same batch payload."
    files = [
        ("files", ("file_a.txt", io.BytesIO(identical_content), "text/plain")),
        ("files", ("file_b.txt", io.BytesIO(identical_content), "text/plain")),
    ]

    resp = test_client.post(
        f"/api/knowledge/websites/{site.id}/documents/upload",
        headers=headers,
        files=files,
    )

    assert resp.status_code == 409
    assert "Duplicate file" in resp.json()["error"]["message"]


def test_upload_duplicate_file_existing_website_rejected(client) -> None:
    test_client, env, _ = client
    headers, tenant_id = _register(test_client)
    site = _make_website(tenant_id, "site-reupload")
    env.websites.websites[site.id] = site

    content = b"Content uploaded in initial upload call that will be re-attempted."
    files1 = [("files", ("first.txt", io.BytesIO(content), "text/plain"))]
    resp1 = test_client.post(
        f"/api/knowledge/websites/{site.id}/documents/upload",
        headers=headers,
        files=files1,
    )
    assert resp1.status_code == 201

    files2 = [("files", ("first.txt", io.BytesIO(content), "text/plain"))]
    resp2 = test_client.post(
        f"/api/knowledge/websites/{site.id}/documents/upload",
        headers=headers,
        files=files2,
    )
    assert resp2.status_code == 409
    assert "already been uploaded" in resp2.json()["error"]["message"]


def test_upload_duplicate_file_different_websites_allowed(client) -> None:
    test_client, env, _ = client
    headers, tenant_id = _register(test_client)
    site1 = _make_website(tenant_id, "site-1")
    site2 = _make_website(tenant_id, "site-2")
    env.websites.websites[site1.id] = site1
    env.websites.websites[site2.id] = site2

    content = b"Content uploaded to two different websites owned by the same tenant."
    files1 = [("files", ("shared.txt", io.BytesIO(content), "text/plain"))]
    resp1 = test_client.post(
        f"/api/knowledge/websites/{site1.id}/documents/upload",
        headers=headers,
        files=files1,
    )
    assert resp1.status_code == 201

    files2 = [("files", ("shared.txt", io.BytesIO(content), "text/plain"))]
    resp2 = test_client.post(
        f"/api/knowledge/websites/{site2.id}/documents/upload",
        headers=headers,
        files=files2,
    )
    assert resp2.status_code == 201


def test_upload_plan_document_limit_exceeded_rejected(client) -> None:
    test_client, env, _ = client
    headers, tenant_id = _register(test_client)
    site = _make_website(tenant_id, "site-limit")
    env.websites.websites[site.id] = site
    env.usage.limit_exceeded = True

    files = [
        (
            "files",
            (
                "doc.txt",
                io.BytesIO(b"Valid content with more than fifty characters for limit test."),
                "text/plain",
            ),
        )
    ]
    resp = test_client.post(
        f"/api/knowledge/websites/{site.id}/documents/upload",
        headers=headers,
        files=files,
    )
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "LIMIT_REACHED"


def test_upload_tenant_isolation(client) -> None:
    test_client, env, _ = client
    headers_a, tenant_a = _register(test_client)
    _, tenant_b = _register(test_client)

    site_b = _make_website(tenant_b, "site-b")
    env.websites.websites[site_b.id] = site_b

    files = [
        (
            "files",
            (
                "doc.txt",
                io.BytesIO(b"Content attempted to be uploaded to another tenant website."),
                "text/plain",
            ),
        )
    ]
    # Tenant A attempts to upload to Tenant B's website
    resp = test_client.post(
        f"/api/knowledge/websites/{site_b.id}/documents/upload",
        headers=headers_a,
        files=files,
    )
    assert resp.status_code == 404


def test_upload_corrupted_pdf_rejected(client) -> None:
    test_client, env, _ = client
    headers, tenant_id = _register(test_client)
    site = _make_website(tenant_id, "site-corrupt")
    env.websites.websites[site.id] = site

    corrupt_pdf = b"NOT_A_VALID_PDF_HEADER_BYTES" + b" " * 100
    files = [("files", ("bad.pdf", io.BytesIO(corrupt_pdf), "application/pdf"))]

    resp = test_client.post(
        f"/api/knowledge/websites/{site.id}/documents/upload",
        headers=headers,
        files=files,
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "DOCUMENT_CORRUPTED"


def test_delete_uploaded_document_success(client) -> None:
    test_client, env, _ = client
    headers, tenant_id = _register(test_client)
    site = _make_website(tenant_id, "site-del")
    env.websites.websites[site.id] = site

    file_content = b"Content to be deleted after upload testing successfully."
    files = [("files", ("del.txt", io.BytesIO(file_content), "text/plain"))]
    upload_resp = test_client.post(
        f"/api/knowledge/websites/{site.id}/documents/upload",
        headers=headers,
        files=files,
    )
    assert upload_resp.status_code == 201
    doc_id = upload_resp.json()["uploaded"][0]["id"]
    storage_key = env.documents.documents[doc_id].storage_key

    # Confirm exists in storage and documents
    assert (tenant_id, storage_key) in env.storage.files
    assert doc_id in env.documents.documents

    # Delete
    del_resp = test_client.delete(f"/api/knowledge/documents/{doc_id}", headers=headers)
    assert del_resp.status_code == 200
    del_data = del_resp.json()
    assert del_data["deleted"] is True
    assert del_data["document_id"] == doc_id

    # Confirm removed from documents repo
    assert doc_id not in env.documents.documents
    # Confirm removed from storage
    assert (tenant_id, storage_key) not in env.storage.files
    # Confirm chunks deleted from vector repo
    assert (tenant_id, doc_id) in env.vector.deleted_docs
    # Confirm audit log
    assert AUDIT_KNOWLEDGE_DELETED in [log.action for log in env.audit.logs]


def test_delete_tenant_isolation(client) -> None:
    test_client, env, _ = client
    headers_a, tenant_a = _register(test_client)
    headers_b, tenant_b = _register(test_client)

    site_a = _make_website(tenant_a, "site-a")
    env.websites.websites[site_a.id] = site_a

    file_content = b"Document owned by tenant A which tenant B will try to delete."
    files = [("files", ("a.txt", io.BytesIO(file_content), "text/plain"))]
    upload_resp = test_client.post(
        f"/api/knowledge/websites/{site_a.id}/documents/upload",
        headers=headers_a,
        files=files,
    )
    doc_id = upload_resp.json()["uploaded"][0]["id"]

    # Tenant B tries to delete Tenant A's document
    del_resp = test_client.delete(f"/api/knowledge/documents/{doc_id}", headers=headers_b)
    assert del_resp.status_code == 404
    assert doc_id in env.documents.documents


def test_download_uploaded_file_success(client) -> None:
    test_client, env, _ = client
    headers, tenant_id = _register(test_client)
    site = _make_website(tenant_id, "site-dl")
    env.websites.websites[site.id] = site

    file_content = b"Unique content for download verification endpoint testing."
    files = [("files", ("download_me.txt", io.BytesIO(file_content), "text/plain"))]
    upload_resp = test_client.post(
        f"/api/knowledge/websites/{site.id}/documents/upload",
        headers=headers,
        files=files,
    )
    doc_id = upload_resp.json()["uploaded"][0]["id"]

    # Download
    dl_resp = test_client.get(f"/api/knowledge/documents/{doc_id}/download", headers=headers)
    assert dl_resp.status_code == 200
    assert dl_resp.content == file_content
    assert "attachment" in dl_resp.headers["Content-Disposition"]
    assert "download_me.txt" in dl_resp.headers["Content-Disposition"]


def test_download_website_document_rejected(client) -> None:
    test_client, env, _ = client
    headers, tenant_id = _register(test_client)
    site = _make_website(tenant_id, "site-web")
    env.websites.websites[site.id] = site

    # Create a website page document without file attachment
    web_doc = Document.new(
        tenant_id=tenant_id,
        website_id=site.id,
        url="https://site-web.example.com/page",
        title="Web Page",
        content="This is a crawled website page with no file attachment.",
        checksum="abc",
        source_type=SOURCE_TYPE_WEBSITE,
    )
    env.documents.documents[web_doc.id] = web_doc

    dl_resp = test_client.get(f"/api/knowledge/documents/{web_doc.id}/download", headers=headers)
    assert dl_resp.status_code == 400


def test_download_tenant_isolation(client) -> None:
    test_client, env, _ = client
    headers_a, tenant_a = _register(test_client)
    headers_b, tenant_b = _register(test_client)

    site_a = _make_website(tenant_a, "site-dl-iso")
    env.websites.websites[site_a.id] = site_a

    file_content = b"Secret data for Tenant A that Tenant B cannot access."
    files = [("files", ("secret.txt", io.BytesIO(file_content), "text/plain"))]
    upload_resp = test_client.post(
        f"/api/knowledge/websites/{site_a.id}/documents/upload",
        headers=headers_a,
        files=files,
    )
    doc_id = upload_resp.json()["uploaded"][0]["id"]

    # Tenant B tries to download Tenant A's document
    dl_resp = test_client.get(f"/api/knowledge/documents/{doc_id}/download", headers=headers_b)
    assert dl_resp.status_code == 404
