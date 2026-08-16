"""End-to-end HTTP tests for the public widget API (Phase 8, ADR-004).

Covers the three widget surfaces (config / sessions / chat SSE) plus the CORS
isolation contract: `/api/widget/*` gets public `ACAO: *` with no credentials
while the dashboard namespace keeps its strict origin + credentials behavior.
"""

import json

import pytest
from backend.api.deps import (
    get_feedback_service,
    get_rag_service,
    get_usage_service,
    get_widget_service,
)
from backend.core.config import get_settings
from backend.core.security import create_widget_session_token
from backend.main import create_app
from backend.models.tenant import Tenant
from backend.models.widget import Widget
from backend.services.feedback.feedback_service import FeedbackService
from backend.services.widget.widget_service import WidgetService
from fastapi.testclient import TestClient

from tests.billing_helpers import build_billing_env
from tests.chat_helpers import build_chat_env, make_chunk, make_website
from tests.fakes import (
    FakeFeedbackRepository,
    FakeTenantRepository,
    FakeWebsiteRepository,
    FakeWidgetRepository,
    FakeWidgetStore,
)

WIDGET_ID = "widget-1"
TENANT_ID = "tenant-a"
WEBSITE_ID = "web-1"


def _build_widget_service(
    websites: FakeWebsiteRepository,
    *,
    tenant_status: str = "active",
    widget_enabled: bool = True,
    allowed_domains: list[str] | None = None,
    tenants: FakeTenantRepository | None = None,
) -> WidgetService:
    widgets = FakeWidgetRepository()
    tenants = tenants or FakeTenantRepository()
    store = FakeWidgetStore()

    widget = Widget.new(tenant_id=TENANT_ID, website_id=WEBSITE_ID)
    widget.widget_id = WIDGET_ID
    widget.enabled = widget_enabled
    # The CORS tests embed from `customer.example`; under the strict allowlist
    # policy an empty allowlist would reject it (WIDGET_DOMAIN_NOT_CONFIGURED),
    # so the default fixture widget explicitly permits that customer origin.
    widget.allowed_domains = list(allowed_domains or ["customer.example"])
    widgets.widgets[widget.id] = widget

    tenant = Tenant.new(company_name="Acme")
    tenant.id = TENANT_ID
    tenant.status = tenant_status
    tenants.tenants[TENANT_ID] = tenant

    return WidgetService(
        widgets=widgets,
        tenants=tenants,
        websites=websites,
        store=store,
    )


def _app_with_service(
    widget_service: WidgetService,
    chat_env,
    usage=None,
) -> TestClient:
    feedback_service = FeedbackService(
        feedback=FakeFeedbackRepository(),
        messages=chat_env.messages,
    )
    app = create_app()
    app.dependency_overrides[get_widget_service] = lambda: widget_service
    app.dependency_overrides[get_rag_service] = lambda: chat_env.rag
    app.dependency_overrides[get_feedback_service] = lambda: feedback_service
    if usage is not None:
        app.dependency_overrides[get_usage_service] = lambda: usage
    return TestClient(app)


@pytest.fixture
def client(monkeypatch):
    """A TestClient whose widget + rag services are backed by fakes."""
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    # Hermetic: a developer's .env may enable the widget limiter (which needs
    # live Redis); the fakes below don't provide one, so pin it off here.
    monkeypatch.setenv("WIDGET_RATE_LIMIT_ENABLED", "false")
    get_settings.cache_clear()
    chat_env = build_chat_env()
    tenants = FakeTenantRepository()
    widget_service = _build_widget_service(chat_env.websites, tenants=tenants)
    billing_env = build_billing_env(tenants)
    # The feedback service shares the chat message repo so a visitor can rate a
    # message the chat flow actually produced.
    feedback_service = FeedbackService(
        feedback=FakeFeedbackRepository(),
        messages=chat_env.messages,
    )
    app = create_app()
    app.dependency_overrides[get_widget_service] = lambda: widget_service
    app.dependency_overrides[get_rag_service] = lambda: chat_env.rag
    app.dependency_overrides[get_feedback_service] = lambda: feedback_service
    app.dependency_overrides[get_usage_service] = lambda: billing_env.service
    with TestClient(app) as test_client:
        yield test_client, widget_service, chat_env, feedback_service
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
    test_client, _, _, _ = client
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


async def test_widget_config_includes_branding_defaults(client) -> None:
    """Phase 11.6 branding fields ride on the public config with sane defaults."""
    test_client, _, _, _ = client
    response = test_client.get(f"/api/widget/v1/config/{WIDGET_ID}")
    assert response.status_code == 200
    body = response.json()
    assert body["bot_name"] == "WebChat AI"
    assert body["bot_status_text"] == "Online"
    assert body["header_color"] is None
    assert body["secondary_color"] is None
    assert body["background_color"] is None
    assert body["text_color"] is None
    assert body["font_family"] is None
    assert body["theme_preset"] == ""
    assert body["width"] == "380px"
    assert body["height"] == "600px"
    assert body["border_radius"] == "20px"
    assert body["launcher_size"] == "58px"


