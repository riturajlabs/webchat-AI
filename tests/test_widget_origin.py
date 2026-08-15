"""End-to-end tests for the widget embed-origin allowlist (production hardening).

A widget with a non-empty `allowed_domains` may only be embedded by browser
pages whose `Origin` hostname is listed. The widget surface still answers
`ACAO: *` (that cannot express an allowlist), so enforcement is
application-level: every widget route rejects mismatched origins with
`403 WIDGET_ORIGIN_NOT_ALLOWED`. Requests without an `Origin` header (curl /
server-to-server) are not browser embeds and stay permitted.

An empty allowlist is now *blocking*: browser embeds get
`403 WIDGET_DOMAIN_NOT_CONFIGURED` until domains are configured. The literal
`*` entry is the explicit open-embedding opt-in. In `development` the loopback
hosts (`localhost` / `127.0.0.1`) are auto-permitted so a developer can test an
embed without editing the allowlist; production never auto-permits them.
"""

import pytest
from backend.api.deps import (
    get_feedback_service,
    get_rag_service,
    get_usage_service,
    get_widget_service,
)
from backend.core.config import Settings, get_settings
from backend.core.security import create_widget_session_token
from backend.main import create_app
from backend.models.tenant import Tenant
from backend.models.widget import Widget
from backend.services.feedback.feedback_service import FeedbackService
from backend.services.widget.widget_service import WidgetService
from fastapi.testclient import TestClient

from tests.billing_helpers import build_billing_env
from tests.chat_helpers import ChatEnv, build_chat_env, make_chunk, make_website
from tests.fakes import (
    FakeFeedbackRepository,
    FakeTenantRepository,
    FakeWebsiteRepository,
    FakeWidgetRepository,
    FakeWidgetStore,
)

WIDGET_ID = "widget-origin-1"
TENANT_ID = "tenant-origin"
WEBSITE_ID = "web-origin-1"
ALLOWED = ["acme.example"]


def _prod_settings() -> Settings:
    """Production settings that pass the startup security validator."""
    return Settings(
        _env_file=None,
        environment="production",
        jwt_secret="x" * 40,
        gemini_api_key="test-key",
        embedding_provider_order=["gemini"],
        embedding_dimensions=768,
        widget_script_url="https://cdn.example.com/webchat-widget.iife.min.js",
        # Real production dashboard origins; localhost is not auto-permitted.
        cors_origins=["https://app.example.com"],
        payment_provider="stripe",
        stripe_secret_key="sk_test",
        stripe_webhook_secret="whsec_test",
    )


def _build_widget_service(
    websites: FakeWebsiteRepository,
    allowed_domains: list[str],
    settings: Settings | None = None,
    tenants: FakeTenantRepository | None = None,
) -> WidgetService:
    widgets = FakeWidgetRepository()
    tenants = tenants or FakeTenantRepository()
    store = FakeWidgetStore()

    widget = Widget.new(tenant_id=TENANT_ID, website_id=WEBSITE_ID)
    widget.widget_id = WIDGET_ID
    widget.allowed_domains = list(allowed_domains)
    widgets.widgets[widget.id] = widget

    tenant = Tenant.new(company_name="Acme")
    tenant.id = TENANT_ID
    tenants.tenants[TENANT_ID] = tenant

    return WidgetService(
        widgets=widgets,
        tenants=tenants,
        websites=websites,
        store=store,
        settings=settings,
    )


def _build_client(
    monkeypatch,
    allowed_domains: list[str],
    *,
    settings: Settings | None = None,
) -> tuple[TestClient, WidgetService, ChatEnv]:
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("WIDGET_RATE_LIMIT_ENABLED", "false")
    # Deterministic regardless of a local `.env` (which may set production).
    if settings is None:
        monkeypatch.setenv("ENVIRONMENT", "development")
    get_settings.cache_clear()
    chat_env = build_chat_env()
    tenants = FakeTenantRepository()
    widget_service = _build_widget_service(
        chat_env.websites, allowed_domains, settings, tenants=tenants
    )
    billing_env = build_billing_env(tenants)
    feedback_service = FeedbackService(
        feedback=FakeFeedbackRepository(),
        messages=chat_env.messages,
    )
    app = create_app()
    app.dependency_overrides[get_widget_service] = lambda: widget_service
    app.dependency_overrides[get_rag_service] = lambda: chat_env.rag
    app.dependency_overrides[get_feedback_service] = lambda: feedback_service
    app.dependency_overrides[get_usage_service] = lambda: billing_env.service
    return TestClient(app), widget_service, chat_env


@pytest.fixture
def client(monkeypatch):
    """TestClient whose widget service uses a widget with an allowlist (dev)."""
    test_client, widget_service, chat_env = _build_client(monkeypatch, ALLOWED)
    with test_client:
        yield test_client, widget_service, chat_env
    get_settings.cache_clear()


