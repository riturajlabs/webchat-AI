"""Subscription lifecycle service (Phase 14, SaaS subscriptions).

Owns everything the read-only Phase 13 billing surface could not:

    create_checkout()        start a provider-hosted checkout for a plan
    activate_payment()       webhook-driven: record a successful payment as a
                             new `subscriptions` document (payment history)
    get_current_subscription()  the plan-granting subscription (or None)
    get_effective_plan()     subscription plan > `tenants.plan` > Free
    get_report()             current subscription + payment history for the
                             dashboard Billing page

Design rules:

* `subscriptions` is append-only per payment: one document per paid billing
  period. `list_by_tenant` therefore *is* the payment history.
* Activation is idempotent on `payment_id` (the gateway's idempotency key): a
  replayed webhook must not mint a second document.
* Only signature-verified `paid` events (from the provider `parse_webhook`)
  reach `activate_payment`; the service re-validates status + ids defensively.
* Plan enforcement reads the active subscription via `UsageService`; the
  tenant `plan` field remains the signup default / fallback.
"""

from collections.abc import Callable
from datetime import datetime

from backend.core.errors import PlanNotPurchasableError
from backend.core.security import utcnow
from backend.models.plan import Plan, get_plan
from backend.models.subscription import (
    SUBSCRIPTION_LIVE_STATUSES,
    SUBSCRIPTION_STATUS_ACTIVE,
    SUBSCRIPTION_STATUS_EXPIRED,
    Subscription,
)
from backend.repositories.subscription_repository import SubscriptionRepository
from backend.repositories.tenant_repository import TenantRepository
from backend.services.billing.payments import (
    PAYMENT_STATUS_PAID,
    PaymentCheckout,
    PaymentProvider,
    WebhookEvent,
)

DEFAULT_BILLING_PERIOD_DAYS = 30


class SubscriptionService:
    """Checkout, webhook activation and subscription reads."""

    def __init__(
        self,
        *,
        subscriptions: SubscriptionRepository,
        provider: PaymentProvider,
        tenants: TenantRepository,
        currency: str = "USD",
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._subscriptions = subscriptions
        self._provider = provider
        self._tenants = tenants
        self._currency = currency
        self._now = now or utcnow

    # ---------------------------------------------------------------- checkout

    async def create_checkout(
        self,
        *,
        tenant_id: str,
        plan_id: str,
        success_url: str,
        cancel_url: str,
    ) -> PaymentCheckout:
        """Start a hosted checkout for `plan_id`; raises if not purchasable.

        Free (trial) and Enterprise (sales) have no self-serve price, so they
        are rejected up front with `PlanNotPurchasableError`.
        """
        plan = get_plan(plan_id)
        if plan.price_cents is None or plan.price_cents <= 0:
            raise PlanNotPurchasableError(
                f"The {plan.name} plan cannot be purchased through checkout."
            )
        return await self._provider.create_checkout(
            tenant_id=tenant_id,
            plan_id=plan.id,
            amount_cents=plan.price_cents,
            currency=self._currency,
            success_url=success_url,
            cancel_url=cancel_url,
        )

    # ------------------------------------------------------------- activation

    async def activate_payment(self, event: WebhookEvent) -> Subscription | None:
        """Record a paid webhook event as a new subscription (idempotent).

        Returns the created `Subscription`, or `None` when the event is not a
        `paid` payment or has already been processed (same `payment_id`).
        """
        if event.status != PAYMENT_STATUS_PAID:
            return None
        if not event.payment_id or not event.tenant_id or not event.plan_id:
            return None
        if await self._subscriptions.find_by_payment_id(event.payment_id) is not None:
            return None
        plan = get_plan(event.plan_id)
        period_days = plan.billing_period_days or DEFAULT_BILLING_PERIOD_DAYS
        now = self._now()
        subscription = Subscription.new(
            tenant_id=event.tenant_id,
            plan_id=plan.id,
            status=SUBSCRIPTION_STATUS_ACTIVE,
            payment_provider=self._provider.name,
            payment_id=event.payment_id,
            start_date=now,
            period_days=period_days,
            # Phase 15 revenue accounting: the price actually charged for this
            # period, persisted so `/api/admin/revenue` can aggregate it.
            amount_cents=plan.price_cents,
            currency=self._currency,
        )
        await self._subscriptions.create(subscription)
        return subscription

    # ------------------------------------------------------------------ reads

    async def get_current_subscription(self, tenant_id: str) -> Subscription | None:
        """The newest plan-granting subscription for the tenant (or None)."""
        return await self._subscriptions.find_active_by_tenant(
            tenant_id, now=self._now()
        )

    async def get_effective_plan(self, tenant_id: str) -> Plan:
        """Resolve the tenant's plan: subscription > tenants.plan > Free."""
        subscription = await self.get_current_subscription(tenant_id)
        if subscription is not None:
            return get_plan(subscription.plan_id)
        tenant = await self._tenants.find_by_id(tenant_id)
        if tenant is None:
            return get_plan("free")
        return get_plan(tenant.plan)

    async def get_report(
        self, tenant_id: str
    ) -> tuple[Subscription | None, list[Subscription]]:
        """Return (current subscription, payment history) for the Billing page.

        When the newest subscription has lapsed (`end_date` passed) its status
        is reported as `expired` so the dashboard can show the fallback state
        while payment history still records the raw documents.
        """
        current = await self.get_current_subscription(tenant_id)
        history = await self._subscriptions.list_by_tenant(tenant_id, limit=50)
        if current is None and history:
            latest = history[0]
            if (
                latest.status in SUBSCRIPTION_LIVE_STATUSES
                and latest.end_date is not None
                and latest.end_date < self._now()
            ):
                return self._expired_copy(latest), history
            return latest, history
        return current, history

    @staticmethod
    def _expired_copy(subscription: Subscription) -> Subscription:
        return subscription.model_copy(update={"status": SUBSCRIPTION_STATUS_EXPIRED})


__all__ = [
    "DEFAULT_BILLING_PERIOD_DAYS",
    "SubscriptionService",
]
