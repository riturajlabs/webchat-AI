"""End-to-end HTTP tests for the /api/feedback endpoints using fakes.

Phase 12.4 (ADR-005 §5.6): the dashboard read surfaces — paginated list with
website/category/rating filters and the satisfaction summary. Exercises auth,
RBAC, tenant isolation, and the request validation of the Pydantic boundary.
"""

import pytest
from backend.api.deps import get_auth_service, get_feedback_service
from backend.core.config import get_settings
from backend.main import create_app
from fastapi.testclient import TestClient

from tests.auth_helpers import VALID_PASSWORD, build_auth_env
from tests.feedback_helpers import build_feedback_env, seed_assistant_message

_ACCOUNT_SEQ = 0

REGISTER_PAYLOAD = {
    "name": "Alice",
    "email": "alice@example.com",
    "password": VALID_PASSWORD,
}


@pytest.fixture
def client(monkeypatch):
    """A TestClient whose auth + feedback services use in-memory fakes."""
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    get_settings.cache_clear()
    auth_env = build_auth_env()
    feedback_env = build_feedback_env()
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: auth_env.service
    app.dependency_overrides[get_feedback_service] = lambda: feedback_env.service
    with TestClient(app) as test_client:
        yield test_client, auth_env, feedback_env
    get_settings.cache_clear()


def _auth(test_client: TestClient) -> tuple[dict[str, str], str]:
    """Register a fresh account and return (bearer headers, tenant_id)."""
    global _ACCOUNT_SEQ
    _ACCOUNT_SEQ += 1
    payload = {
        "name": "Alice",
        "email": f"alice{_ACCOUNT_SEQ}@example.com",
        "password": VALID_PASSWORD,
    }
    response = test_client.post("/api/auth/register", json=payload)
    assert response.status_code == 201, response.text
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["user"]["tenant_id"]


async def _seed_ratings(feedback_env, tenant_id: str) -> None:
    for index in range(3):
        await seed_assistant_message(feedback_env, tenant_id=tenant_id, message_id=f"msg-{index}")
        await feedback_env.service.submit(
            tenant_id=tenant_id,
            website_id="web-1",
            session_id="session-1",
            message_id=f"msg-{index}",
            rating=index + 1,
            category="helpful" if index == 2 else "wrong",
        )


def test_feedback_requires_authentication(client) -> None:
    test_client, _, _ = client
    assert test_client.get("/api/feedback").status_code == 401
    assert test_client.get("/api/feedback/summary").status_code == 401


async def test_feedback_list_returns_paginated_ratings(client) -> None:
    test_client, _, feedback_env = client
    headers, tenant_id = _auth(test_client)
    await _seed_ratings(feedback_env, tenant_id)

    response = test_client.get("/api/feedback", headers=headers)

    assert response.status_code == 200
    assert response.headers["X-Total-Count"] == "3"
    body = response.json()
    assert body["total"] == 3
    assert body["page"] == 1
    assert body["per_page"] == 20
    assert len(body["items"]) == 3
    first = body["items"][0]
    assert first["message_id"] == "msg-2"
    assert first["rating"] == 3
    assert first["category"] == "helpful"
    assert first["comment"] == ""
    assert first["session_id"] == "session-1"
    assert first["website_id"] == "web-1"


async def test_feedback_list_filters_by_category_and_rating(client) -> None:
    test_client, _, feedback_env = client
    headers, tenant_id = _auth(test_client)
    await _seed_ratings(feedback_env, tenant_id)

    wrong = test_client.get("/api/feedback?category=wrong", headers=headers)
    assert wrong.status_code == 200
    assert wrong.json()["total"] == 2

    rated = test_client.get("/api/feedback?rating=3", headers=headers)
    assert rated.status_code == 200
    assert rated.json()["total"] == 1
    assert rated.json()["items"][0]["message_id"] == "msg-2"


async def test_feedback_summary_reports_distribution(client) -> None:
    test_client, _, feedback_env = client
    headers, tenant_id = _auth(test_client)
    await _seed_ratings(feedback_env, tenant_id)

    response = test_client.get("/api/feedback/summary", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    # (1 + 2 + 3) / 3 = 2.0
    assert body["average_rating"] == 2.0
    # JSON object keys are always strings.
    assert body["distribution"] == {"1": 1, "2": 1, "3": 1}


async def test_feedback_summary_empty_returns_nulls(client) -> None:
    test_client, _, _ = client
    headers, _tenant_id = _auth(test_client)

    response = test_client.get("/api/feedback/summary", headers=headers)

    assert response.status_code == 200
    assert response.json() == {
        "total": 0,
        "average_rating": None,
        "distribution": {},
    }


async def test_feedback_summary_accepts_days_filter(client) -> None:
    test_client, _, feedback_env = client
    headers, tenant_id = _auth(test_client)
    await _seed_ratings(feedback_env, tenant_id)

    response = test_client.get("/api/feedback/summary?days=90", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["average_rating"] == 2.0

    assert (
        test_client.get("/api/feedback/summary?days=0", headers=headers).status_code == 422
    )
    assert (
        test_client.get("/api/feedback/summary?days=91", headers=headers).status_code == 422
    )


async def test_feedback_isolates_tenants(client) -> None:
    test_client, _, feedback_env = client
    owner_headers, owner_tenant = _auth(test_client)
    await _seed_ratings(feedback_env, owner_tenant)

    other_headers, _other_tenant = _auth(test_client)

    other_list = test_client.get("/api/feedback", headers=other_headers)
    assert other_list.status_code == 200
    assert other_list.json()["total"] == 0

    other_summary = test_client.get("/api/feedback/summary", headers=other_headers)
    assert other_summary.json()["total"] == 0


async def test_feedback_requires_owner_or_admin_role(client) -> None:
    test_client, auth_env, _ = client
    headers, _tenant_id = _auth(test_client)
    member = next(iter(auth_env.members.members.values()))
    member.role = "viewer"

    response = test_client.get("/api/feedback", headers=headers)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


async def test_feedback_rejects_invalid_filters(client) -> None:
    test_client, _, _ = client
    headers, _tenant_id = _auth(test_client)

    assert test_client.get("/api/feedback?rating=6", headers=headers).status_code == 422
    assert test_client.get("/api/feedback?rating=0", headers=headers).status_code == 422
    assert test_client.get("/api/feedback?category=bogus", headers=headers).status_code == 422
    assert test_client.get("/api/feedback?per_page=101", headers=headers).status_code == 422
