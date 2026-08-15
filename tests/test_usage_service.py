"""Service-level tests for Phase 13 billing + Phase 14 subscription resolution
(no HTTP).

Exercise `UsageService` against the in-memory fakes: plan resolution,
`get_current_usage` counts + utilization, `check_limit` enforcement across
every metric (event-based and live-count), the Enterprise/unlimited escape
hatch, and `record_usage` validation. Endpoint wiring + RBAC is covered by
`test_billing_api.py`; chat/website/crawl enforcement wiring by the API tests.
Phase 14: the active subscription plan now overrides `tenants.plan`.
"""

from datetime import UTC, datetime

import pytest
from backend.core.errors import LimitReachedError, TenantNotFoundError
from backend.models.document import Document
from backend.models.plan import PLAN_ENTERPRISE, PLAN_FREE, PLAN_PRO
from backend.models.subscription import Subscription
from backend.models.tenant import Tenant
from backend.models.usage_event import UsageEvent
from backend.models.website import Website

from tests.billing_helpers import build_billing_env
from tests.fakes import FakeTenantRepository

NOW = datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)


def _seed_tenant(
    tenants: FakeTenantRepository,
    *,
    tenant_id: str = "tenant-a",
    plan: str = PLAN_FREE,
) -> None:
    tenant = Tenant.new(company_name="Acme")
    tenant.id = tenant_id
    tenant.plan = plan
    tenants.tenants[tenant_id] = tenant


def _event(
    *,
    tenant_id: str = "tenant-a",
    event_type: str,
    quantity: int = 1,
    created_at: datetime = NOW,
    user_id: str | None = "user-a",
    website_id: str | None = "web-1",
) -> UsageEvent:
    return UsageEvent(
        id=f"{event_type}-{created_at.timestamp()}",
        tenant_id=tenant_id,
        user_id=user_id,
        website_id=website_id,
        event_type=event_type,
        quantity=quantity,
        created_at=created_at,
    )


@pytest.fixture
def env():
    tenants = FakeTenantRepository()
    _seed_tenant(tenants)
    return build_billing_env(tenants, now=NOW)


# ------------------------------------------------------------ plan resolution


async def test_get_plan_resolves_tenant_plan(env) -> None:
    plan = await env.service.get_plan("tenant-a")
    assert plan.id == PLAN_FREE


async def test_get_plan_defaults_to_free_for_unknown_plan_id(env) -> None:
    _seed_tenant(env.tenants, tenant_id="tenant-b", plan="mystery")
    plan = await env.service.get_plan("tenant-b")
    assert plan.id == PLAN_FREE


async def test_get_plan_raises_for_missing_tenant(env) -> None:
    with pytest.raises(TenantNotFoundError):
        await env.service.get_plan("nope")


async def test_get_plan_uses_active_subscription_over_tenant_plan(env) -> None:
    _seed_tenant(env.tenants, tenant_id="tenant-a", plan=PLAN_FREE)
    await env.subscriptions.create(
        Subscription.new(
            tenant_id="tenant-a",
            plan_id=PLAN_PRO,
            start_date=NOW,
            period_days=30,
        )
    )

    plan = await env.service.get_plan("tenant-a")

    assert plan.id == PLAN_PRO
    assert plan.max_websites == 5


async def test_get_plan_falls_back_to_tenant_plan_without_subscription(env) -> None:
    _seed_tenant(env.tenants, tenant_id="tenant-a", plan=PLAN_PRO)
    plan = await env.service.get_plan("tenant-a")
    assert plan.id == PLAN_PRO


async def test_get_plan_ignores_expired_subscription(env) -> None:
    _seed_tenant(env.tenants, tenant_id="tenant-a", plan=PLAN_FREE)
    await env.subscriptions.create(
        Subscription.new(
            tenant_id="tenant-a",
            plan_id=PLAN_PRO,
            start_date=datetime(2026, 5, 1, tzinfo=UTC),
            end_date=datetime(2026, 5, 31, tzinfo=UTC),
        )
    )

    plan = await env.service.get_plan("tenant-a")

    assert plan.id == PLAN_FREE


# ------------------------------------------------------------ current usage


