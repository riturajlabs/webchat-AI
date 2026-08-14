"""End-to-end HTTP tests for the /api/chat/stream SSE endpoint (Phase 6)."""

import json

import pytest
from backend.api.deps import get_auth_service, get_rag_service, get_website_service
from backend.core.config import get_settings
from backend.main import create_app
from fastapi.testclient import TestClient

from tests.auth_helpers import build_auth_env
from tests.chat_helpers import build_chat_env, make_chunk, make_website
from tests.http_helpers import register_verified_account

_ACCOUNT_SEQ = 0


@pytest.fixture
def client(monkeypatch):
    """A TestClient whose auth/website/rag services are backed by fakes."""
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    get_settings.cache_clear()
    auth_env = build_auth_env()
    chat_env = build_chat_env()
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: auth_env.service
    app.dependency_overrides[get_website_service] = lambda: chat_env.websites_service
    app.dependency_overrides[get_rag_service] = lambda: chat_env.rag
    with TestClient(app) as test_client:
        yield test_client, auth_env, chat_env
    get_settings.cache_clear()


def _register(test_client: TestClient) -> tuple[dict, dict[str, str]]:
    """Register + verify a fresh account (unique email) and return (user, headers)."""
    global _ACCOUNT_SEQ
    _ACCOUNT_SEQ += 1
    body = register_verified_account(
        test_client,
        name="Alice",
        email=f"alice{_ACCOUNT_SEQ}@example.com",
    )
    return body["user"], {"Authorization": f"Bearer {body['access_token']}"}


def _sse_events(body: str) -> list[tuple[str, dict]]:
    """Parse an SSE response body into (event, data) pairs."""
    events: list[tuple[str, dict]] = []
    for block in body.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        event = None
        data: dict | None = None
        for line in block.split("\n"):
            if line.startswith("event: "):
                event = line[len("event: ") :]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: ") :])
        events.append((event, data))
    return events


def _event_map(events: list[tuple[str, dict]]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for event, data in events:
        grouped.setdefault(event, []).append(data)
    return grouped


async def test_chat_streams_answer_with_sources_and_done(client) -> None:
    test_client, _, chat_env = client
    user, headers = _register(test_client)
    await make_website(
        chat_env,
        tenant_id=user["tenant_id"],
        website_id="web-1",
        knowledge_chunks=1,
    )
    await make_chunk(
        chat_env,
        tenant_id=user["tenant_id"],
        website_id="web-1",
        text="We offer Pro and Team plans.",
    )

    response = test_client.post(
        "/api/chat/stream",
        json={"website_id": "web-1", "question": "What plans do you offer?"},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    events = _sse_events(response.text)
    grouped = _event_map(events)
    assert "sources" in grouped
    assert grouped["sources"][0]["sources"][0]["url"] == "https://example.com/page"
    assert "".join(data["delta"] for data in grouped["message"]) == "Hello world!"
    done = grouped["done"][0]
    assert done["input_tokens"] == 10 and done["output_tokens"] == 20
    assert done["fallback"] is False
    assert "error" not in grouped


async def test_chat_requires_authentication(client) -> None:
    test_client, _, _ = client
    response = test_client.post("/api/chat/stream", json={"website_id": "web-1", "question": "Hi"})
    assert response.status_code == 401


async def test_chat_requires_owner_or_admin_role(client) -> None:
    test_client, auth_env, chat_env = client
    user, headers = _register(test_client)
    # Downgrade the account to viewer: chat must be forbidden (RBAC).
    member = next(iter(auth_env.members.members.values()))
    member.role = "viewer"

    response = test_client.post(
        "/api/chat/stream", json={"website_id": "web-1", "question": "Hi"}, headers=headers
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


async def test_chat_rejects_blank_question(client) -> None:
    test_client, _, _ = client
    _, headers = _register(test_client)
    response = test_client.post(
        "/api/chat/stream",
        json={"website_id": "web-1", "question": "   \t "},
        headers=headers,
    )
    assert response.status_code == 422


async def test_chat_isolates_websites_between_tenants(client) -> None:
    test_client, _, chat_env = client
    owner, owner_headers = _register(test_client)
    await make_website(
        chat_env,
        tenant_id=owner["tenant_id"],
        website_id="web-1",
        knowledge_chunks=1,
    )
    await make_chunk(
        chat_env,
        tenant_id=owner["tenant_id"],
        website_id="web-1",
        text="Owner's private data.",
    )

    _, other_headers = _register(test_client)
    response = test_client.post(
        "/api/chat/stream",
        json={"website_id": "web-1", "question": "Hello?"},
        headers=other_headers,
    )

    assert response.status_code == 200
    grouped = _event_map(_sse_events(response.text))
    assert grouped["error"][0]["code"] == "WEBSITE_NOT_FOUND"
    assert chat_env.generation.calls == []
    # Only the owner's tenant ever saw a session/message.
    assert len(chat_env.messages.messages) == 0


async def test_chat_fallback_streams_error_free_fallback(client) -> None:
    test_client, _, chat_env = client
    user, headers = _register(test_client)
    await make_website(
        chat_env,
        tenant_id=user["tenant_id"],
        website_id="web-1",
        knowledge_chunks=0,
    )

    response = test_client.post(
        "/api/chat/stream",
        json={"website_id": "web-1", "question": "Anything?"},
        headers=headers,
    )

    grouped = _event_map(_sse_events(response.text))
    assert "".join(data["delta"] for data in grouped["message"])
    assert grouped["done"][0]["fallback"] is True
    assert "error" not in grouped
    assert chat_env.generation.calls == []
