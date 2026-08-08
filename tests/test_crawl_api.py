"""API tests for POST /websites/{id}/crawl and GET /crawl-jobs/{id} (Phase 4)."""

import pytest
from backend.api.deps import get_auth_service, get_crawl_service
from backend.core.config import get_settings
from backend.core.errors import CrawlConflictError, CrawlJobNotFoundError
from backend.main import create_app
from backend.models.crawl_job import CRAWL_STATUS_COMPLETED, CRAWL_STATUS_PENDING, CrawlJob
from fastapi.testclient import TestClient
from tests.auth_helpers import VALID_PASSWORD, build_auth_env

_ACCOUNT_SEQ = 0


class _StubCrawlService:
    def __init__(self) -> None:
        self.job: CrawlJob | None = None
        self.enqueued: list[str] = []
        self.raise_conflict = False
        self.missing_website = False

    async def start_crawl(self, *, principal, website_id, ip_address, user_agent):
        if self.raise_conflict:
            raise CrawlConflictError("A crawl is already in progress.")
        if self.missing_website:
            raise CrawlJobNotFoundError("Website not found.")
        job = CrawlJob.new(tenant_id=principal.tenant_id, website_id=website_id)
        self.job = job
        self.enqueued.append(website_id)
        return job

    async def get_crawl_job(self, tenant_id: str, job_id: str):
        if self.job is None or self.job.id != job_id or self.job.tenant_id != tenant_id:
            raise CrawlJobNotFoundError("Crawl job not found.")
        return self.job


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    get_settings.cache_clear()
    auth_env = build_auth_env()
    stub = _StubCrawlService()
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: auth_env.service
    app.dependency_overrides[get_crawl_service] = lambda: stub
    with TestClient(app) as test_client:
        yield test_client, stub
    get_settings.cache_clear()


def _auth_headers(test_client: TestClient) -> dict[str, str]:
    global _ACCOUNT_SEQ
    _ACCOUNT_SEQ += 1
    payload = {
        "name": "Alice",
        "email": f"alice{_ACCOUNT_SEQ}@example.com",
        "password": VALID_PASSWORD,
    }
    response = test_client.post("/api/auth/register", json=payload)
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_start_crawl_returns_202_and_job(client) -> None:
    test_client, stub = client
    headers = _auth_headers(test_client)

    resp = test_client.post("/api/websites/website-1/crawl", headers=headers)

    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["crawl_job_id"] == stub.job.id
    assert body["status"] == CRAWL_STATUS_PENDING
    assert stub.enqueued == ["website-1"]


def test_start_crawl_requires_auth(client) -> None:
    test_client, _ = client
    resp = test_client.post("/api/websites/website-1/crawl")
    assert resp.status_code == 401


def test_start_crawl_conflict_returns_409(client) -> None:
    test_client, stub = client
    headers = _auth_headers(test_client)
    stub.raise_conflict = True

    resp = test_client.post("/api/websites/website-1/crawl", headers=headers)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "CRAWL_IN_PROGRESS"
    assert resp.json()["error"]["message"] == "A crawl is already in progress."


def test_start_crawl_missing_website_returns_404(client) -> None:
    test_client, stub = client
    headers = _auth_headers(test_client)
    stub.missing_website = True

    resp = test_client.post("/api/websites/website-1/crawl", headers=headers)
    assert resp.status_code == 404


def test_get_crawl_job_returns_payload(client) -> None:
    test_client, stub = client
    headers = _auth_headers(test_client)
    test_client.post("/api/websites/website-1/crawl", headers=headers)
    job = stub.job
    job.status = CRAWL_STATUS_COMPLETED
    job.pages_completed = 3

    resp = test_client.get(f"/api/crawl-jobs/{job.id}", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == job.id
    assert body["website_id"] == "website-1"
    assert body["status"] == CRAWL_STATUS_COMPLETED
    assert body["pages_completed"] == 3


def test_get_crawl_job_unknown_returns_404(client) -> None:
    test_client, _ = client
    headers = _auth_headers(test_client)
    resp = test_client.get("/api/crawl-jobs/missing", headers=headers)
    assert resp.status_code == 404


def test_get_crawl_job_requires_auth(client) -> None:
    test_client, _ = client
    resp = test_client.get("/api/crawl-jobs/some-id")
    assert resp.status_code == 401
