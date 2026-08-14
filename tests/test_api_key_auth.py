"""HTTP tests for `wc_*` API key authentication (Sprint 2).

API keys authenticate as the tenant `owner` on the accepted programmatic
surface - chat stream, conversation list/get/delete, and the analytics reads -
and are rejected everywhere else (website CRUD, widget config, user
management, admin). Only the SHA-256 hash is stored (ADR-004), so these tests
seed keys directly into the fake repository.
"""

from datetime import timedelta

import pytest
from backend.api.deps import (
    get_analytics_service,
    get_api_key_service,
    get_auth_service,
    get_conversation_service,
    get_rag_service,
    get_website_service,
)
from backend.core.config import get_settings
from backend.core.security import hash_api_key, utcnow
from backend.main import create_app
from backend.models.api_key import API_KEY_STATUS_REVOKED, ApiKey
from backend.models.tenant import Tenant
from fastapi.testclient import TestClient

from tests.analytics_helpers import build_analytics_env, seed_day, seed_website
from tests.api_keys_helpers import build_api_keys_env
from tests.auth_helpers import build_auth_env
from tests.chat_helpers import build_chat_env, make_chunk, make_website
from tests.conversations_helpers import build_conversation_env, seed_conversation
from tests.http_helpers import register_verified_account

_ACCOUNT_SEQ = 0


@pytest.fixture
def client(monkeypatch):
    """A TestClient over fakes for auth, api keys, chat, conversations, analytics."""
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    get_settings.cache_clear()
    auth_env = build_auth_env()
    api_keys_env = build_api_keys_env()
    chat_env = build_chat_env()
    conv_env = build_conversation_env()
    analytics_env = build_analytics_env()
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: auth_env.service
    app.dependency_overrides[get_api_key_service] = lambda: api_keys_env.service
    app.dependency_overrides[get_rag_service] = lambda: chat_env.rag
    app.dependency_overrides[get_website_service] = lambda: chat_env.websites_service
    app.dependency_overrides[get_conversation_service] = lambda: conv_env.service
    app.dependency_overrides[get_analytics_service] = lambda: analytics_env.service
    with TestClient(app) as test_client:
        yield test_client, auth_env, api_keys_env, chat_env, conv_env, analytics_env
    get_settings.cache_clear()


def _register(client: TestClient, name: str = "Alice") -> tuple[dict[str, str], str]:
    """Register + verify a fresh account; returns (bearer headers, tenant_id)."""
    global _ACCOUNT_SEQ
    _ACCOUNT_SEQ += 1
    body = register_verified_account(
        client,
        name=name,
        email=f"alice{_ACCOUNT_SEQ}@example.com",
    )
    return {"Authorization": f"Bearer {body['access_token']}"}, body["user"]["tenant_id"]


async def _issue_key(env, tenant_id: str, *, name: str = "Production") -> str:
    """Seed an active key for `tenant_id`; returns its raw `wc_*` secret.

    The owning tenant is also seeded into the api-key service's own tenant
    fake, mirroring `authenticate_api_key`'s live tenant re-check.
    """
    tenant = Tenant.new(company_name="Example Co")
    tenant.id = tenant_id
    await env.tenants.create(tenant)
    raw = f"wc_{tenant_id}_{name}_secret"
    key = ApiKey.new(tenant_id=tenant_id, name=name, hashed_secret=hash_api_key(raw))
    await env.keys.create(key)
    return raw


async def test_valid_api_key_authenticates_as_owner(client) -> None:
    test_client, _, api_keys_env, _, _, analytics_env = client
    _, tenant_id = _register(test_client)
    raw_key = await _issue_key(api_keys_env, tenant_id)

    response = test_client.get(
        "/api/analytics/summary", headers={"Authorization": f"Bearer {raw_key}"}
    )

    assert response.status_code == 200
    assert response.json()["total_conversations"] == 0
    # The key id is now resolvable and its use was audited.
    key = next(iter(api_keys_env.keys.keys.values()))
    assert key.last_used_at is not None
    assert any(log.action == "API_KEY_AUTHENTICATED" for log in api_keys_env.audit.logs)


