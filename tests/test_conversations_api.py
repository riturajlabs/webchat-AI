"""End-to-end HTTP tests for the /api/conversations endpoints using fakes."""

from datetime import UTC, datetime, timedelta

import pytest
from backend.api.deps import get_auth_service, get_conversation_service
from backend.core.config import get_settings
from backend.main import create_app
from backend.models.audit_log import AUDIT_CONVERSATION_DELETED
from backend.models.chat_session import CHAT_SESSION_STATUS_DELETED
from fastapi.testclient import TestClient

from tests.auth_helpers import VALID_PASSWORD, build_auth_env
from tests.conversations_helpers import build_conversation_env, seed_conversation

REGISTER_PAYLOAD = {
    "name": "Alice",
    "email": "alice@example.com",
    "password": VALID_PASSWORD,
}

_ACCOUNT_SEQ = 0


@pytest.fixture
def client(monkeypatch):
    """A TestClient whose auth + conversation services use in-memory fakes."""
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    get_settings.cache_clear()
    auth_env = build_auth_env()
    conv_env = build_conversation_env()
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: auth_env.service
    app.dependency_overrides[get_conversation_service] = lambda: conv_env.service
    with TestClient(app) as test_client:
        yield test_client, conv_env
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


async def _seed(
    conv_env,
    *,
    tenant_id: str,
    session_id: str,
    **kwargs,
) -> None:
    await seed_conversation(conv_env, tenant_id=tenant_id, session_id=session_id, **kwargs)


