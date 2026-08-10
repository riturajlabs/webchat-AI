"""End-to-end HTTP tests for the public widget API (Phase 8, ADR-004).

Covers the three widget surfaces (config / sessions / chat SSE) plus the CORS
isolation contract: `/api/widget/*` gets public `ACAO: *` with no credentials
while the dashboard namespace keeps its strict origin + credentials behavior.
"""

import json

import pytest
from backend.api.deps import (
    get_rag_service,
    get_widget_service,
)
from backend.core.config import get_settings
from backend.core.security import create_widget_session_token
from backend.main import create_app
from backend.models.tenant import Tenant
from backend.models.widget import Widget
from backend.services.widget.widget_service import WidgetService
from fastapi.testclient import TestClient
from tests.chat_helpers import build_chat_env, make_chunk, make_website
from tests.fakes import (
    FakeTenantRepository,
    FakeWebsiteRepository,
    FakeWidgetRepository,
    FakeWidgetStore,
)

WIDGET_ID = "widget-1"
TENANT_ID = "tenant-a"
WEBSITE_ID = "web-1"


def _build_widget_service(websites: FakeWebsiteRepository) -> WidgetService:
    widgets = FakeWidgetRepository()
    tenants = FakeTenantRepository()
    store = FakeWidgetStore()

    widget = Widget.new(tenant_id=TENANT_ID, website_id=WEBSITE_ID)
    widget.widget_id = WIDGET_ID
    widgets.widgets[widget.id] = widget

    tenant = Tenant.new(company_name="Acme")
    tenant.id = TENANT_ID
    tenants.tenants[TENANT_ID] = tenant

    return WidgetService(
        widgets=widgets,
        tenants=tenants,
        websites=websites,
        store=store,
    )


@pytest.fixture
def client(monkeypatch):
    """A TestClient whose widget + rag services are backed by fakes."""
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    get_settings.cache_clear()
    chat_env = build_chat_env()
    widget_service = _build_widget_service(chat_env.websites)
    app = create_app()
    app.dependency_overrides[get_widget_service] = lambda: widget_service
    app.dependency_overrides[get_rag_service] = lambda: chat_env.rag
    with TestClient(app) as test_client:
        yield test_client, widget_service, chat_env
    get_settings.cache_clear()


def _sse_events(body: str) -> list[tuple[str, dict]]:
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


# ---------------------------------------------------------------- config


async def test_widget_config_returns_public_shape(client) -> None:
    test_client, _, _ = client
    response = test_client.get(f"/api/widget/v1/config/{WIDGET_ID}")
    assert response.status_code == 200
    body = response.json()
    assert body["widget_id"] == WIDGET_ID
    assert body["enabled"] is True
    assert body["theme"] == "light"
    assert body["welcome_message"] == "Hi! How can I help you?"
    # Never leaks internal identifiers or secrets.
    assert "tenant_id" not in body
    assert "website_id" not in body
    assert "widget_secret_hash" not in body