@pytest.fixture
def unconfigured_client(monkeypatch):
    """Widget with an empty allowlist (dev)."""
    test_client, _, _ = _build_client(monkeypatch, [])
    with test_client:
        yield test_client
    get_settings.cache_clear()


@pytest.fixture
def production_client(monkeypatch):
    """Widget with an allowlist under production settings."""
    test_client, _, _ = _build_client(monkeypatch, ALLOWED, settings=_prod_settings())
    with test_client:
        yield test_client
    get_settings.cache_clear()


async def _ready_website(chat_env) -> None:
    await make_website(
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


def _token() -> str:
    token, _ = create_widget_session_token(
        widget_id=WIDGET_ID,
        tenant_id=TENANT_ID,
        website_id=WEBSITE_ID,
        visitor_id="visitor-origin",
    )
    return f"Bearer {token}"


def _headers(**extra: str) -> dict[str, str]:
    return {"Origin": "https://acme.example", **extra}


# ------------------------------------------------------------ allowed flow


async def test_allowed_origin_full_flow(client) -> None:
    test_client, _, chat_env = client
    await _ready_website(chat_env)

    config = test_client.get(
        f"/api/widget/v1/config/{WIDGET_ID}", headers=_headers()
    )
    assert config.status_code == 200
    assert config.headers["access-control-allow-origin"] == "*"

    session = test_client.post(
        "/api/widget/v1/sessions",
        json={"widget_id": WIDGET_ID, "visitor_id": "v"},
        headers=_headers(),
    )
    assert session.status_code == 200

    chat = test_client.post(
        "/api/widget/v1/chat",
        json={"question": "What plans do you offer?"},
        headers=_headers(Authorization=_token()),
    )
    assert chat.status_code == 200
    assert chat.headers["content-type"].startswith("text/event-stream")

    assert (
        test_client.options(
            "/api/widget/v1/chat",
            headers=_headers(
                Authorization=_token(),
                **{
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "authorization,content-type",
                },
            ),
        ).status_code
        == 204
    )


async def test_allowed_origin_feedback_preflight_with_authorization(client) -> None:
    test_client, _, _ = client
    response = test_client.options(
        "/api/widget/v1/feedback",
        headers=_headers(
            Authorization=_token(),
            **{
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        ),
    )
    assert response.status_code == 204
    assert response.headers["access-control-allow-origin"] == "*"


async def test_allowed_origin_matching_ignores_port(client) -> None:
    test_client, _, _ = client
    # Origin header carries the scheme+port; the allowlist matches hostname only.
    response = test_client.get(
        f"/api/widget/v1/config/{WIDGET_ID}",
        headers={"Origin": "https://acme.example:5500"},
    )
    assert response.status_code == 200


async def test_allowed_origin_matching_is_case_insensitive(client) -> None:
    test_client, _, _ = client
    response = test_client.get(
        f"/api/widget/v1/config/{WIDGET_ID}",
        headers={"Origin": "https://ACME.EXAMPLE"},
    )
    assert response.status_code == 200


# ----------------------------------------------------------- rejection paths


@pytest.mark.parametrize(
    "method, path, body, headers",
    [
        ("get", "/api/widget/v1/config/widget-origin-1", None, {}),
        ("post", "/api/widget/v1/sessions", {"widget_id": WIDGET_ID, "visitor_id": "v"}, {}),
        ("post", "/api/widget/v1/chat", {"question": "Hi"}, {"Authorization": _token()}),
        (
            "post",
            "/api/widget/v1/feedback",
            {"session_id": "s", "message_id": "m", "rating": 4, "category": "helpful"},
            {"Authorization": _token()},
        ),
    ],
)
async def test_disallowed_origin_rejected_on_all_routes(
    client, method, path, body, headers
) -> None:
    test_client, _, chat_env = client
    await _ready_website(chat_env)
    call = getattr(test_client, method)
    response = (
        call(path, headers={"Origin": "https://evil.example", **headers})
        if body is None
        else call(
            path,
            json=body,
            headers={"Origin": "https://evil.example", **headers},
        )
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "WIDGET_ORIGIN_NOT_ALLOWED"


async def test_null_origin_rejected(client) -> None:
    test_client, _, _ = client
    # `Origin: null` (sandboxed iframe / file://) is never a legitimate embed.
    response = test_client.get(
        f"/api/widget/v1/config/{WIDGET_ID}", headers={"Origin": "null"}
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "WIDGET_ORIGIN_NOT_ALLOWED"


async def test_no_origin_header_still_permitted(client) -> None:
    test_client, _, _ = client
    # curl / server-to-server callers send no Origin; not a browser embed.
    response = test_client.get(f"/api/widget/v1/config/{WIDGET_ID}")
    assert response.status_code == 200
    assert response.json()["widget_id"] == WIDGET_ID


async def test_disallowed_origin_config_does_not_reveal_website(client) -> None:
    test_client, _, _ = client
    response = test_client.get(
        f"/api/widget/v1/config/{WIDGET_ID}",
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403
    body = response.json()["error"]
    assert "tenant" not in str(body).lower()
    assert "website" not in str(body).lower()


# ------------------------------------------------------------ wildcards


@pytest.fixture
def wildcard_client(monkeypatch):
    """Widget whose allowlist is `*.acme.example` (subdomains + bare domain)."""
    test_client, _, _ = _build_client(monkeypatch, ["*.acme.example"])
    with test_client:
        yield test_client
    get_settings.cache_clear()


async def test_wildcard_allowlist_matches_subdomain_and_bare(wildcard_client) -> None:
    test_client = wildcard_client
    assert (
        test_client.get(
            f"/api/widget/v1/config/{WIDGET_ID}",
            headers={"Origin": "https://app.acme.example"},
        ).status_code
        == 200
    )
    assert (
        test_client.get(
            f"/api/widget/v1/config/{WIDGET_ID}",
            headers={"Origin": "https://acme.example"},
        ).status_code
        == 200
    )
    assert (
        test_client.get(
            f"/api/widget/v1/config/{WIDGET_ID}",
            headers={"Origin": "https://acme.example.evil.com"},
        ).status_code
        == 403
    )


# ------------------------------------------------------- development hosts


async def test_development_hosts_allowed_without_allowlist_entry(client) -> None:
    test_client, _, _ = client
    # Loopback hosts not in `cors_origins` are auto-permitted in development
    # so a developer can embed without editing the allowlist.
    for origin in ("http://localhost:5173", "http://127.0.0.1:5173"):
        response = test_client.get(
            f"/api/widget/v1/config/{WIDGET_ID}", headers={"Origin": origin}
        )
        assert response.status_code == 200, origin


async def test_production_blocks_loopback_origin(production_client) -> None:
    test_client = production_client
    # Development-only loopback auto-allow is off in production: a local embed
    # must be explicitly allowlisted (or served through an allowed domain).
    response = test_client.get(
        f"/api/widget/v1/config/{WIDGET_ID}", headers={"Origin": "http://localhost:5173"}
    )
    assert response.status_code == 403
    body = response.json()["error"]
    assert body["code"] == "WIDGET_ORIGIN_NOT_ALLOWED"
    assert "localhost" in body["message"]


# ------------------------------------------------------ empty allowlist


async def test_empty_allowlist_blocks_browser_origin(unconfigured_client) -> None:
    test_client = unconfigured_client
    response = test_client.get(
        f"/api/widget/v1/config/{WIDGET_ID}", headers={"Origin": "https://acme.example"}
    )
    assert response.status_code == 403
    body = response.json()["error"]
    assert body["code"] == "WIDGET_DOMAIN_NOT_CONFIGURED"


async def test_empty_allowlist_still_allows_non_browser_clients(
    unconfigured_client,
) -> None:
    test_client = unconfigured_client
    response = test_client.get(f"/api/widget/v1/config/{WIDGET_ID}")
    assert response.status_code == 200


# --------------------------------------------------------- error messages


async def test_disallowed_origin_message_includes_hostname(client) -> None:
    test_client, _, _ = client
    response = test_client.get(
        f"/api/widget/v1/config/{WIDGET_ID}", headers={"Origin": "https://evil.example"}
    )
    assert response.status_code == 403
    body = response.json()["error"]
    assert body["code"] == "WIDGET_ORIGIN_NOT_ALLOWED"
    assert "evil.example" in body["message"]


async def test_domain_not_configured_message_is_actionable(unconfigured_client) -> None:
    test_client = unconfigured_client
    response = test_client.get(
        f"/api/widget/v1/config/{WIDGET_ID}", headers={"Origin": "https://acme.example"}
    )
    body = response.json()["error"]
    assert body["code"] == "WIDGET_DOMAIN_NOT_CONFIGURED"
    assert "Add allowed domains" in body["message"]


# ----------------------------------------------------------- open embedding


async def test_asterisk_allowlist_opens_embedding(monkeypatch) -> None:
    test_client, _, _ = _build_client(monkeypatch, ["*"])
    with test_client:
        assert (
            test_client.get(
                f"/api/widget/v1/config/{WIDGET_ID}",
                headers={"Origin": "https://anything.example"},
            ).status_code
            == 200
        )
    get_settings.cache_clear()
