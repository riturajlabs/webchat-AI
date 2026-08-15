"""Service-level tests for Phase 14 `SubscriptionService` (no HTTP).

Covers checkout creation (purchasable + price guard), webhook-driven
activation (idempotency on `payment_id`, non-paid no-ops), and the read side:
current subscription, effective plan resolution and the payment-history report
(including the lapsed-subscription `expired` display). Provider signature
verification is covered separately in `test_payment_providers.py`; the HTTP
webhook surface in `test_payment_webhooks.py`; API wiring in `test_billing_api.py`.
"""

from datetime import UTC, datetime, timedelta

import pytest
from backend.core.errors import PlanNotPurchasableError
from backend.models.plan import PLAN_FREE, PLAN_PRO
from backend.models.subscription import (
    SUBSCRIPTION_STATUS_ACTIVE,
    SUBSCRIPTION_STATUS_EXPIRED,
)
from backend.models.tenant import Tenant
from backend.services.billing import (
    PAYMENT_STATUS_FAILED,
    PAYMENT_STATUS_PAID,
    WebhookEvent,
)

from tests.billing_helpers import build_payment_env
from tests.fakes import FakeTenantRepository

NOW = datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)


def _seed_tenant(tenants: FakeTenantRepository, *, plan: str = PLAN_FREE) -> None:
    tenant = Tenant.new(company_name="Acme")
    tenant.id = "tenant-a"
    tenant.plan = plan
    tenants.tenants[tenant.id] = tenant


def _paid_event(**overrides) -> WebhookEvent:
    fields = dict(
        event_type="payment.captured",
        payment_id="pay_1",
        status=PAYMENT_STATUS_PAID,
        tenant_id="tenant-a",
        plan_id=PLAN_PRO,
    )
    fields.update(overrides)
    return WebhookEvent(**fields)


@pytest.fixture
def env():
    tenants = FakeTenantRepository()
    _seed_tenant(tenants)
    return build_payment_env(tenants, now=NOW)


# -------------------------------------------------------------- checkout


async def test_create_checkout_delegates_to_provider(env) -> None:
    checkout = await env.service.create_checkout(
        tenant_id="tenant-a",
        plan_id=PLAN_PRO,
        success_url="http://localhost:3000/billing?status=success",
        cancel_url="http://localhost:3000/billing?status=cancelled",
    )

    assert checkout.checkout_id.startswith("fake_checkout_")
    assert checkout.url.startswith("https://checkout.example.com/")
    assert env.provider.checkouts == [
        {
            "tenant_id": "tenant-a",
            "plan_id": "pro",
            "amount_cents": 2_900,
            "currency": "USD",
            "success_url": "http://localhost:3000/billing?status=success",
            "cancel_url": "http://localhost:3000/billing?status=cancelled",
        }
    ]


async def test_create_checkout_rejects_free_plan(env) -> None:
    with pytest.raises(PlanNotPurchasableError) as exc_info:
        await env.service.create_checkout(
            tenant_id="tenant-a", plan_id=PLAN_FREE, success_url="/", cancel_url="/"
        )
    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "PLAN_NOT_PURCHASABLE"
    assert env.provider.checkouts == []


# ------------------------------------------------------------- activation


async def test_activate_payment_creates_active_subscription(env) -> None:
    subscription = await env.service.activate_payment(_paid_event())

    assert subscription is not None
    assert subscription.tenant_id == "tenant-a"
    assert subscription.plan_id == PLAN_PRO
    assert subscription.status == SUBSCRIPTION_STATUS_ACTIVE
    assert subscription.payment_provider == "fake"
    assert subscription.payment_id == "pay_1"
    assert subscription.start_date == NOW
    assert subscription.end_date == NOW + timedelta(days=30)  # Pro billing period


async def test_activate_payment_is_idempotent_on_payment_id(env) -> None:
    first = await env.service.activate_payment(_paid_event())
    assert first is not None

    replay = await env.service.activate_payment(_paid_event())

    assert replay is None
    assert len(env.subscriptions.subscriptions) == 1


async def test_activate_payment_ignores_failed_events(env) -> None:
    result = await env.service.activate_payment(
        _paid_event(status=PAYMENT_STATUS_FAILED)
    )
    assert result is None
    assert env.subscriptions.subscriptions == []


async def test_activate_payment_requires_ids(env) -> None:
    assert await env.service.activate_payment(_paid_event(payment_id="")) is None
    assert await env.service.activate_payment(_paid_event(tenant_id=None)) is None
    assert await env.service.activate_payment(_paid_event(plan_id=None)) is None
    assert env.subscriptions.subscriptions == []


# ------------------------------------------------------------------ reads


async def test_get_current_subscription_returns_live_only(env) -> None:
    await env.service.activate_payment(_paid_event())
    current = await env.service.get_current_subscription("tenant-a")
    assert current is not None
    assert current.plan_id == PLAN_PRO


async def test_get_effective_plan_prefers_subscription(env) -> None:
    await env.service.activate_payment(_paid_event())
    plan = await env.service.get_effective_plan("tenant-a")
    assert plan.id == PLAN_PRO


async def test_get_effective_plan_falls_back_to_tenant_plan(env) -> None:
    _seed_tenant(env.tenants, plan=PLAN_PRO)
    plan = await env.service.get_effective_plan("tenant-a")
    assert plan.id == PLAN_PRO


async def test_get_report_returns_subscription_and_history(env) -> None:
    env.service._now = lambda: NOW
    await env.service.activate_payment(_paid_event(payment_id="pay_1"))
    env.service._now = lambda: NOW + timedelta(minutes=1)
    await env.service.activate_payment(_paid_event(payment_id="pay_2", plan_id=PLAN_PRO))

    current, history = await env.service.get_report("tenant-a")

    assert current is not None and current.payment_id == "pay_2"
    assert [row.payment_id for row in history] == ["pay_2", "pay_1"]


async def test_get_report_marks_lapsed_subscription_expired(env) -> None:
    await env.service.activate_payment(_paid_event(payment_id="pay_1"))
    later = NOW + timedelta(days=45)
    env.service._now = lambda: later

    current, history = await env.service.get_report("tenant-a")

    assert current is not None
    assert current.status == SUBSCRIPTION_STATUS_EXPIRED
    assert history[0].status == SUBSCRIPTION_STATUS_ACTIVE  # raw doc unchanged


async def test_get_report_empty_for_unknown_tenant(env) -> None:
    current, history = await env.service.get_report("missing")
    assert current is None
    assert history == []
