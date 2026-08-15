"""Shared helpers for Phase 13 billing/usage + Phase 14 subscription tests.

`build_billing_env` wires the usage event fake plus the tenant/website/document
fakes into a real `UsageService`, so API tests can exercise limit enforcement
and `/api/billing/*` with in-memory state. Callers pass the *same* tenant fake
used by the auth service so plan resolution sees the registered tenant.

`build_payment_env` additionally wires a `FakeSubscriptionRepository` + a
`FakePaymentProvider` into a real `SubscriptionService` for the Phase 14
checkout / subscription / webhook surfaces.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from backend.services.billing import SubscriptionService, UsageService

from tests.fakes import (
    FakeDocumentRepository,
    FakePaymentProvider,
    FakeSubscriptionRepository,
    FakeTenantRepository,
    FakeUsageEventRepository,
    FakeWebsiteRepository,
)


@dataclass
class BillingEnv:
    tenants: FakeTenantRepository
    events: FakeUsageEventRepository
    websites: FakeWebsiteRepository
    documents: FakeDocumentRepository
    subscriptions: FakeSubscriptionRepository | None
    service: UsageService


@dataclass
class PaymentEnv:
    tenants: FakeTenantRepository
    subscriptions: FakeSubscriptionRepository
    provider: FakePaymentProvider
    service: SubscriptionService


def build_billing_env(
    tenants: FakeTenantRepository,
    *,
    now: datetime | None = None,
) -> BillingEnv:
    """Build a real `UsageService` over in-memory fakes sharing `tenants`."""
    events = FakeUsageEventRepository()
    websites = FakeWebsiteRepository()
    documents = FakeDocumentRepository()
    subscriptions = FakeSubscriptionRepository()
    service = UsageService(
        events=events,
        tenants=tenants,
        websites=websites,
        documents=documents,
        subscriptions=subscriptions,
        now=None if now is None else (lambda: now.replace(tzinfo=UTC)),
    )
    return BillingEnv(
        tenants=tenants,
        events=events,
        websites=websites,
        documents=documents,
        subscriptions=subscriptions,
        service=service,
    )


def build_payment_env(
    tenants: FakeTenantRepository,
    *,
    currency: str = "USD",
    now: datetime | None = None,
) -> PaymentEnv:
    """Build a real `SubscriptionService` over fakes sharing `tenants`."""
    subscriptions = FakeSubscriptionRepository()
    provider = FakePaymentProvider()
    service = SubscriptionService(
        subscriptions=subscriptions,
        provider=provider,
        tenants=tenants,
        currency=currency,
        now=None if now is None else (lambda: now.replace(tzinfo=UTC)),
    )
    return PaymentEnv(
        tenants=tenants,
        subscriptions=subscriptions,
        provider=provider,
        service=service,
    )


__all__ = ["BillingEnv", "PaymentEnv", "build_billing_env", "build_payment_env"]