async def test_get_current_usage_reports_totals_and_live_counts(env) -> None:
    await env.service.record_usage(
        tenant_id="tenant-a", user_id="user-a", website_id="web-1", event_type="messages_sent"
    )
    await env.service.record_usage(
        tenant_id="tenant-a", user_id="user-a", website_id="web-1", event_type="tokens_used",
        quantity=150,
    )
    await env.service.record_usage(
        tenant_id="tenant-a", user_id=None, website_id=None, event_type="crawl_pages",
        quantity=3,
    )
    await env.websites.create(Website.new(tenant_id="tenant-a", name="A", url="https://a.example"))
    await env.documents.upsert(
        Document.new(
            tenant_id="tenant-a",
            website_id="web-1",
            url="https://a.example/page",
            title="Page",
            content="Hello",
            checksum="c1",
        )
    )

    snapshot = await env.service.get_current_usage("tenant-a")

    assert snapshot.plan.id == PLAN_FREE
    assert snapshot.totals.messages_sent == 1
    assert snapshot.totals.tokens_used == 150
    assert snapshot.totals.crawl_pages == 3
    assert snapshot.websites == 1
    assert snapshot.documents == 1

    by_metric = {metric.metric: metric for metric in snapshot.metrics}
    assert by_metric["messages_sent"].used == 1
    assert by_metric["messages_sent"].limit == 1_000
    assert by_metric["messages_sent"].percent == 0.1
    assert by_metric["websites"].used == 1
    assert by_metric["websites"].limit == 1
    assert by_metric["websites"].percent == 100.0
    assert by_metric["documents"].percent == 10.0


async def test_get_current_usage_excludes_previous_month_events(env) -> None:
    last_month = datetime(2026, 5, 30, 12, 0, 0, tzinfo=UTC)
    await env.events.record(
        _event(event_type="messages_sent", quantity=40, created_at=last_month)
    )
    await env.service.record_usage(
        tenant_id="tenant-a", user_id="user-a", website_id="web-1", event_type="messages_sent"
    )
    snapshot = await env.service.get_current_usage("tenant-a")
    assert snapshot.totals.messages_sent == 1


async def test_get_current_usage_percent_none_for_unlimited_metrics(env) -> None:
    tenants = FakeTenantRepository()
    _seed_tenant(tenants, plan=PLAN_ENTERPRISE)
    unlimited_env = build_billing_env(tenants, now=NOW)

    snapshot = await unlimited_env.service.get_current_usage("tenant-a")

    assert snapshot.plan.id == PLAN_ENTERPRISE
    assert all(metric.limit is None and metric.percent is None for metric in snapshot.metrics)


# -------------------------------------------------------------- enforcement


async def test_check_limit_passes_below_limit(env) -> None:
    await env.service.check_limit("tenant-a", event_type="messages_sent")
    await env.service.check_limit("tenant-a", event_type="websites")
    await env.service.check_limit("tenant-a", event_type="documents")


async def test_check_limit_raises_for_exhausted_event_metric(env) -> None:
    await env.service.record_usage(
        tenant_id="tenant-a", user_id="user-a", website_id="web-1",
        event_type="messages_sent", quantity=1_000,
    )
    with pytest.raises(LimitReachedError) as exc_info:
        await env.service.check_limit("tenant-a", event_type="messages_sent")
    assert exc_info.value.status_code == 429
    assert exc_info.value.code == "LIMIT_REACHED"
    assert exc_info.value.extra == {
        "metric": "messages_sent",
        "used": 1_000,
        "limit": 1_000,
    }


async def test_check_limit_raises_for_exhausted_live_count(env) -> None:
    await env.service.check_limit("tenant-a", event_type="websites")
    await env.websites.create(
        Website.new(tenant_id="tenant-a", name="A", url="https://a.example")
    )
    with pytest.raises(LimitReachedError):
        await env.service.check_limit("tenant-a", event_type="websites")


async def test_check_limit_raises_for_tokens_and_crawl_pages(env) -> None:
    await env.service.record_usage(
        tenant_id="tenant-a", user_id="user-a", website_id="web-1",
        event_type="tokens_used", quantity=100_000,
    )
    with pytest.raises(LimitReachedError):
        await env.service.check_limit("tenant-a", event_type="tokens_used")
    await env.service.record_usage(
        tenant_id="tenant-a", user_id=None, website_id=None,
        event_type="crawl_pages", quantity=500,
    )
    with pytest.raises(LimitReachedError):
        await env.service.check_limit("tenant-a", event_type="crawl_pages")


async def test_check_limit_never_raises_on_unlimited_plan(env) -> None:
    tenants = FakeTenantRepository()
    _seed_tenant(tenants, plan=PLAN_ENTERPRISE)
    unlimited_env = build_billing_env(tenants, now=NOW)
    for metric in ("messages_sent", "tokens_used", "crawl_pages", "websites", "documents"):
        await unlimited_env.service.check_limit("tenant-a", event_type=metric)