async def test_valid_api_key_works_across_accepted_endpoints(client) -> None:
    test_client, _, api_keys_env, chat_env, conv_env, analytics_env = client
    _, tenant_id = _register(test_client)
    raw_key = await _issue_key(api_keys_env, tenant_id)
    headers = {"Authorization": f"Bearer {raw_key}"}

    await make_website(chat_env, tenant_id=tenant_id, website_id="web-1", knowledge_chunks=1)
    await make_chunk(chat_env, tenant_id=tenant_id, website_id="web-1", text="Pro and Team plans.")
    await seed_conversation(
        conv_env,
        tenant_id=tenant_id,
        session_id="sess-1",
        turns=[("user", "Pricing?"), ("assistant", "Three plans.")],
    )
    await seed_website(analytics_env, tenant_id=tenant_id, website_id="web-1")

    chat = test_client.post(
        "/api/chat/stream",
        json={"website_id": "web-1", "question": "What plans?"},
        headers=headers,
    )
    assert chat.status_code == 200
    assert chat.headers["content-type"].startswith("text/event-stream")

    conv_list = test_client.get("/api/conversations", headers=headers)
    assert conv_list.status_code == 200
    assert conv_list.json()["items"][0]["id"] == "sess-1"

    conv_detail = test_client.get("/api/conversations/sess-1", headers=headers)
    assert conv_detail.status_code == 200

    summary = test_client.get("/api/analytics/summary", headers=headers)
    timeseries = test_client.get("/api/analytics/timeseries", headers=headers)
    top = test_client.get("/api/analytics/top-websites", headers=headers)
    perf = test_client.get("/api/analytics/performance", headers=headers)
    assert summary.status_code == 200
    assert timeseries.status_code == 200
    assert top.status_code == 200
    assert perf.status_code == 200


async def test_api_key_can_delete_conversation(client) -> None:
    test_client, _, api_keys_env, _, conv_env, _ = client
    _, tenant_id = _register(test_client)
    raw_key = await _issue_key(api_keys_env, tenant_id)
    await seed_conversation(conv_env, tenant_id=tenant_id, session_id="sess-1")

    response = test_client.delete(
        "/api/conversations/sess-1", headers={"Authorization": f"Bearer {raw_key}"}
    )

    assert response.status_code == 204


