"""End-to-end HTTP tests for the dashboard widget customization API (Phase 11.5).

Covers the widget builder write path (`PATCH /api/websites/{id}/widget`):
apply changes, partial updates, request validation, tenant isolation and
authentication. Uses in-memory fakes so no MongoDB/Redis is required.
"""

import pytest
from backend.api.deps import (
    get_auth_service,
    get_website_service,
    get_widget_config_service,
)
from backend.core.config import get_settings
from backend.main import create_app
from backend.models.audit_log import AUDIT_WIDGET_UPDATED
from backend.services.widget import WidgetConfigService
from fastapi.testclient import TestClient

from tests.auth_helpers import build_auth_env
from tests.http_helpers import register_verified
from tests.website_helpers import build_website_env

_ACCOUNT_SEQ = 0


@pytest.fixture
def client(monkeypatch):
    """A TestClient whose auth + website + widget-config services are fakes."""
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    get_settings.cache_clear()

    auth_env = build_auth_env()
    website_env = build_website_env()

    invalidated: list[str] = []

    async def _invalidate(widget_id: str) -> None:
        invalidated.append(widget_id)

    config_service = WidgetConfigService(
        widgets=website_env.widgets,
        audit=website_env.audit,
        invalidate_public_config=_invalidate,
    )

    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: auth_env.service
    app.dependency_overrides[get_website_service] = lambda: website_env.service
    app.dependency_overrides[get_widget_config_service] = lambda: config_service
    with TestClient(app) as test_client:
        yield test_client, website_env, invalidated
    get_settings.cache_clear()


def _auth_headers(test_client: TestClient) -> dict[str, str]:
    global _ACCOUNT_SEQ
    _ACCOUNT_SEQ += 1
    return register_verified(
        test_client,
        name="Alice",
        email=f"alice{_ACCOUNT_SEQ}@example.com",
    )


