"""HTTP tests for the /api/knowledge endpoints (production hardening).

The dashboard reads per-document processing status and triggers manual retries;
both surfaces must be tenant-scoped (00-AI-Development-Rules §7).
"""

from dataclasses import dataclass, field

import pytest
from backend.api.deps import get_auth_service, get_knowledge_service
from backend.core.config import get_settings
from backend.main import create_app
from fastapi.testclient import TestClient

from tests.auth_helpers import VALID_PASSWORD, build_auth_env
from tests.fakes import (
    FakeAuditLogRepository,
    FakeDocumentRepository,
    FakeWebsiteRepository,
)
from tests.http_helpers import register_verified_account

REGISTER_PAYLOAD = {
    "name": "Alice",
    "email": "alice@example.com",
    "password": VALID_PASSWORD,
}

_ACCOUNT_SEQ = 0


@dataclass
class RecordingEnqueue:
    """Records per-document retry submissions instead of touching Redis."""

    document_ids: list[str] = field(default_factory=list)

    async def __call__(self, document_id: str) -> None:
        self.document_ids.append(document_id)


@dataclass
class KnowledgeEnv:
    websites: FakeWebsiteRepository
    documents: FakeDocumentRepository
    audit: FakeAuditLogRepository
    enqueue: RecordingEnqueue
    service: object


def build_knowledge_env() -> KnowledgeEnv:
    websites = FakeWebsiteRepository()
    documents = FakeDocumentRepository()
    audit = FakeAuditLogRepository()
    enqueue = RecordingEnqueue()
    from backend.services.knowledge import KnowledgeService

    service = KnowledgeService(
        websites=websites,
        documents=documents,
        audit=audit,
        enqueue=enqueue,
    )
    return KnowledgeEnv(
        websites=websites,
        documents=documents,
        audit=audit,
        enqueue=enqueue,
        service=service,
    )


@pytest.fixture
def client(monkeypatch):
    """A TestClient whose auth + knowledge services are backed by fakes."""
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    get_settings.cache_clear()
    auth_env = build_auth_env()
    knowledge_env = build_knowledge_env()
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: auth_env.service
    app.dependency_overrides[get_knowledge_service] = lambda: knowledge_env.service
    with TestClient(app) as test_client:
        yield test_client, knowledge_env, auth_env
    get_settings.cache_clear()


def _register(test_client: TestClient) -> tuple[dict[str, str], str]:
    """Register + verify a fresh account; return bearer headers and tenant_id."""
    global _ACCOUNT_SEQ
    _ACCOUNT_SEQ += 1
    body = register_verified_account(
        test_client,
        name="Alice",
        email=f"alice{_ACCOUNT_SEQ}@example.com",
    )
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    return headers, body["user"]["tenant_id"]


def _seed_website(env: KnowledgeEnv, *, tenant_id: str, website_id: str) -> None:
    from backend.models.website import Website

    website = Website.new(tenant_id=tenant_id, name="Acme", url="https://acme.example/")
    website.id = website_id
    env.websites.websites[website_id] = website


def _seed_document(
    env: KnowledgeEnv,
    *,
    tenant_id: str,
    website_id: str,
    url: str,
    title: str = "Page",
    status: str = "failed",
    failure_reason: str = "EmbeddingError: provider timeout",
    retry_count: int = 1,
) -> str:
    from backend.models.document import Document
    from backend.models.knowledge_chunk import KNOWLEDGE_STATUS_FAILED, KNOWLEDGE_STATUS_READY

    document = Document.new(
        tenant_id=tenant_id,
        website_id=website_id,
        url=url,
        title=title,
        content="Alpha beta. " * 40,
        checksum="abc123",
    )
    document.knowledge_status = (
        KNOWLEDGE_STATUS_READY if status == "ready" else KNOWLEDGE_STATUS_FAILED
    )
    document.knowledge_failure_reason = failure_reason if status == "failed" else None
    document.knowledge_retry_count = retry_count
    document.knowledge_chunks = 5 if status == "ready" else 0
    env.documents._documents[document.id] = document
    return document.id