async def test_invalid_api_key_is_rejected(client) -> None:
    test_client, _, api_keys_env, _, _, _ = client
    _, tenant_id = _register(test_client)
    await _issue_key(api_keys_env, tenant_id)

    response = test_client.get(
        "/api/analytics/summary",
        headers={"Authorization": "Bearer wc_wrong_key"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"
    # Rejections are audited.
    assert any(log.action == "API_KEY_REJECTED" for log in api_keys_env.audit.logs)


async def test_missing_bearer_prefix_is_rejected(client) -> None:
    test_client, _, api_keys_env, _, _, _ = client
    _, tenant_id = _register(test_client)
    raw_key = await _issue_key(api_keys_env, tenant_id)

    # The raw key without `Bearer ` is a malformed Authorization header.
    response = test_client.get("/api/analytics/summary", headers={"Authorization": raw_key})

    assert response.status_code == 401


async def test_revoked_api_key_is_rejected(client) -> None:
    test_client, _, api_keys_env, _, _, _ = client
    _, tenant_id = _register(test_client)
    tenant = Tenant.new(company_name="Example Co")
    tenant.id = tenant_id
    await api_keys_env.tenants.create(tenant)
    raw_key = f"wc_{tenant_id}_revoked_secret"
    key = ApiKey.new(tenant_id=tenant_id, name="Revoked", hashed_secret=hash_api_key(raw_key))
    await api_keys_env.keys.create(key)
    key.status = API_KEY_STATUS_REVOKED

    response = test_client.get(
        "/api/analytics/summary", headers={"Authorization": f"Bearer {raw_key}"}
    )

    assert response.status_code == 401


async def test_api_key_is_isolated_between_tenants(client) -> None:
    test_client, _, api_keys_env, _, conv_env, analytics_env = client
    owner_headers, owner_tenant = _register(test_client)
    _, other_tenant = _register(test_client, name="Bob")
    other_key = await _issue_key(api_keys_env, other_tenant)

    await seed_website(analytics_env, tenant_id=owner_tenant, website_id="web-owner")
    await seed_day(
        analytics_env,
        tenant_id=owner_tenant,
        website_id="web-owner",
        date=utcnow() - timedelta(days=1),
        chats=2,
        messages=4,
    )
    await seed_conversation(conv_env, tenant_id=owner_tenant, session_id="owner-sess")

    # A key owned by another tenant must never see the owner's data.
    other_headers = {"Authorization": f"Bearer {other_key}"}
    summary = test_client.get("/api/analytics/summary", headers=other_headers)
    assert summary.status_code == 200
    assert summary.json()["total_conversations"] == 0

    conv_list = test_client.get("/api/conversations", headers=other_headers)
    assert conv_list.json()["total"] == 0

    # The owner's user session still sees its own data.
    owner_summary = test_client.get("/api/analytics/summary", headers=owner_headers)
    assert owner_summary.json()["total_conversations"] == 2

    # A key cannot address a foreign tenant's conversation by id either.
    detail = test_client.get("/api/conversations/owner-sess", headers=other_headers)
    assert detail.status_code == 404


async def test_api_key_rejected_on_excluded_endpoints(client) -> None:
    """User management, website CRUD, widget config and admin stay user-only."""
    test_client, _, api_keys_env, _, _, _ = client
    _, tenant_id = _register(test_client)
    raw_key = await _issue_key(api_keys_env, tenant_id)
    headers = {"Authorization": f"Bearer {raw_key}"}

    for method, path in (
        ("GET", "/api/websites"),  # website CRUD
        ("GET", "/api/websites/web-1/widget"),  # widget configuration
        ("GET", "/api/api-keys"),  # API-key management stays user-only
        ("GET", "/api/admin/users"),  # user management
        ("GET", "/api/admin/stats"),  # admin APIs
    ):
        response = test_client.request(method, path, headers=headers)
        assert response.status_code == 401, (method, path, response.status_code)


async def test_api_key_rate_limit_is_per_key(monkeypatch) -> None:
    """API-key requests consume a dedicated per-key budget, not the per-IP one."""
    import backend.api.deps as deps

    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("API_KEY_RATE_LIMIT_PER_MINUTE", "2")
    get_settings.cache_clear()
    store = _FakeRateLimitStore()
    monkeypatch.setattr(deps, "get_redis", lambda: store)

    auth_env = build_auth_env()
    api_keys_env = build_api_keys_env()
    analytics_env = build_analytics_env()
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: auth_env.service
    app.dependency_overrides[get_api_key_service] = lambda: api_keys_env.service
    app.dependency_overrides[get_analytics_service] = lambda: analytics_env.service
    with TestClient(app) as test_client:
        _, tenant_id = _register(test_client)
        raw_key = await _issue_key(api_keys_env, tenant_id)
        headers = {"Authorization": f"Bearer {raw_key}"}

        assert test_client.get("/api/analytics/summary", headers=headers).status_code == 200
        assert test_client.get("/api/analytics/summary", headers=headers).status_code == 200
        limited = test_client.get("/api/analytics/summary", headers=headers)
        assert limited.status_code == 429
        assert limited.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"

        # The user (access-token) budget on the same route is untouched.
        user_headers, _ = _register(test_client)
        assert test_client.get("/api/analytics/summary", headers=user_headers).status_code == 200
    get_settings.cache_clear()


class _FakeRateLimitStore:
    """Minimal ZSET-backed sliding-window store (mirrors test_rate_limit)."""

    def __init__(self) -> None:
        self._members: dict[str, dict[str, float]] = {}

    async def zadd(self, name: str, mapping: dict[str, float]) -> int:
        self._members.setdefault(name, {}).update(mapping)
        return len(mapping)

    async def zremrangebyscore(self, name: str, min: int, max: float) -> int:
        members = self._members.get(name, {})
        stale = [k for k, v in members.items() if v <= max]
        for key in stale:
            del members[key]
        return len(stale)

    async def zcard(self, name: str) -> int:
        return len(self._members.get(name, {}))

    async def expire(self, name: str, time: int) -> bool:
        return True