def _create_website(test_client: TestClient, headers: dict[str, str]) -> dict:
    response = test_client.post(
        "/api/websites", json={"name": "Example", "url": "https://example.com"}, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()


FULL_PAYLOAD = {
    "theme": "dark",
    "position": "bottom-left",
    "primary_color": "#000000",
    "accent_color": "#ffffff",
    "font_size": "lg",
    "logo_url": "https://cdn.example.com/logo.png",
    "avatar_url": "https://cdn.example.com/avatar.png",
    "welcome_message": "Hello!",
    "placeholder": "Ask anything",
    "suggested_questions": ["Question 1", "Question 2"],
    "branding": True,
    "dark_mode": False,
    "auto_open": True,
}


def test_update_widget_config_applies_changes(client) -> None:
    test_client, env, invalidated = client
    headers = _auth_headers(test_client)
    created = _create_website(test_client, headers)
    website_id = created["website"]["id"]

    response = test_client.patch(
        f"/api/websites/{website_id}/widget", json=FULL_PAYLOAD, headers=headers
    )

    assert response.status_code == 200
    body = response.json()
    widget = body["widget"]
    assert widget["widget_id"] == created["website"]["widget_id"]
    assert widget["theme"] == "dark"
    assert widget["position"] == "bottom-left"
    assert widget["primary_color"] == "#000000"
    assert widget["accent_color"] == "#ffffff"
    assert widget["font_size"] == "lg"
    assert widget["logo_url"] == "https://cdn.example.com/logo.png"
    assert widget["avatar_url"] == "https://cdn.example.com/avatar.png"
    assert widget["welcome_message"] == "Hello!"
    assert widget["placeholder"] == "Ask anything"
    assert widget["suggested_questions"] == ["Question 1", "Question 2"]
    assert widget["branding"] is True
    assert widget["dark_mode"] is False
    assert widget["auto_open"] is True
    # The embed script stays intact and references the public widget id.
    assert created["website"]["widget_id"] in body["embed_script"]

    # The repository document reflects the update.
    stored = next(iter(env.widgets.widgets.values()))
    assert stored.primary_color == "#000000"
    assert stored.welcome_message == "Hello!"
    # Audit trail + public config cache invalidation.
    assert any(log.action == AUDIT_WIDGET_UPDATED for log in env.audit.logs)
    assert invalidated == [created["website"]["widget_id"]]


def test_update_widget_config_partial(client) -> None:
    test_client, env, invalidated = client
    headers = _auth_headers(test_client)
    created = _create_website(test_client, headers)
    website_id = created["website"]["id"]

    response = test_client.patch(
        f"/api/websites/{website_id}/widget",
        json={"primary_color": "#ff0000"},
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    # Only the sent field changed; the rest is untouched.
    assert body["widget"]["primary_color"] == "#ff0000"
    assert body["widget"]["theme"] == "light"
    assert body["widget"]["welcome_message"] == "Hi! How can I help you?"
    stored = next(iter(env.widgets.widgets.values()))
    assert stored.primary_color == "#ff0000"
    assert stored.theme == "light"
    assert invalidated == [created["website"]["widget_id"]]


def test_update_widget_config_clears_logo_with_empty_string(client) -> None:
    test_client, env, _ = client
    headers = _auth_headers(test_client)
    created = _create_website(test_client, headers)
    website_id = created["website"]["id"]

    first = test_client.patch(
        f"/api/websites/{website_id}/widget",
        json={"logo_url": "https://cdn.example.com/logo.png"},
        headers=headers,
    )
    assert first.status_code == 200
    assert first.json()["widget"]["logo_url"] == "https://cdn.example.com/logo.png"

    cleared = test_client.patch(
        f"/api/websites/{website_id}/widget",
        json={"logo_url": ""},
        headers=headers,
    )
    assert cleared.status_code == 200
    assert cleared.json()["widget"]["logo_url"] is None
    assert next(iter(env.widgets.widgets.values())).logo_url is None


def test_update_widget_config_validation(client) -> None:
    test_client, _, _ = client
    headers = _auth_headers(test_client)
    created = _create_website(test_client, headers)
    website_id = created["website"]["id"]

    cases = [
        ({"primary_color": "red"}, "invalid hex color"),
        ({"theme": "neon"}, "invalid theme enum"),
        ({"position": "top-center"}, "invalid position enum"),
        ({"font_size": "xl"}, "invalid font size enum"),
        ({"logo_url": "ftp://cdn.example.com/logo.png"}, "invalid URL scheme"),
        ({"logo_url": "not-a-url"}, "invalid URL"),
        ({"suggested_questions": ["a", "b", "c", "d", "e", "f"]}, "too many suggested questions"),
        ({"suggested_questions": [""]}, "blank suggested question"),
        ({"welcome_message": "x" * 501}, "welcome message too long"),
        ({"placeholder": "x" * 121}, "placeholder too long"),
        ({}, "empty patch body"),
    ]
    for payload, _label in cases:
        response = test_client.patch(
            f"/api/websites/{website_id}/widget", json=payload, headers=headers
        )
        assert response.status_code == 422, f"expected 422 for {payload}"


def test_update_widget_config_tenant_isolation(client) -> None:
    test_client, env, _ = client
    owner_headers = _auth_headers(test_client)
    created = _create_website(test_client, owner_headers)
    website_id = created["website"]["id"]

    other_headers = _auth_headers(test_client)
    response = test_client.patch(
        f"/api/websites/{website_id}/widget",
        json={"welcome_message": "Hijacked"},
        headers=other_headers,
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "WEBSITE_NOT_FOUND"

    # The owner's widget was not modified.
    stored = next(iter(env.widgets.widgets.values()))
    assert stored.welcome_message == "Hi! How can I help you?"


def test_update_widget_config_missing_website_returns_404(client) -> None:
    test_client, _, _ = client
    response = test_client.patch(
        "/api/websites/missing-id/widget",
        json={"welcome_message": "Hi"},
        headers=_auth_headers(test_client),
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "WEBSITE_NOT_FOUND"


def test_update_widget_config_requires_authentication(client) -> None:
    test_client, _, _ = client
    response = test_client.patch(
        "/api/websites/some-id/widget", json={"welcome_message": "Hi"}
    )
    assert response.status_code == 401


def test_update_widget_allowed_domains_normalizes_and_stores(client) -> None:
    test_client, env, invalidated = client
    headers = _auth_headers(test_client)
    created = _create_website(test_client, headers)
    website_id = created["website"]["id"]

    response = test_client.patch(
        f"/api/websites/{website_id}/widget",
        json={
            "allowed_domains": [
                "Acme.Example",
                "*.Sub.Example",
                "example.com:8080",  # port rejected -> entry dropped
            ]
        },
        headers=headers,
    )
    assert response.status_code == 422  # dropped entries fail loudly


async def test_widget_allowed_domains_stored_after_patch(client) -> None:
    test_client, env, invalidated = client
    headers = _auth_headers(test_client)
    created = _create_website(test_client, headers)
    website_id = created["website"]["id"]

    response = test_client.patch(
        f"/api/websites/{website_id}/widget",
        json={"allowed_domains": ["acme.example", "*.store.example"]},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["widget"]["allowed_domains"] == ["acme.example", "*.store.example"]
    stored = next(iter(env.widgets.widgets.values()))
    assert stored.allowed_domains == ["acme.example", "*.store.example"]
    assert invalidated == [created["website"]["widget_id"]]


def test_get_widget_exposes_allowed_domains(client) -> None:
    test_client, env, _ = client
    headers = _auth_headers(test_client)
    created = _create_website(test_client, headers)
    website_id = created["website"]["id"]

    # The widget is seeded with the website's host, so the GET response must
    # expose the current allowlist for the dashboard to render it.
    response = test_client.get(f"/api/websites/{website_id}/widget", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert "allowed_domains" in body["widget"]
    assert body["widget"]["allowed_domains"] == ["example.com"]

    patched = test_client.patch(
        f"/api/websites/{website_id}/widget",
        json={"allowed_domains": ["acme.example", "*.store.example"]},
        headers=headers,
    )
    assert patched.status_code == 200
    assert patched.json()["widget"]["allowed_domains"] == ["acme.example", "*.store.example"]


async def test_widget_allowed_domains_cleared_by_empty_list(client) -> None:
    test_client, env, _ = client
    headers = _auth_headers(test_client)
    created = _create_website(test_client, headers)
    website_id = created["website"]["id"]

    seeded = test_client.patch(
        f"/api/websites/{website_id}/widget",
        json={"allowed_domains": ["acme.example"]},
        headers=headers,
    )
    assert seeded.status_code == 200

    cleared = test_client.patch(
        f"/api/websites/{website_id}/widget",
        json={"allowed_domains": []},
        headers=headers,
    )
    assert cleared.status_code == 200
    assert cleared.json()["widget"]["allowed_domains"] == []
    assert next(iter(env.widgets.widgets.values())).allowed_domains == []


def test_update_widget_allowed_domains_validation(client) -> None:
    test_client, _, _ = client
    headers = _auth_headers(test_client)
    created = _create_website(test_client, headers)
    website_id = created["website"]["id"]

    cases = [
        ({"allowed_domains": [f"a{i}.example.com" for i in range(51)]}, "too many domains"),
        ({"allowed_domains": ["https://example.com"]}, "scheme not a hostname"),
        ({"allowed_domains": ["example.com/path"]}, "path in hostname"),
        ({"allowed_domains": ["example.com:8080"]}, "port in hostname"),
        ({"allowed_domains": ["not a hostname"]}, "spaces in hostname"),
    ]
    for payload, _label in cases:
        response = test_client.patch(
            f"/api/websites/{website_id}/widget", json=payload, headers=headers
        )
        assert response.status_code == 422, f"expected 422 for {payload}"