def test_list_knowledge_documents_endpoint(client) -> None:
    test_client, env, _ = client
    headers, tenant_id = _register(test_client)
    _seed_website(env, tenant_id=tenant_id, website_id="site-a")
    _seed_document(
        env,
        tenant_id=tenant_id,
        website_id="site-a",
        url="https://acme.example/",
        status="ready",
    )
    _seed_document(
        env,
        tenant_id=tenant_id,
        website_id="site-a",
        url="https://acme.example/fail",
        status="failed",
    )

    response = test_client.get("/api/knowledge/websites/site-a/documents", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["website_id"] == "site-a"
    assert payload["summary"] == {
        "total": 2,
        "pending": 0,
        "processing": 0,
        "completed": 1,
        "failed": 1,
    }
    assert len(payload["documents"]) == 2
    failed = next(d for d in payload["documents"] if d["status"] == "failed")
    assert failed["url"] == "https://acme.example/fail"
    assert failed["failure_reason"] == "EmbeddingError: provider timeout"
    assert failed["retry_count"] == 1
    assert failed["last_attempt_at"] is None
    assert failed["chunks"] == 0


def test_list_knowledge_documents_unknown_website_404(client) -> None:
    test_client, _, _ = client
    headers, _ = _register(test_client)

    response = test_client.get("/api/knowledge/websites/ghost/documents", headers=headers)

    assert response.status_code == 404


def test_retry_document_endpoint_resets_and_requeues(client) -> None:
    test_client, env, _ = client
    headers, tenant_id = _register(test_client)
    _seed_website(env, tenant_id=tenant_id, website_id="site-a")
    document_id = _seed_document(
        env,
        tenant_id=tenant_id,
        website_id="site-a",
        url="https://acme.example/fail",
        status="failed",
    )

    response = test_client.post(f"/api/knowledge/documents/{document_id}/retry", headers=headers)

    assert response.status_code == 202
    payload = response.json()
    assert payload["document_id"] == document_id
    assert payload["website_id"] == "site-a"
    assert payload["status"] == "processing"
    assert env.enqueue.document_ids == [document_id]
    retried = env.documents._documents[document_id]
    assert retried.knowledge_retry_count == 0
    assert retried.knowledge_failure_reason is None


def test_retry_document_returns_404_for_missing_document(client) -> None:
    test_client, _, _ = client
    headers, _ = _register(test_client)

    response = test_client.post("/api/knowledge/documents/does-not-exist/retry", headers=headers)

    assert response.status_code == 404


def test_retry_document_is_tenant_scoped(client) -> None:
    """A foreign tenant must never see or retry another tenant's document."""
    test_client, env, _ = client
    headers, tenant_id = _register(test_client)
    _seed_website(env, tenant_id="other-tenant", website_id="site-other")
    document_id = _seed_document(
        env,
        tenant_id="other-tenant",
        website_id="site-other",
        url="https://other.example/fail",
        status="failed",
    )

    response = test_client.post(f"/api/knowledge/documents/{document_id}/retry", headers=headers)

    assert response.status_code == 404
    assert env.enqueue.document_ids == []


def test_retry_document_requires_owner_or_admin_role(client) -> None:
    test_client, env, auth_env = client
    headers, tenant_id = _register(test_client)
    _seed_website(env, tenant_id=tenant_id, website_id="site-a")
    document_id = _seed_document(
        env,
        tenant_id=tenant_id,
        website_id="site-a",
        url="https://acme.example/fail",
        status="failed",
    )

    from backend.core.security import create_access_token

    # A real viewer user/member in the same tenant resolves during auth, so the
    # role guard (not the auth gate) is what must reject the request.
    from backend.models.member import Member
    from backend.models.user import User

    viewer = User.new(
        tenant_id=tenant_id,
        name="Xavier",
        email="xavier@example.com",
        password_hash="x",
    )
    viewer.email_verified = True
    auth_env.users._users[viewer.id] = viewer
    auth_env.members._members[viewer.id] = Member.new(
        tenant_id=tenant_id, user_id=viewer.id, role="viewer"
    )
    viewer_token, _ = create_access_token(viewer.id, tenant_id, "viewer")
    viewer_headers = {"Authorization": f"Bearer {viewer_token}"}

    response = test_client.post(
        f"/api/knowledge/documents/{document_id}/retry", headers=viewer_headers
    )

    assert response.status_code == 403
    assert env.enqueue.document_ids == []
