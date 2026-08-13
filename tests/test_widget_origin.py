"""End-to-end tests for the widget embed-origin allowlist (production hardening).

A widget with a non-empty `allowed_domains` may only be embedded by browser
pages whose `Origin` hostname is listed. The widget surface still answers
`ACAO: *` (that cannot express an allowlist), so enforcement is
application-level: every widget route rejects mismatched origins with
`403 WIDGET_ORIGIN_NOT_ALLOWED`. Requests without an `Origin` header (curl /
server-to-server) are not browser embeds and stay permitted.
"""

import pytest
from backend.api.deps import (
    get_feedback_service,
    get_rag_service,
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

from tests.chat_helpers import build_chat_env, make_chunk, make_website
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


def _build_widget_service(
    websites: FakeWebsiteRepository, allowed_domains: list[str]
) -> WidgetService:
    widgets = FakeWidgetRepository()
    tenants = FakeTenantRepository()
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
    )


@pytest.fixture
def client(monkeypatch):
    """TestClient whose widget service uses a widget with an allowlist."""
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("WIDGET_RATE_LIMIT_ENABLED", "false")
    get_settings.cache_clear()
    chat_env = build_chat_env()
    widget_service = _build_widget_service(chat_env.websites, ALLOWED)
    feedback_service = FeedbackService(
        feedback=FakeFeedbackRepository(),
        messages=chat_env.messages,
    )
    app = create_app()
    app.dependency_overrides[get_widget_service] = lambda: widget_service
    app.dependency_overrides[get_rag_service] = lambda: chat_env.rag
    app.dependency_overrides[get_feedback_service] = lambda: feedback_service
    with TestClient(app) as test_client:
        yield test_client, widget_service, chat_env
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
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("WIDGET_RATE_LIMIT_ENABLED", "false")
    get_settings.cache_clear()
    chat_env = build_chat_env()
    widget_service = _build_widget_service(chat_env.websites, ["*.acme.example"])
    app = create_app()
    app.dependency_overrides[get_widget_service] = lambda: widget_service
    app.dependency_overrides[get_rag_service] = lambda: chat_env.rag
    with TestClient(app) as test_client:
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
