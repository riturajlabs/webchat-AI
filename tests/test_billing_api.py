"""End-to-end HTTP tests for the /api/billing endpoints (Phase 13 + Phase 14).

Phase 13 covers the two read surfaces: `GET /api/billing/usage` (plan + live/
monthly counts + per-metric utilization) and `GET /api/billing/plans` (the
purchasable tiers), plus the owner/admin RBAC and authentication gates.
Phase 14 adds `POST /api/billing/checkout` (start a hosted checkout) and
`GET /api/billing/subscription` (current subscription + payment history), and
prices each plan in `GET /api/billing/plans`. Chat-stream limit enforcement is
covered in `test_chat_api.py`; service-level gating for website creation and
crawls in `test_usage_service.py`; webhook activation in `test_payment_webhooks.py`.
"""

import pytest
from backend.api.deps import (
    get_auth_service,
    get_payment_provider,
    get_subscription_service,
    get_usage_service,
)
from backend.core.config import get_settings
from backend.main import create_app
from fastapi.testclient import TestClient

from tests.auth_helpers import build_auth_env
from tests.billing_helpers import build_billing_env, build_payment_env
from tests.http_helpers import register_verified_account

_ACCOUNT_SEQ = 0


@pytest.fixture
def client(monkeypatch):
    """A TestClient whose auth + billing + payment services are backed by fakes."""
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    get_settings.cache_clear()
    auth_env = build_auth_env()
    billing_env = build_billing_env(auth_env.tenants)
    payment_env = build_payment_env(auth_env.tenants)
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: auth_env.service
    app.dependency_overrides[get_usage_service] = lambda: billing_env.service
    app.dependency_overrides[get_subscription_service] = lambda: payment_env.service
    app.dependency_overrides[get_payment_provider] = lambda: payment_env.provider
    with TestClient(app) as test_client:
        yield test_client, auth_env, billing_env, payment_env
    get_settings.cache_clear()


def _auth(test_client: TestClient) -> tuple[dict[str, str], str]:
    """Register + verify a fresh account and return (bearer headers, tenant_id)."""
    global _ACCOUNT_SEQ
    _ACCOUNT_SEQ += 1
    body = register_verified_account(
        test_client,
        name="Alice",
        email=f"alice{_ACCOUNT_SEQ}@example.com",
    )
    return {"Authorization": f"Bearer {body['access_token']}"}, body["user"]["tenant_id"]


# ------------------------------------------------------------------ /usage


