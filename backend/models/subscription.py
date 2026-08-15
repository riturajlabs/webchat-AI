"""Subscription document model (Phase 14, SaaS subscriptions).

The `subscriptions` collection records every completed payment for a tenant -
one document per paid billing period - so the same collection serves both the
current-plan lookup (the newest `active`/`trialing` subscription whose
`end_date` has not passed) and the dashboard's payment history. It is a
write-only append log from the payment webhook path; plan *enforcement* reads
it through `UsageService`, which resolves limits from the active subscription
before falling back to `tenants.plan`.

Statuses:

    trialing    free evaluation window (future proofing; not self-serve yet)
    active      payment captured, `end_date` in the future
    cancelled   the tenant cancelled / was replaced by a newer subscription
    expired     `end_date` passed; limits fall back to the tenant plan

`payment_provider`/`payment_id` tie the record back to the gateway
(`stripe`/`razorpay`); `payment_id` is the provider's idempotency key - a
replayed webhook must not create a duplicate document.
"""

from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict

from backend.core.security import new_id, utcnow

SUBSCRIPTION_STATUS_TRIALING = "trialing"
SUBSCRIPTION_STATUS_ACTIVE = "active"
SUBSCRIPTION_STATUS_CANCELLED = "cancelled"
SUBSCRIPTION_STATUS_EXPIRED = "expired"

SUBSCRIPTION_STATUSES = frozenset(
    {
        SUBSCRIPTION_STATUS_TRIALING,
        SUBSCRIPTION_STATUS_ACTIVE,
        SUBSCRIPTION_STATUS_CANCELLED,
        SUBSCRIPTION_STATUS_EXPIRED,
    }
)

# Statuses that grant plan limits while `end_date` is still in the future.
SUBSCRIPTION_LIVE_STATUSES = frozenset(
    {SUBSCRIPTION_STATUS_TRIALING, SUBSCRIPTION_STATUS_ACTIVE}
)

SUBSCRIPTION_SCHEMA_VERSION = 1


class Subscription(BaseModel):
    """One paid billing period (or free trial) for a tenant."""

    model_config = ConfigDict(extra="allow")

    id: str
    tenant_id: str
    plan_id: str
    status: str
    payment_provider: str | None = None
    payment_id: str | None = None
    start_date: datetime
    end_date: datetime | None = None
    # Revenue accounting (Phase 15): the amount actually charged for this
    # billing period in minor units plus the currency. Optional so pre-existing
    # documents (created before Phase 15) remain readable; the activation path
    # fills it from the plan's `price_cents` going forward.
    amount_cents: int | None = None
    currency: str | None = None
    created_at: datetime
    updated_at: datetime
    schema_version: int = SUBSCRIPTION_SCHEMA_VERSION

    @classmethod
    def new(
        cls,
        *,
        tenant_id: str,
        plan_id: str,
        status: str = SUBSCRIPTION_STATUS_ACTIVE,
        payment_provider: str | None = None,
        payment_id: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        period_days: int | None = None,
        amount_cents: int | None = None,
        currency: str | None = None,
    ) -> "Subscription":
        now = start_date or utcnow()
        if end_date is None and period_days:
            end_date = now + timedelta(days=period_days)
        return cls(
            id=new_id(),
            tenant_id=tenant_id,
            plan_id=plan_id,
            status=status,
            payment_provider=payment_provider,
            payment_id=payment_id,
            start_date=now,
            end_date=end_date,
            amount_cents=amount_cents,
            currency=currency,
            created_at=now,
            updated_at=now,
        )

    @classmethod
    def from_doc(cls, doc: dict[str, Any]) -> "Subscription":
        doc = dict(doc)
        doc["id"] = str(doc.pop("_id"))
        return cls(**doc)

    def to_doc(self) -> dict[str, Any]:
        doc = self.model_dump(exclude={"id"})
        doc["_id"] = self.id
        return doc


__all__ = [
    "SUBSCRIPTION_LIVE_STATUSES",
    "SUBSCRIPTION_SCHEMA_VERSION",
    "SUBSCRIPTION_STATUS_ACTIVE",
    "SUBSCRIPTION_STATUS_CANCELLED",
    "SUBSCRIPTION_STATUS_EXPIRED",
    "SUBSCRIPTION_STATUS_TRIALING",
    "SUBSCRIPTION_STATUSES",
    "Subscription",
]
