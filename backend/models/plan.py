"""Subscription plan model (Phase 13 billing + Phase 14 subscriptions).

Plans are pure data: a `Plan` carries the id that `tenants.plan` stores
("free" is the signup default, `backend/models/tenant.py`) plus the numeric
limits the billing/usage service enforces. `None` means "unlimited / custom":
ENTERPRISE limits are negotiated per-customer, so every limit is open-ended
unless a sales-ops row sets one.

`price_cents` is the self-serve list price in `PAYMENT_CURRENCY` minor units;
`None`/`0` marks a plan that is not purchasable through checkout (Free is the
trial tier, Enterprise is sold by sales). Phase 14 uses it to build payment
provider checkouts and to render upgrade cards + payment history.

Limit fields (all optional, `None` = unlimited):

    max_websites            live websites the tenant may own
    max_monthly_messages    messages_sent usage_events per calendar month
    max_monthly_tokens      tokens_used usage_events per calendar month
    max_documents           documents stored for the tenant (all websites)
    max_crawl_pages         crawl_pages usage_events per calendar month
"""

from dataclasses import dataclass

PLAN_FREE = "free"
PLAN_PRO = "pro"
PLAN_ENTERPRISE = "enterprise"

VALID_PLAN_IDS = frozenset({PLAN_FREE, PLAN_PRO, PLAN_ENTERPRISE})


@dataclass(frozen=True)
class Plan:
    """One subscription tier and the limits it enforces."""

    id: str
    name: str
    description: str
    max_websites: int | None = None
    max_monthly_messages: int | None = None
    max_monthly_tokens: int | None = None
    max_documents: int | None = None
    max_crawl_pages: int | None = None
    # Phase 14: self-serve list price in minor units (PAYMENT_CURRENCY).
    # `None` or `0` means the plan is not purchasable via checkout.
    price_cents: int | None = None
    # Billing period in days for the auto-expiry of self-serve plans.
    billing_period_days: int | None = None


PLANS: dict[str, Plan] = {
    PLAN_FREE: Plan(
        id=PLAN_FREE,
        name="Free",
        description="For personal projects and evaluation.",
        max_websites=1,
        max_monthly_messages=1_000,
        max_monthly_tokens=100_000,
        max_documents=10,
        max_crawl_pages=500,
        price_cents=0,
    ),
    PLAN_PRO: Plan(
        id=PLAN_PRO,
        name="Pro",
        description="For growing teams with higher usage.",
        max_websites=5,
        max_monthly_messages=50_000,
        max_monthly_tokens=2_000_000,
        max_documents=100,
        max_crawl_pages=5_000,
        price_cents=2_900,
        billing_period_days=30,
    ),
    PLAN_ENTERPRISE: Plan(
        id=PLAN_ENTERPRISE,
        name="Enterprise",
        description="Custom limits for high-volume deployments.",
        price_cents=None,
    ),
}


def get_plan(plan_id: str) -> Plan:
    """Resolve a `tenants.plan` value to a `Plan`, defaulting to Free."""
    return PLANS.get(plan_id, PLANS[PLAN_FREE])


__all__ = [
    "PLANS",
    "PLAN_ENTERPRISE",
    "PLAN_FREE",
    "PLAN_PRO",
    "VALID_PLAN_IDS",
    "Plan",
    "get_plan",
]
