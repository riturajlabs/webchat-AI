"""End-to-end HTTP tests for the /api/api-keys endpoints using fakes.

Creation is re-enabled (Sprint 2): POST returns the raw `wc_*` secret exactly
once, only its SHA-256 hash is persisted, and revoke is a tenant-scoped soft
delete. List/revoke scenarios seed keys through the fake repository directly.
"""

import asyncio

import pytest
from backend.api.deps import get_api_key_service, get_auth_service
from backend.core.config import get_settings
from backend.core.security import hash_api_key
from backend.main import create_app
from backend.models.api_key import ApiKey
from fastapi.testclient import TestClient

from tests.api_keys_helpers import build_api_keys_env
from tests.auth_helpers import build_auth_env
from tests.http_helpers import register_verified_account

_ACCOUNT_SEQ = 0


@pytest.fixture
def client(monkeypatch):
    """A TestClient whose auth + API key services are backed by in-memory fakes."""
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    get_settings.cache_clear()
    auth_env = build_auth_env()
    api_keys_env = build_api_keys_env()
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: auth_env.service
    app.dependency_overrides[get_api_key_service] = lambda: api_keys_env.service
    with TestClient(app) as test_client:
        yield test_client, api_keys_env
    get_settings.cache_clear()


def _account(test_client: TestClient) -> tuple[dict[str, str], str]:
    """Register + verify a fresh account; returns (bearer headers, tenant_id)."""
    global _ACCOUNT_SEQ
    _ACCOUNT_SEQ += 1
    body = register_verified_account(
        test_client,
        name="Alice",
        email=f"alice{_ACCOUNT_SEQ}@example.com",
    )
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    return headers, body["user"]["tenant_id"]


def _seed_key(env, tenant_id: str, *, name: str) -> str:
    """Seed one active key directly in the fake repository; returns its id.

    The fake repository's `create` is a coroutine, so it is driven with
    `asyncio.run` (these TestClient-based tests are synchronous).
    """
    key = ApiKey.new(
        tenant_id=tenant_id,
        name=name,
        hashed_secret=hash_api_key(f"wc_{tenant_id}_{name}"),
    )
    asyncio.run(env.keys.create(key))
    return key.id


def test_create_api_key_returns_secret_once_and_stores_only_hash(client) -> None:
    test_client, env = client
    headers, tenant_id = _account(test_client)
    response = test_client.post("/api/api-keys", json={"name": "Production"}, headers=headers)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["api_key"].startswith("wc_")
    assert body["key"]["name"] == "Production"
    assert body["key"]["tenant_id"] == tenant_id
    assert body["key"]["status"] == "active"
    # Only the hash is persisted - the raw secret never reaches the DB.
    stored = next(iter(env.keys.keys.values()))
    assert stored.hashed_secret == hash_api_key(body["api_key"])
    assert stored.hashed_secret != body["api_key"]
    # The secret is not leaked through listings either.
    listed = test_client.get("/api/api-keys", headers=headers).json()
    assert all("api_key" not in key for key in listed)


def test_create_api_key_requires_name(client) -> None:
    test_client, _ = client
    headers, _ = _account(test_client)
    response = test_client.post("/api/api-keys", json={"name": "x"}, headers=headers)
    assert response.status_code == 422


def test_create_api_key_requires_authentication(client) -> None:
    test_client, _ = client
    response = test_client.post("/api/api-keys", json={"name": "Production"})
    assert response.status_code == 401


def test_list_api_keys_returns_owned_keys(client) -> None:
    test_client, env = client
    headers, tenant_id = _account(test_client)
    _seed_key(env, tenant_id, name="Production")
    _seed_key(env, tenant_id, name="Staging")

    response = test_client.get("/api/api-keys", headers=headers)

    assert response.status_code == 200
    keys = response.json()
    assert {key["name"] for key in keys} == {"Production", "Staging"}
    assert all(key["status"] == "active" for key in keys)
    # The raw secret must never appear in listings.
    assert all("api_key" not in key for key in keys)


def test_list_api_keys_is_isolated_between_tenants(client) -> None:
    test_client, env = client
    owner_headers, owner_tenant = _account(test_client)
    _seed_key(env, owner_tenant, name="Production")

    other_headers, _ = _account(test_client)
    assert test_client.get("/api/api-keys", headers=other_headers).json() == []
    assert len(test_client.get("/api/api-keys", headers=owner_headers).json()) == 1


def test_revoke_api_key_returns_204(client) -> None:
    test_client, env = client
    headers, tenant_id = _account(test_client)
    key_id = _seed_key(env, tenant_id, name="Production")

    response = test_client.delete(f"/api/api-keys/{key_id}", headers=headers)

    assert response.status_code == 204
    # Soft delete: the record persists with status=revoked and is hidden.
    assert env.keys.keys[key_id].status == "revoked"
    assert test_client.get("/api/api-keys", headers=headers).json() == []
    # Revoking again is idempotent from the client's perspective: the key is
    # already gone, so a second revoke yields 404.
    assert test_client.delete(f"/api/api-keys/{key_id}", headers=headers).status_code == 404


def test_revoke_api_key_missing_returns_404(client) -> None:
    test_client, _ = client
    headers, _ = _account(test_client)
    response = test_client.delete("/api/api-keys/missing-id", headers=headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "API_KEY_NOT_FOUND"


def test_api_key_isolation_between_tenants(client) -> None:
    test_client, env = client
    owner_headers, owner_tenant = _account(test_client)
    key_id = _seed_key(env, owner_tenant, name="Production")

    other_headers, _ = _account(test_client)
    # A foreign tenant cannot revoke or even see the owner's key.
    assert test_client.delete(f"/api/api-keys/{key_id}", headers=other_headers).status_code == 404
    assert env.keys.keys[key_id].status == "active"
