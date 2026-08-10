"""End-to-end HTTP tests for the /api/websites endpoints using fakes."""

import pytest
from backend.api.deps import get_auth_service, get_website_service
from backend.core.config import get_settings
from backend.main import create_app
from fastapi.testclient import TestClient
from tests.auth_helpers import VALID_PASSWORD, build_auth_env
from tests.website_helpers import build_website_env

REGISTER_PAYLOAD = {
    "name": "Alice",
    "email": "alice@example.com",
    "password": VALID_PASSWORD,
}

_ACCOUNT_SEQ = 0


@pytest.fixture
def client(monkeypatch):
    """A TestClient whose auth + website services are backed by in-memory fakes."""
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    get_settings.cache_clear()
    auth_env = build_auth_env()
    website_env = build_website_env()
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: auth_env.service
    app.dependency_overrides[get_website_service] = lambda: website_env.service
    with TestClient(app) as test_client:
        yield test_client, website_env
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


def _create_website(
    test_client: TestClient,
    headers: dict[str, str],
    *,
    url: str = "https://example.com",
    name: str = "Example",
) -> dict:
    response = test_client.post("/api/websites", json={"name": name, "url": url}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def test_create_website_returns_website_widget_secret_and_script(client) -> None:
    test_client, env = client
    body = _create_website(test_client, _auth_headers(test_client))

    website = body["website"]
    assert website["name"] == "Example"
    assert website["url"] == "https://example.com/"
    assert website["status"] == "pending"
    assert website["widget_id"]
    assert body["widget_secret"]
    assert body["embed_script"].startswith("<script src=")
    assert website["widget_id"] in body["embed_script"]
    assert len(env.websites.websites) == 1
    assert len(env.widgets.widgets) == 1


def test_create_website_rejects_invalid_url(client) -> None:
    test_client, _ = client
    headers = _auth_headers(test_client)
    response = test_client.post(
        "/api/websites", json={"name": "Bad", "url": "http://localhost"}, headers=headers
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_URL"


def test_create_website_duplicate_url_returns_409(client) -> None:
    test_client, _ = client
    headers = _auth_headers(test_client)
    payload = {"name": "Example", "url": "https://example.com"}
    assert test_client.post("/api/websites", json=payload, headers=headers).status_code == 201
    response = test_client.post("/api/websites", json=payload, headers=headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "WEBSITE_ALREADY_EXISTS"


def test_create_website_requires_authentication(client) -> None:
    test_client, _ = client
    response = test_client.post(
        "/api/websites", json={"name": "Example", "url": "https://example.com"}
    )
    assert response.status_code == 401


def test_list_websites_returns_owned_sites(client) -> None:
    test_client, _ = client
    headers = _auth_headers(test_client)
    first = _create_website(test_client, headers, url="https://a.example", name="Site A")
    _create_website(test_client, headers, url="https://b.example", name="Site B")

    response = test_client.get("/api/websites", headers=headers)

    assert response.status_code == 200
    websites = response.json()
    assert len(websites) == 2
    assert {website["name"] for website in websites} == {"Site A", "Site B"}
    assert all(website["widget_id"] for website in websites)
    assert first["website"]["id"] in {website["id"] for website in websites}


def test_get_website_detail(client) -> None:
    test_client, _ = client
    headers = _auth_headers(test_client)
    created = _create_website(test_client, headers)
    response = test_client.get(f"/api/websites/{created['website']['id']}", headers=headers)
    assert response.status_code == 200
    assert response.json()["url"] == "https://example.com/"


def test_get_website_missing_returns_404(client) -> None:
    test_client, _ = client
    response = test_client.get("/api/websites/missing-id", headers=_auth_headers(test_client))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "WEBSITE_NOT_FOUND"


def test_website_isolation_between_tenants(client) -> None:
    test_client, _ = client
    owner_headers = _auth_headers(test_client)
    created = _create_website(test_client, owner_headers)

    other_headers = _auth_headers(test_client)
    website_id = created["website"]["id"]
    assert test_client.get(f"/api/websites/{website_id}", headers=other_headers).status_code == 404
    assert (
        test_client.patch(
            f"/api/websites/{website_id}", json={"name": "Hijack"}, headers=other_headers
        ).status_code
        == 404
    )
    assert (
        test_client.delete(f"/api/websites/{website_id}", headers=other_headers).status_code == 404
    )
    # The owner's website is untouched by the foreign tenant's attempts.
    assert test_client.get(f"/api/websites/{website_id}", headers=owner_headers).status_code == 200


def test_update_website_renames(client) -> None:
    test_client, _ = client
    headers = _auth_headers(test_client)
    created = _create_website(test_client, headers, name="Old")
    response = test_client.patch(
        f"/api/websites/{created['website']['id']}",
        json={"name": "Renamed"},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Renamed"


def test_update_website_missing_returns_404(client) -> None:
    test_client, _ = client
    response = test_client.patch(
        "/api/websites/missing-id", json={"name": "Site"}, headers=_auth_headers(test_client)
    )
    assert response.status_code == 404


def test_delete_website_returns_204(client) -> None:
    test_client, env = client
    headers = _auth_headers(test_client)
    created = _create_website(test_client, headers)
    response = test_client.delete(f"/api/websites/{created['website']['id']}", headers=headers)
    assert response.status_code == 204

    # Soft delete: the website record persists with status=deleted and is
    # hidden from listing/get; the widget is removed.
    assert len(env.websites.websites) == 1
    remaining = next(iter(env.websites.websites.values()))
    assert remaining.status == "deleted"
    assert len(env.widgets.widgets) == 0
    assert test_client.get("/api/websites", headers=headers).json() == []
    assert (
        test_client.get(f"/api/websites/{created['website']['id']}", headers=headers).status_code
        == 404
    )


def test_delete_website_missing_returns_404(client) -> None:
    test_client, _ = client
    response = test_client.delete("/api/websites/missing-id", headers=_auth_headers(test_client))
    assert response.status_code == 404


def test_list_websites_filters_by_status(client) -> None:
    test_client, _ = client
    headers = _auth_headers(test_client)
    _create_website(test_client, headers, url="https://a.example", name="Site A")
    _create_website(test_client, headers, url="https://b.example", name="Site B")

    response = test_client.get("/api/websites?status=ready", headers=headers)
    assert response.status_code == 200
    assert response.json() == []
    assert response.headers["X-Total-Count"] == "0"

    response = test_client.get("/api/websites?status=pending", headers=headers)
    assert len(response.json()) == 2
    assert response.headers["X-Total-Count"] == "2"


def test_list_websites_paginates_and_sorts(client) -> None:
    test_client, _ = client
    headers = _auth_headers(test_client)
    _create_website(test_client, headers, url="https://a.example", name="Alpha")
    _create_website(test_client, headers, url="https://b.example", name="Beta")
    _create_website(test_client, headers, url="https://c.example", name="Gamma")

    response = test_client.get(
        "/api/websites?limit=2&offset=0&sort=name&order=asc", headers=headers
    )
    names = [website["name"] for website in response.json()]
    assert names == ["Alpha", "Beta"]
    assert response.headers["X-Total-Count"] == "3"

    response = test_client.get(
        "/api/websites?limit=2&offset=2&sort=name&order=asc", headers=headers
    )
    assert [website["name"] for website in response.json()] == ["Gamma"]

    response = test_client.get("/api/websites?limit=1&sort=name&order=desc", headers=headers)
    assert [website["name"] for website in response.json()] == ["Gamma"]


def test_get_website_widget(client) -> None:
    test_client, _ = client
    headers = _auth_headers(test_client)
    created = _create_website(test_client, headers)
    response = test_client.get(
        f"/api/websites/{created['website']['id']}/widget",
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["widget"]["widget_id"] == created["website"]["widget_id"]
    assert created["website"]["widget_id"] in body["embed_script"]
    assert "widget_secret" not in body["widget"]