async def test_check_limit_ignores_unknown_metric(env) -> None:
    await env.service.check_limit("tenant-a", event_type="bogus")
    await env.service.check_limit("tenant-a", event_type="messages_sent", quantity=0)


# ------------------------------------------------------------ recording


async def test_record_usage_appends_events(env) -> None:
    await env.service.record_usage(
        tenant_id="tenant-a", user_id="user-a", website_id="web-1",
        event_type="messages_sent",
    )
    assert len(env.events.events) == 1
    assert env.events.events[0].event_type == "messages_sent"
    assert env.events.events[0].tenant_id == "tenant-a"


async def test_record_usage_validates_type_and_quantity(env) -> None:
    with pytest.raises(ValueError):
        await env.service.record_usage(
            tenant_id="tenant-a", user_id=None, website_id=None, event_type="bogus"
        )
    with pytest.raises(ValueError):
        await env.service.record_usage(
            tenant_id="tenant-a", user_id=None, website_id=None, event_type="messages_sent",
            quantity=0,
        )


# -------------------------------------------- website/crawl service gating


async def test_website_service_blocks_creation_at_max_websites(env) -> None:
    from backend.services.auth import Principal

    from tests.website_helpers import build_website_env

    principal = Principal(
        user_id="user-a",
        tenant_id="tenant-a",
        role="owner",
        name="Alice",
        email="alice@example.com",
        email_verified=True,
        status="active",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    website_env = build_website_env(usage=env.service)
    await env.websites.create(
        Website.new(tenant_id="tenant-a", name="A", url="https://a.example")
    )

    with pytest.raises(LimitReachedError):
        await website_env.service.create_website(
            principal=principal,
            name="B",
            url="https://b.example",
            ip_address=None,
            user_agent=None,
        )
    # Nothing was persisted (gated before create).
    assert len(website_env.websites.websites) == 0


async def test_website_service_allows_creation_below_limit(env) -> None:
    from backend.services.auth import Principal

    from tests.website_helpers import build_website_env

    principal = Principal(
        user_id="user-a",
        tenant_id="tenant-a",
        role="owner",
        name="Alice",
        email="alice@example.com",
        email_verified=True,
        status="active",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    website_env = build_website_env(usage=env.service)

    result = await website_env.service.create_website(
        principal=principal,
        name="A",
        url="https://a.example",
        ip_address=None,
        user_agent=None,
    )

    assert result.website.url == "https://a.example/"
    assert len(website_env.websites.websites) == 1


async def test_crawl_service_blocks_when_crawl_pages_exhausted(env) -> None:
    from backend.services.auth import Principal

    from tests.crawl_helpers import build_crawl_env

    principal = Principal(
        user_id="user-a",
        tenant_id="tenant-a",
        role="owner",
        name="Alice",
        email="alice@example.com",
        email_verified=True,
        status="active",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    crawl_env = build_crawl_env(usage=env.service)
    website = Website.new(tenant_id="tenant-a", name="A", url="https://a.example")
    website.id = "web-1"
    await crawl_env.websites.create(website)
    await env.service.record_usage(
        tenant_id="tenant-a", user_id=None, website_id=None,
        event_type="crawl_pages", quantity=500,
    )

    with pytest.raises(LimitReachedError):
        await crawl_env.service.start_crawl(
            principal=principal,
            website_id="web-1",
            ip_address=None,
            user_agent=None,
        )
    # Gated before the job was created/queued.
    assert len(crawl_env.crawl_jobs.jobs) == 0
    assert crawl_env.enqueued == []


async def test_crawl_service_allows_under_limit(env) -> None:
    from backend.services.auth import Principal

    from tests.crawl_helpers import build_crawl_env

    principal = Principal(
        user_id="user-a",
        tenant_id="tenant-a",
        role="owner",
        name="Alice",
        email="alice@example.com",
        email_verified=True,
        status="active",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    crawl_env = build_crawl_env(usage=env.service)
    website = Website.new(tenant_id="tenant-a", name="A", url="https://a.example")
    website.id = "web-1"
    await crawl_env.websites.create(website)

    job = await crawl_env.service.start_crawl(
        principal=principal,
        website_id="web-1",
        ip_address=None,
        user_agent=None,
    )

    assert job.website_id == "web-1"
    assert crawl_env.enqueued == [job.id]
