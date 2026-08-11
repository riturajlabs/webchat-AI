"""End-to-end HTTP tests for the /api/api-keys endpoints using fakes."""

import pytest
from backend.api.deps import get_api_key_service, get_auth_service
from backend.core.config import get_settings
from backend.main import create_app
from fastapi.testclient import TestClient

from tests.api_keys_helpers import build_api_keys_env
from tests.auth_helpers import VALID_PASSWORD, build_auth_env

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


def _auth_headers(test_client: TestClient) -> dict[str, str]:
    """Register a fresh account (unique email) and return bearer headers."""
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


def _create_key(
    test_client: TestClient,
    headers: dict[str, str],
    *,
    name: str = "Production",
) -> dict:
    response = test_client.post("/api/api-keys", json={"name": name}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def test_create_api_key_returns_secret_once(client) -> None:
    test_client, env = client
    body = _create_key(test_client, _auth_headers(test_client), name="Production")

    assert body["key"]["name"] == "Production"
    assert body["key"]["status"] == "active"
    assert body["api_key"].startswith("wc_")
    assert body["key"]["id"]
    assert len(env.keys.keys) == 1
    stored = next(iter(env.keys.keys.values()))
    # Only the hash is persisted; the raw secret can never be recovered.
    assert stored.hashed_secret != body["api_key"]


def test_create_api_key_requires_name(client) -> None:
    test_client, _ = client
    headers = _auth_headers(test_client)
    response = test_client.post("/api/api-keys", json={"name": "x"}, headers=headers)
    assert response.status_code == 422


def test_create_api_key_requires_authentication(client) -> None:
    test_client, _ = client
    response = test_client.post("/api/api-keys", json={"name": "Production"})
    assert response.status_code == 401


def test_list_api_keys_returns_owned_keys(client) -> None:
    test_client, _ = client
    headers = _auth_headers(test_client)
    _create_key(test_client, headers, name="Production")
    _create_key(test_client, headers, name="Staging")

    response = test_client.get("/api/api-keys", headers=headers)

    assert response.status_code == 200
    keys = response.json()
    assert {key["name"] for key in keys} == {"Production", "Staging"}
    assert all(key["status"] == "active" for key in keys)
    # The raw secret must never appear in listings.
    assert all("api_key" not in key for key in keys)


def test_list_api_keys_is_isolated_between_tenants(client) -> None:
    test_client, _ = client
    owner_headers = _auth_headers(test_client)
    _create_key(test_client, owner_headers)

    other_headers = _auth_headers(test_client)
    assert test_client.get("/api/api-keys", headers=other_headers).json() == []
    assert len(test_client.get("/api/api-keys", headers=owner_headers).json()) == 1


def test_revoke_api_key_returns_204(client) -> None:
    test_client, env = client
    headers = _auth_headers(test_client)
    created = _create_key(test_client, headers)
    key_id = created["key"]["id"]

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
    response = test_client.delete("/api/api-keys/missing-id", headers=_auth_headers(test_client))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "API_KEY_NOT_FOUND"


def test_api_key_isolation_between_tenants(client) -> None:
    test_client, env = client
    owner_headers = _auth_headers(test_client)
    created = _create_key(test_client, owner_headers)
    key_id = created["key"]["id"]

    other_headers = _auth_headers(test_client)
    # A foreign tenant cannot revoke or even see the owner's key.
    assert test_client.delete(f"/api/api-keys/{key_id}", headers=other_headers).status_code == 404
    assert env.keys.keys[key_id].status == "active"