async def test_widget_config_unknown_returns_404(client) -> None:
    test_client, _, _ = client
    response = test_client.get("/api/widget/v1/config/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "WIDGET_NOT_FOUND"


# --------------------------------------------------------------- sessions


async def test_widget_sessions_mints_token(client) -> None:
    test_client, _, _ = client
    response = test_client.post(
        "/api/widget/v1/sessions",
        json={"widget_id": WIDGET_ID, "visitor_id": "visitor-1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["session_token"]
    assert body["expires_at"]


async def test_widget_sessions_rejects_unknown_widget(client) -> None:
    test_client, _, _ = client
    response = test_client.post(
        "/api/widget/v1/sessions",
        json={"widget_id": "nope", "visitor_id": "visitor-1"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "WIDGET_NOT_FOUND"


# ----------------------------------------------------------------- chat


async def _ready_website(chat_env) -> None:
    website = await make_website(
        chat_env,
        tenant_id=TENANT_ID,
        website_id=WEBSITE_ID,
        knowledge_chunks=1,
    )
    await make_chunk(
        chat_env,
        tenant_id=TENANT_ID,
        website_id=WEBSITE_ID,
        text="We offer Pro and Team plans.",
    )
    return website


def _chat_headers(visitor_id: str = "visitor-1") -> dict[str, str]:
    token, _ = create_widget_session_token(
        widget_id=WIDGET_ID,
        tenant_id=TENANT_ID,
        website_id=WEBSITE_ID,
        visitor_id=visitor_id,
    )
    return {"Authorization": f"Bearer {token}"}


async def test_widget_chat_streams_answer(client) -> None:
    test_client, _, chat_env = client
    await _ready_website(chat_env)

    response = test_client.post(
        "/api/widget/v1/chat",
        json={"question": "What plans do you offer?"},
        headers=_chat_headers(),
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    grouped = _event_map(_sse_events(response.text))
    assert "sources" in grouped
    assert "".join(data["delta"] for data in grouped["message"]) == "Hello world!"
    assert grouped["done"][0]["fallback"] is False
    assert "error" not in grouped
    # The conversation session id is returned in the done event.
    assert grouped["done"][0]["session_id"]


async def test_widget_chat_requires_bearer_token(client) -> None:
    test_client, _, chat_env = client
    await _ready_website(chat_env)
    response = test_client.post("/api/widget/v1/chat", json={"question": "Hi"})
    assert response.status_code == 401


async def test_widget_chat_rejects_foreign_website_token(client) -> None:
    test_client, _, chat_env = client
    await _ready_website(chat_env)
    foreign_token, _ = create_widget_session_token(
        widget_id=WIDGET_ID,
        tenant_id=TENANT_ID,
        website_id="other-website",
        visitor_id="visitor-1",
    )
    response = test_client.post(
        "/api/widget/v1/chat",
        json={"question": "Hi"},
        headers={"Authorization": f"Bearer {foreign_token}"},
    )
    assert response.status_code == 200
    grouped = _event_map(_sse_events(response.text))
    assert grouped["error"][0]["code"] == "WIDGET_NOT_FOUND"


async def test_widget_chat_rejects_not_ready_website(client) -> None:
    test_client, _, chat_env = client
    website = await make_website(
        chat_env,
        tenant_id=TENANT_ID,
        website_id=WEBSITE_ID,
        knowledge_chunks=0,
    )
    website.status = "pending"

    response = test_client.post(
        "/api/widget/v1/chat",
        json={"question": "Hi"},
        headers=_chat_headers(),
    )
    grouped = _event_map(_sse_events(response.text))
    assert grouped["error"][0]["code"] == "WEBSITE_NOT_READY"


async def test_widget_chat_rejects_spam(client) -> None:
    test_client, _, chat_env = client
    await _ready_website(chat_env)
    response = test_client.post(
        "/api/widget/v1/chat",
        json={"question": "BUY NOW CLICK HERE!!!!!!!"},
        headers=_chat_headers(),
    )
    grouped = _event_map(_sse_events(response.text))
    assert grouped["error"][0]["code"] == "SPAM_REJECTED"


# --------------------------------------------------------------- CORS


def _cors_assertions(response) -> None:
    assert response.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in response.headers
    assert "access-control-allow-methods" in response.headers
    assert "access-control-allow-headers" in response.headers


async def test_widget_cors_preflight_allows_any_origin(client) -> None:
    test_client, _, _ = client
    response = test_client.options(
        "/api/widget/v1/config/widget-1",
        headers={
            "Origin": "https://customer.example",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert response.status_code == 204
    _cors_assertions(response)


async def test_widget_cors_actual_response_has_public_origin(client) -> None:
    test_client, _, _ = client
    response = test_client.get(
        "/api/widget/v1/config/widget-1",
        headers={"Origin": "https://customer.example"},
    )
    assert response.status_code == 200
    _cors_assertions(response)


async def test_dashboard_cors_unchanged_for_disallowed_origin(client) -> None:
    test_client, _, _ = client
    # A health/API path on the dashboard surface from a non-allowed origin must
    # not receive any CORS headers (no wildcard, no credentials).
    response = test_client.get(
        "/api/health",
        headers={"Origin": "https://evil.example"},
    )
    assert "access-control-allow-origin" not in response.headers


async def test_widget_and_dashboard_cors_do_not_bleed(client) -> None:
    test_client, _, _ = client
    widget = test_client.get(
        "/api/widget/v1/config/widget-1",
        headers={"Origin": "https://localhost:3000"},
    )
    _cors_assertions(widget)

    dashboard = test_client.get(
        "/api/health",
        headers={"Origin": "https://localhost:3000"},
    )
    assert dashboard.headers.get("access-control-allow-origin") != "*"