async def test_billing_usage_reports_free_plan_and_zero_usage(client) -> None:
    test_client, _, _, _ = client
    headers, _tenant_id = _auth(test_client)

    response = test_client.get("/api/billing/usage", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["plan"]["id"] == "free"
    assert body["plan"]["name"] == "Free"
    assert body["plan"]["limits"]["max_websites"] == 1
    assert body["plan"]["limits"]["max_monthly_messages"] == 1_000
    assert body["usage"] == {
        "messages_sent": 0,
        "ai_responses": 0,
        "tokens_used": 0,
        "documents_created": 0,
        "crawl_pages": 0,
        "websites": 0,
        "documents": 0,
    }
    by_metric = {row["metric"]: row for row in body["limits"]}
    assert set(by_metric) == {
        "messages_sent",
        "websites",
        "tokens_used",
        "documents",
        "crawl_pages",
    }
    assert by_metric["messages_sent"]["limit"] == 1_000
    assert by_metric["messages_sent"]["percent"] == 0.0


async def test_billing_usage_reflects_recorded_events_and_live_counts(client) -> None:
    test_client, _, billing_env, _ = client
    headers, tenant_id = _auth(test_client)
    await billing_env.service.record_usage(
        tenant_id=tenant_id, user_id="user-1", website_id="web-1", event_type="messages_sent"
    )
    await billing_env.service.record_usage(
        tenant_id=tenant_id, user_id="user-1", website_id="web-1",
        event_type="tokens_used", quantity=250,
    )

    response = test_client.get("/api/billing/usage", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["usage"]["messages_sent"] == 1
    assert body["usage"]["tokens_used"] == 250
    by_metric = {row["metric"]: row for row in body["limits"]}
    assert by_metric["messages_sent"]["used"] == 1
    assert by_metric["tokens_used"]["percent"] == 0.2  # 250 / 100_000


async def test_billing_usage_requires_authentication(client) -> None:
    test_client, _, _, _ = client
    response = test_client.get("/api/billing/usage")
    assert response.status_code == 401


async def test_billing_usage_requires_owner_or_admin_role(client) -> None:
    test_client, auth_env, _, _ = client
    headers, _tenant_id = _auth(test_client)
    member = next(iter(auth_env.members.members.values()))
    member.role = "viewer"

    response = test_client.get("/api/billing/usage", headers=headers)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


# ------------------------------------------------------------------ /plans


async def test_billing_plans_lists_all_tiers_with_prices(client) -> None:
    test_client, _, _, _ = client
    headers, _tenant_id = _auth(test_client)

    response = test_client.get("/api/billing/plans", headers=headers)

    assert response.status_code == 200
    plans = response.json()
    assert [plan["id"] for plan in plans] == ["free", "pro", "enterprise"]
    free = plans[0]
    assert free["name"] == "Free"
    assert free["limits"]["max_websites"] == 1
    assert free["limits"]["max_monthly_messages"] == 1_000
    assert free["price_cents"] == 0
    assert free["currency"] == "USD"
    pro = plans[1]
    assert pro["price_cents"] == 2_900
    assert pro["currency"] == "USD"
    enterprise = plans[2]
    assert enterprise["limits"]["max_websites"] is None
    assert enterprise["limits"]["max_crawl_pages"] is None
    assert enterprise["price_cents"] is None


async def test_billing_plans_requires_authentication(client) -> None:
    test_client, _, _, _ = client
    response = test_client.get("/api/billing/plans")
    assert response.status_code == 401


# -------------------------------------------------------------- /checkout


async def test_checkout_creates_provider_checkout_for_purchasable_plan(client) -> None:
    test_client, _, _, payment_env = client
    headers, tenant_id = _auth(test_client)

    response = test_client.post(
        "/api/billing/checkout",
        headers=headers,
        json={
            "plan_id": "pro",
            "success_url": "http://localhost:3000/billing?status=success",
            "cancel_url": "http://localhost:3000/billing?status=cancelled",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["checkout_id"].startswith("fake_checkout_")
    assert body["url"].startswith("https://checkout.example.com/")
    checkout = payment_env.provider.checkouts[0]
    assert checkout["tenant_id"] == tenant_id
    assert checkout["plan_id"] == "pro"
    assert checkout["amount_cents"] == 2_900
    assert checkout["currency"] == "USD"


async def test_checkout_rejects_non_purchasable_plan(client) -> None:
    test_client, _, _, _ = client
    headers, _tenant_id = _auth(test_client)

    response = test_client.post(
        "/api/billing/checkout", headers=headers, json={"plan_id": "free"}
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "PLAN_NOT_PURCHASABLE"
    assert response.json()["error"]["message"] == (
        "The Free plan cannot be purchased through checkout."
    )


async def test_checkout_rejects_unknown_plan(client) -> None:
    test_client, _, _, _ = client
    headers, _tenant_id = _auth(test_client)

    response = test_client.post(
        "/api/billing/checkout", headers=headers, json={"plan_id": "does-not-exist"}
    )

    # `get_plan` falls back to Free for unknown ids; Free is not purchasable.
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "PLAN_NOT_PURCHASABLE"


async def test_checkout_requires_authentication(client) -> None:
    test_client, _, _, _ = client
    response = test_client.post("/api/billing/checkout", json={"plan_id": "pro"})
    assert response.status_code == 401


# ---------------------------------------------------------- /subscription


async def test_subscription_returns_empty_report_for_new_tenant(client) -> None:
    test_client, _, _, _ = client
    headers, _tenant_id = _auth(test_client)

    response = test_client.get("/api/billing/subscription", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["subscription"] is None
    assert body["payments"] == []


async def test_subscription_reflects_activation_and_payment_history(client) -> None:
    test_client, _, _, payment_env = client
    headers, tenant_id = _auth(test_client)
    payment_env.provider.tenant_id = tenant_id

    await payment_env.service.activate_payment(
        payment_env.provider.parse_webhook(b"payload", {})
    )

    response = test_client.get("/api/billing/subscription", headers=headers)

    assert response.status_code == 200
    body = response.json()
    subscription = body["subscription"]
    assert subscription is not None
    assert subscription["plan_id"] == "pro"
    assert subscription["plan_name"] == "Pro"
    assert subscription["status"] == "active"
    assert subscription["payment_provider"] == "fake"
    assert subscription["payment_id"] == "fake_payment_1"
    assert len(body["payments"]) == 1
    payment = body["payments"][0]
    assert payment["plan_id"] == "pro"
    assert payment["amount_cents"] == 2_900
    assert payment["currency"] == "USD"
