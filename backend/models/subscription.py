"""Subscription document model (Phase 14, SaaS subscriptions).

The `subscriptions` collection records every completed payment for a tenant -
one document per paid billing period - so the same collection serves both the
current-plan lookup (the newest `active`/`trialing` subscription whose
`end_date` has not passed) and the dashboard's payment history. It is a
write-only append log from the payment webhook path; plan *enforcement* reads
it through `UsageService`, which resolves limits from the active subscription
before falling back to `tenants.plan`.

The same collection also hosts *admin grants* (`source="admin_grant"`): a
complementary, operator-issued subscription record so a workspace can be
given a paid plan without a payment. Grants are stored alongside payments so
one repository/collection keeps the "current plan" rule consistent, and they
are excluded from revenue (`amount_cents` is always `0`). The effective-plan
resolution prefers an active admin grant, then the newest paid subscription,
then `tenants.plan`.

Statuses:

    trialing    free evaluation window (future proofing; not self-serve yet)
    active      payment captured (or grant active), `end_date` in the future
    cancelled   the tenant cancelled / was replaced / the grant was revoked
    expired     `end_date` passed; limits fall back to the tenant plan

`payment_provider`/`payment_id` tie a payment record back to the gateway
(`stripe`/`razorpay`); `payment_id` is the provider's idempotency key - a
replayed webhook must not create a duplicate document. Grant records instead
set `payment_provider="admin"` and leave `payment_id` empty, carrying the
grantor and an optional reason in `granted_by`/`granted_at`/`grant_reason`.
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
SUBSCRIPTION_LIVE_STATUSES = frozenset({SUBSCRIPTION_STATUS_TRIALING, SUBSCRIPTION_STATUS_ACTIVE})

# Document provenance: how a subscription record came to exist. `payment` is
# the webhook-driven paid billing period; `admin_grant` is a complimentary
# plan issued by a platform operator (payment_provider="admin", amount 0).
# Legacy documents written before this field simply omit it and read as
# `payment`.
SUBSCRIPTION_SOURCE_PAYMENT = "payment"
SUBSCRIPTION_SOURCE_ADMIN_GRANT = "admin_grant"
SUBSCRIPTION_SOURCES = frozenset({SUBSCRIPTION_SOURCE_PAYMENT, SUBSCRIPTION_SOURCE_ADMIN_GRANT})

# Payment records that count toward revenue / paid MRR (excludes admin grants).
PAID_SUBSCRIPTION_SOURCE = SUBSCRIPTION_SOURCE_PAYMENT

SUBSCRIPTION_SCHEMA_VERSION = 1


class Subscription(BaseModel):
    """One paid billing period (or free trial) for a tenant."""

    model_config = ConfigDict(extra="allow")

    id: str
    tenant_id: str
    plan_id: str
    status: str
    # Provenance: `payment` (webhook → activate_payment) or `admin_grant`
    # (platform operator). Missing on pre-field documents → treated as `payment`.
    source: str = SUBSCRIPTION_SOURCE_PAYMENT
    payment_provider: str | None = None
    payment_id: str | None = None
    start_date: datetime
    end_date: datetime | None = None
    # Admin grant metadata (set only for `source="admin_grant"` records): who
    # issued the grant, when, and the optional operator note.
    granted_by: str | None = None
    granted_at: datetime | None = None
    grant_reason: str | None = None
    # Revenue accounting (Phase 15): the amount actually charged for this
    # billing period in minor units plus the currency. Optional so pre-existing
    # documents (created before Phase 15) remain readable; the activation path
    # fills it from the plan's `price_cents` going forward. Admin grants always
    # carry `amount_cents=0` so they never count toward revenue.
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
        source: str = SUBSCRIPTION_SOURCE_PAYMENT,
        payment_provider: str | None = None,
        payment_id: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        period_days: int | None = None,
        amount_cents: int | None = None,
        currency: str | None = None,
        granted_by: str | None = None,
        granted_at: datetime | None = None,
        grant_reason: str | None = None,
    ) -> "Subscription":
        now = start_date or utcnow()
        if end_date is None and period_days:
            end_date = now + timedelta(days=period_days)
        return cls(
            id=new_id(),
            tenant_id=tenant_id,
            plan_id=plan_id,
            status=status,
            source=source,
            payment_provider=payment_provider,
            payment_id=payment_id,
            start_date=now,
            end_date=end_date,
            amount_cents=amount_cents,
            currency=currency,
            granted_by=granted_by,
            granted_at=granted_at,
            grant_reason=grant_reason,
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
    "PAID_SUBSCRIPTION_SOURCE",
    "SUBSCRIPTION_LIVE_STATUSES",
    "SUBSCRIPTION_SCHEMA_VERSION",
    "SUBSCRIPTION_SOURCES",
    "SUBSCRIPTION_SOURCE_ADMIN_GRANT",
    "SUBSCRIPTION_SOURCE_PAYMENT",
    "SUBSCRIPTION_STATUS_ACTIVE",
    "SUBSCRIPTION_STATUS_CANCELLED",
    "SUBSCRIPTION_STATUS_EXPIRED",
    "SUBSCRIPTION_STATUS_TRIALING",
    "SUBSCRIPTION_STATUSES",
    "Subscription",
]