async def test_widget_config_unknown_returns_404(client) -> None:
    test_client, _, _, _ = client
    response = test_client.get("/api/widget/v1/config/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "WIDGET_NOT_FOUND"


async def test_widget_config_reports_enabled_false_for_suspended_tenant(monkeypatch) -> None:
    """A suspended tenant must not leak via a 403 (ADR-005); it reads as a
    disabled widget so the embed surfaces 'assistant unavailable' instead."""
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("WIDGET_RATE_LIMIT_ENABLED", "false")
    get_settings.cache_clear()
    service = _build_widget_service(chat_env := build_chat_env(), tenant_status="suspended")
    with _app_with_service(service, chat_env) as test_client:
        response = test_client.get(f"/api/widget/v1/config/{WIDGET_ID}")
    assert response.status_code == 200
    assert response.json()["enabled"] is False
    get_settings.cache_clear()


async def test_widget_config_reports_enabled_false_for_disabled_widget(monkeypatch) -> None:
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("WIDGET_RATE_LIMIT_ENABLED", "false")
    get_settings.cache_clear()
    chat_env = build_chat_env()
    service = _build_widget_service(chat_env, widget_enabled=False)
    with _app_with_service(service, chat_env) as test_client:
        response = test_client.get(f"/api/widget/v1/config/{WIDGET_ID}")
    assert response.status_code == 200
    assert response.json()["enabled"] is False
    get_settings.cache_clear()


# --------------------------------------------------------------- sessions


async def test_widget_sessions_mints_token(client) -> None:
    test_client, _, _, _ = client
    response = test_client.post(
        "/api/widget/v1/sessions",
        json={"widget_id": WIDGET_ID, "visitor_id": "visitor-1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["session_token"]
    assert body["expires_at"]


async def test_widget_sessions_rejects_unknown_widget(client) -> None:
    test_client, _, _, _ = client
    response = test_client.post(
        "/api/widget/v1/sessions",
        json={"widget_id": "nope", "visitor_id": "visitor-1"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "WIDGET_NOT_FOUND"


async def test_widget_sessions_rejects_disabled_widget(monkeypatch) -> None:
    """The config endpoint reads a disabled widget as enabled=false, but a
    disabled widget can never mint a session token (403 WIDGET_DISABLED)."""
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("WIDGET_RATE_LIMIT_ENABLED", "false")
    get_settings.cache_clear()
    chat_env = build_chat_env()
    service = _build_widget_service(chat_env, widget_enabled=False)
    with _app_with_service(service, chat_env) as test_client:
        response = test_client.post(
            "/api/widget/v1/sessions",
            json={"widget_id": WIDGET_ID, "visitor_id": "visitor-1"},
        )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "WIDGET_DISABLED"
    get_settings.cache_clear()


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
    test_client, _, chat_env, _ = client
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
    test_client, _, chat_env, _ = client
    await _ready_website(chat_env)
    response = test_client.post("/api/widget/v1/chat", json={"question": "Hi"})
    assert response.status_code == 401


async def test_widget_chat_rejects_foreign_website_token(client) -> None:
    test_client, _, chat_env, _ = client
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
    test_client, _, chat_env, _ = client
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
    test_client, _, chat_env, _ = client
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
    test_client, _, _, _ = client
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
    test_client, _, _, _ = client
    response = test_client.get(
        "/api/widget/v1/config/widget-1",
        headers={"Origin": "https://customer.example"},
    )
    assert response.status_code == 200
    _cors_assertions(response)


async def test_dashboard_cors_unchanged_for_disallowed_origin(client) -> None:
    test_client, _, _, _ = client
    # A health/API path on the dashboard surface from a non-allowed origin must
    # not receive any CORS headers (no wildcard, no credentials).
    response = test_client.get(
        "/api/health",
        headers={"Origin": "https://evil.example"},
    )
    assert "access-control-allow-origin" not in response.headers


async def test_widget_and_dashboard_cors_do_not_bleed(client) -> None:
    test_client, _, _, _ = client
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


async def test_widget_cors_for_origin_listed_in_cors_origins(client) -> None:
    # A dev site origin in `cors_origins` (e.g. Live Server on :5500) makes the
    # inner dashboard CORSMiddleware emit a credentials-scoped origin; the
    # widget surface must still answer with the public `ACAO: *` and never a
    # credential header, so the browser shows no CORS errors.
    test_client, _, _, _ = client
    widget = test_client.get(
        "/api/widget/v1/config/widget-1",
        headers={"Origin": "http://localhost:5500"},
    )
    _cors_assertions(widget)


# ------------------------------------------------------------- feedback


def _feedback_headers(visitor_id: str = "visitor-1") -> dict[str, str]:
    token, _ = create_widget_session_token(
        widget_id=WIDGET_ID,
        tenant_id=TENANT_ID,
        website_id=WEBSITE_ID,
        visitor_id=visitor_id,
    )
    return {"Authorization": f"Bearer {token}"}


async def test_widget_feedback_accepts_rating(client) -> None:
    test_client, _, chat_env, feedback_service = client
    await _ready_website(chat_env)
    response = test_client.post(
        "/api/widget/v1/chat",
        json={"question": "What plans do you offer?"},
        headers=_chat_headers(),
    )
    grouped = _event_map(_sse_events(response.text))
    message_id = grouped["done"][0]["message_id"]
    session_id = grouped["done"][0]["session_id"]

    result = test_client.post(
        "/api/widget/v1/feedback",
        json={
            "session_id": session_id,
            "message_id": message_id,
            "rating": 5,
            "category": "helpful",
            "comment": "Really useful",
        },
        headers=_feedback_headers(),
    )

    assert result.status_code == 204
    stored = feedback_service._feedback.feedback  # noqa: SLF001
    assert len(stored) == 1
    assert stored[0].message_id == message_id
    assert stored[0].rating == 5
    assert stored[0].category == "helpful"
    assert stored[0].comment == "Really useful"


async def test_widget_feedback_requires_bearer_token(client) -> None:
    test_client, _, chat_env, _ = client
    await _ready_website(chat_env)
    response = test_client.post(
        "/api/widget/v1/feedback",
        json={
            "session_id": "s",
            "message_id": "m",
            "rating": 4,
            "category": "helpful",
        },
    )
    assert response.status_code == 401


async def test_widget_feedback_rejects_unknown_message(client) -> None:
    test_client, _, chat_env, feedback_service = client
    await _ready_website(chat_env)
    result = test_client.post(
        "/api/widget/v1/feedback",
        json={
            "session_id": "session-1",
            "message_id": "missing-message",
            "rating": 4,
            "category": "helpful",
        },
        headers=_feedback_headers(),
    )
    assert result.status_code == 404
    assert result.json()["error"]["code"] == "MESSAGE_NOT_FOUND"
    assert feedback_service._feedback.feedback == []  # noqa: SLF001


async def test_widget_feedback_rejects_foreign_website_token(client) -> None:
    test_client, _, chat_env, feedback_service = client
    await _ready_website(chat_env)
    response = test_client.post(
        "/api/widget/v1/chat",
        json={"question": "What plans do you offer?"},
        headers=_chat_headers(),
    )
    grouped = _event_map(_sse_events(response.text))
    message_id = grouped["done"][0]["message_id"]
    session_id = grouped["done"][0]["session_id"]

    foreign_token, _ = create_widget_session_token(
        widget_id=WIDGET_ID,
        tenant_id=TENANT_ID,
        website_id="other-website",
        visitor_id="visitor-1",
    )
    result = test_client.post(
        "/api/widget/v1/feedback",
        json={
            "session_id": session_id,
            "message_id": message_id,
            "rating": 4,
            "category": "helpful",
        },
        headers={"Authorization": f"Bearer {foreign_token}"},
    )

    assert result.status_code == 404
    assert result.json()["error"]["code"] == "MESSAGE_NOT_FOUND"
    assert feedback_service._feedback.feedback == []  # noqa: SLF001


async def test_widget_feedback_validates_rating_and_category(client) -> None:
    test_client, _, chat_env, _ = client
    await _ready_website(chat_env)
    response = test_client.post(
        "/api/widget/v1/chat",
        json={"question": "What plans do you offer?"},
        headers=_chat_headers(),
    )
    grouped = _event_map(_sse_events(response.text))
    payload = {
        "session_id": grouped["done"][0]["session_id"],
        "message_id": grouped["done"][0]["message_id"],
        "rating": 4,
        "category": "helpful",
    }
    headers = _feedback_headers()

    assert (
        test_client.post(
            "/api/widget/v1/feedback",
            json={**payload, "rating": 6},
            headers=headers,
        ).status_code
        == 422
    )
    assert (
        test_client.post(
            "/api/widget/v1/feedback",
            json={**payload, "category": "bogus"},
            headers=headers,
        ).status_code
        == 422
    )


async def test_widget_feedback_is_idempotent_per_message(client) -> None:
    test_client, _, chat_env, feedback_service = client
    await _ready_website(chat_env)
    response = test_client.post(
        "/api/widget/v1/chat",
        json={"question": "What plans do you offer?"},
        headers=_chat_headers(),
    )
    grouped = _event_map(_sse_events(response.text))
    payload = {
        "session_id": grouped["done"][0]["session_id"],
        "message_id": grouped["done"][0]["message_id"],
        "rating": 3,
        "category": "incomplete",
    }

    for _ in range(2):
        result = test_client.post(
            "/api/widget/v1/feedback", json=payload, headers=_feedback_headers()
        )
        assert result.status_code == 204

    assert len(feedback_service._feedback.feedback) == 1  # noqa: SLF001
