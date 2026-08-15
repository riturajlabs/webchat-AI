"""Billing API schemas (Phase 13 billing + Phase 14 subscriptions).

`/api/billing/usage` reports the tenant's plan, live + monthly usage, and one
`limits` row per enforced metric so the dashboard can render cards and
utilization bars. `/api/billing/plans` lists every tier with its self-serve
price. `/api/billing/checkout` starts a hosted payment and
`/api/billing/subscription` returns the current subscription + payment history
(Phase 14).
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

MetricName = Literal[
    "messages_sent", "ai_responses", "tokens_used", "documents_created", "crawl_pages"
]


class PlanLimitsOut(BaseModel):
    """A plan's numeric limits (`None` = unlimited / custom)."""

    max_websites: int | None = None
    max_monthly_messages: int | None = None
    max_monthly_tokens: int | None = None
    max_documents: int | None = None
    max_crawl_pages: int | None = None


class PlanOut(BaseModel):
    """A purchasable subscription tier."""

    id: str
    name: str
    description: str
    limits: PlanLimitsOut
    price_cents: int | None = Field(
        default=None, description="Self-serve list price in minor units; None/0 = not purchasable"
    )
    currency: str = Field(default="USD", description="ISO 4217 currency of `price_cents`")


class UsageCountsOut(BaseModel):
    """All tracked usage for the tenant (events + live counts)."""

    messages_sent: int = 0
    ai_responses: int = 0
    tokens_used: int = 0
    documents_created: int = 0
    crawl_pages: int = 0
    websites: int = 0
    documents: int = 0


class UsageMetricOut(BaseModel):
    """One limit row: used vs cap plus utilization percentage."""

    metric: str
    used: int = 0
    limit: int | None = None
    percent: float | None = Field(default=None, description="0-100, None when unlimited")


class UsageOut(BaseModel):
    """`GET /api/billing/usage` response."""

    plan: PlanOut
    usage: UsageCountsOut
    limits: list[UsageMetricOut]


class CheckoutRequest(BaseModel):
    """`POST /api/billing/checkout` request (Phase 14)."""

    plan_id: str = Field(min_length=1)
    success_url: str = "http://localhost:3000/billing?status=success"
    cancel_url: str = "http://localhost:3000/billing?status=cancelled"


class CheckoutOut(BaseModel):
    """`POST /api/billing/checkout` response: provider checkout redirect."""

    checkout_id: str
    url: str


class SubscriptionOut(BaseModel):
    """The tenant's current (plan-granting) subscription."""

    id: str
    plan_id: str
    plan_name: str
    status: str
    payment_provider: str | None = None
    payment_id: str | None = None
    start_date: datetime
    end_date: datetime | None = None
    created_at: datetime


class PaymentOut(BaseModel):
    """One payment-history row (a paid subscription document)."""

    id: str
    plan_id: str
    plan_name: str
    status: str
    amount_cents: int | None = None
    currency: str = "USD"
    payment_provider: str | None = None
    payment_id: str | None = None
    created_at: datetime


class SubscriptionReportOut(BaseModel):
    """`GET /api/billing/subscription` response (Phase 14)."""

    subscription: SubscriptionOut | None = None
    payments: list[PaymentOut] = Field(default_factory=list)


__all__ = [
    "CheckoutOut",
    "CheckoutRequest",
    "MetricName",
    "PaymentOut",
    "PlanLimitsOut",
    "PlanOut",
    "SubscriptionOut",
    "SubscriptionReportOut",
    "UsageCountsOut",
    "UsageMetricOut",
    "UsageOut",
]