async def test_list_returns_summaries(client) -> None:
    test_client, conv_env = client
    headers, tenant_id = _auth(test_client)
    await _seed(
        conv_env,
        tenant_id=tenant_id,
        session_id="sess-1",
        visitor_id="visitor-1",
        turns=[("user", "What are your pricing plans?"), ("assistant", "We offer three plans.")],
    )

    response = test_client.get("/api/conversations", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["page"] == 1
    assert body["per_page"] == 20
    assert response.headers["X-Total-Count"] == "1"

    item = body["items"][0]
    assert item["id"] == "sess-1"
    assert item["website_id"] == "web-1"
    assert item["visitor_id"] == "visitor-1"
    assert item["title"] == "What are your pricing plans?"
    assert item["message_count"] == 2
    assert item["last_message"] == "We offer three plans."
    assert item["status"] == "answered"


def test_list_empty_returns_no_items(client) -> None:
    test_client, _ = client
    headers, _tenant_id = _auth(test_client)

    response = test_client.get("/api/conversations", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body == {"items": [], "total": 0, "page": 1, "per_page": 20}
    assert response.headers["X-Total-Count"] == "0"


async def test_list_paginates_and_orders_by_activity(client) -> None:
    test_client, conv_env = client
    headers, tenant_id = _auth(test_client)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    await _seed(
        conv_env, tenant_id=tenant_id, session_id="old", turns=[("user", "Oldest")],
        last_activity=base,
    )
    await _seed(
        conv_env, tenant_id=tenant_id, session_id="mid", turns=[("user", "Middle")],
        last_activity=base + timedelta(hours=1),
    )
    await _seed(
        conv_env, tenant_id=tenant_id, session_id="new", turns=[("user", "Newest")],
        last_activity=base + timedelta(hours=2),
    )

    page_one = test_client.get(
        "/api/conversations?per_page=2&page=1", headers=headers
    ).json()
    assert [item["id"] for item in page_one["items"]] == ["new", "mid"]
    assert page_one["total"] == 3

    page_two = test_client.get("/api/conversations?per_page=2&page=2", headers=headers).json()
    assert [item["id"] for item in page_two["items"]] == ["old"]


async def test_list_search_matches_message_content(client) -> None:
    test_client, conv_env = client
    headers, tenant_id = _auth(test_client)
    await _seed(
        conv_env, tenant_id=tenant_id, session_id="match", turns=[("user", "Refund policy?")]
    )
    await _seed(
        conv_env, tenant_id=tenant_id, session_id="nomatch", turns=[("user", "Shipping times?")]
    )

    response = test_client.get(
        "/api/conversations?search=refund", headers=headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert [item["id"] for item in body["items"]] == ["match"]


async def test_list_search_with_no_hits_is_empty(client) -> None:
    test_client, conv_env = client
    headers, tenant_id = _auth(test_client)
    await _seed(conv_env, tenant_id=tenant_id, session_id="sess-1", turns=[("user", "Hi")])

    response = test_client.get("/api/conversations?search=zzzz", headers=headers)

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["total"] == 0


async def test_list_filters_by_website(client) -> None:
    test_client, conv_env = client
    headers, tenant_id = _auth(test_client)
    await _seed(conv_env, tenant_id=tenant_id, session_id="sess-a", website_id="web-a")
    await _seed(conv_env, tenant_id=tenant_id, session_id="sess-b", website_id="web-b")

    response = test_client.get("/api/conversations?website_id=web-a", headers=headers)

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == ["sess-a"]


async def test_list_search_combined_with_website_filter(client) -> None:
    test_client, conv_env = client
    headers, tenant_id = _auth(test_client)
    await _seed(
        conv_env, tenant_id=tenant_id, session_id="sess-a", website_id="web-a",
        turns=[("user", "Pricing details")],
    )
    await _seed(
        conv_env, tenant_id=tenant_id, session_id="sess-b", website_id="web-b",
        turns=[("user", "Pricing details")],
    )

    response = test_client.get(
        "/api/conversations?search=pricing&website_id=web-b", headers=headers
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == ["sess-b"]


async def test_get_conversation_returns_full_history(client) -> None:
    test_client, conv_env = client
    headers, tenant_id = _auth(test_client)
    await _seed(
        conv_env,
        tenant_id=tenant_id,
        session_id="sess-1",
        turns=[
            ("user", "What are your pricing plans?"),
            ("assistant", "We offer three plans."),
            ("user", "Tell me more"),
        ],
    )

    response = test_client.get("/api/conversations/sess-1", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "sess-1"
    assert body["title"] == "What are your pricing plans?"
    assert body["status"] == "awaiting"  # last turn is a user question
    assert [message["role"] for message in body["messages"]] == ["user", "assistant", "user"]
    assert body["messages"][1]["content"] == "We offer three plans."
    assert body["messages"][1]["sources"] == [
        {"url": "https://example.com/page", "title": "Page", "score": 0.9, "citation": 1}
    ]
    assert body["messages"][1]["response_time"] == 1.25
    assert body["messages"][1]["input_tokens"] == 100
    assert body["messages"][1]["output_tokens"] == 50


async def test_get_conversation_requires_authentication(client) -> None:
    test_client, _ = client
    response = test_client.get("/api/conversations")
    assert response.status_code == 401


async def test_get_conversation_missing_returns_404(client) -> None:
    test_client, _ = client
    headers, _tenant_id = _auth(test_client)
    response = test_client.get("/api/conversations/does-not-exist", headers=headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"


async def test_conversation_isolation_between_tenants(client) -> None:
    test_client, conv_env = client
    owner_headers, owner_tenant = _auth(test_client)
    await _seed(conv_env, tenant_id=owner_tenant, session_id="owner-sess")

    other_headers, _other_tenant = _auth(test_client)

    assert (
        test_client.get("/api/conversations/owner-sess", headers=other_headers).status_code == 404
    )
    assert (
        test_client.delete("/api/conversations/owner-sess", headers=other_headers).status_code
        == 404
    )
    # The owner's conversation is untouched by the foreign tenant's attempts.
    assert (
        test_client.get("/api/conversations/owner-sess", headers=owner_headers).status_code == 200
    )


async def test_delete_conversation_cascades_to_messages_and_soft_deletes_session(
    client,
) -> None:
    test_client, conv_env = client
    headers, tenant_id = _auth(test_client)
    await _seed(
        conv_env,
        tenant_id=tenant_id,
        session_id="sess-1",
        turns=[("user", "Hello"), ("assistant", "Hi there!")],
    )
    await _seed(conv_env, tenant_id=tenant_id, session_id="sess-2", turns=[("user", "Keep")])

    response = test_client.delete("/api/conversations/sess-1", headers=headers)

    assert response.status_code == 204
    # Soft delete: the session row remains as a tombstone but is invisible.
    assert conv_env.sessions.sessions["sess-1"].status == CHAT_SESSION_STATUS_DELETED
    assert set(conv_env.sessions.sessions) == {"sess-1", "sess-2"}
    # Content is purged immediately and the conversation is gone from read paths.
    assert all(message.session_id == "sess-2" for message in conv_env.messages.messages)
    assert test_client.get("/api/conversations/sess-1", headers=headers).status_code == 404
    remaining = test_client.get("/api/conversations", headers=headers).json()
    assert [item["id"] for item in remaining["items"]] == ["sess-2"]
    # The deletion is recorded in the tenant's audit log.
    assert len(conv_env.audit.logs) == 1
    assert conv_env.audit.logs[0].action == AUDIT_CONVERSATION_DELETED
    assert conv_env.audit.logs[0].tenant_id == tenant_id


async def test_delete_conversation_writes_audit_log_with_request_context(client) -> None:
    test_client, conv_env = client
    headers, tenant_id = _auth(test_client)
    await _seed(conv_env, tenant_id=tenant_id, session_id="sess-1", turns=[("user", "Hi")])

    response = test_client.delete(
        "/api/conversations/sess-1", headers={**headers, "User-Agent": "conversations-test"}
    )

    assert response.status_code == 204
    assert conv_env.audit.logs[0].action == AUDIT_CONVERSATION_DELETED
    assert conv_env.audit.logs[0].user_id is not None
    assert conv_env.audit.logs[0].ip_address is not None
    assert conv_env.audit.logs[0].user_agent == "conversations-test"


async def test_delete_conversation_missing_returns_404(client) -> None:
    test_client, _ = client
    headers, _tenant_id = _auth(test_client)
    response = test_client.delete("/api/conversations/missing", headers=headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"
