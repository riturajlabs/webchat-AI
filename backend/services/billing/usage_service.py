"""Subscription usage tracking and limit enforcement (Phase 13 billing).

`UsageService` is the single gate for SaaS limits:

    get_current_usage()   snapshot of live counts + monthly events vs limits
    check_limit()         raise `LimitReachedError` (code LIMIT_REACHED)
                          before an action that would exceed a plan cap
    record_usage()        append one `usage_events` document

Monthly totals come from `usage_events` summed over the current UTC calendar
month; website/document counts are authoritative live repository counts
(events never replace state). Enterprise (`None` limits) is never limited.

Phase 14 replaced the static plan lookup: the plan now resolves from the
tenant's active `subscriptions` document first, then `tenants.plan`, then Free
(`get_plan`). When no subscription repository is wired (legacy/tests) it falls
back to the Phase 13 behavior of reading `tenants.plan` directly.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from backend.core.errors import LimitReachedError, TenantNotFoundError
from backend.core.security import utcnow
from backend.models.plan import Plan, get_plan
from backend.models.usage_event import (
    USAGE_EVENT_CRAWL_PAGES,
    USAGE_EVENT_MESSAGES_SENT,
    USAGE_EVENT_TOKENS_USED,
    USAGE_EVENT_TYPES,
    UsageEvent,
)
from backend.repositories.document_repository import DocumentRepository
from backend.repositories.subscription_repository import SubscriptionRepository
from backend.repositories.tenant_repository import TenantRepository
from backend.repositories.usage_event_repository import (
    UsageEventRepository,
    UsageEventTotals,
)
from backend.repositories.website_repository import WebsiteRepository

# Enforcement metrics accepted by `check_limit` (superset of the recorded
# event types: "websites"/"documents" check live repository counts).
ENFORCEMENT_METRICS = frozenset(
    {
        USAGE_EVENT_MESSAGES_SENT,
        USAGE_EVENT_TOKENS_USED,
        USAGE_EVENT_CRAWL_PAGES,
        "websites",
        "documents",
    }
)


@dataclass(frozen=True)
class UsageMetric:
    """One limit row: used vs limit plus the utilization percentage.

    `percent` is `None` when the plan is unlimited (Enterprise / custom).
    """

    metric: str
    used: int
    limit: int | None
    percent: float | None


@dataclass(frozen=True)
class UsageSnapshot:
    """Everything the billing usage surface reports for a tenant."""

    plan: Plan
    totals: UsageEventTotals
    websites: int
    documents: int
    metrics: list[UsageMetric]


def _month_start(now: datetime) -> datetime:
    """First instant of `now`'s UTC calendar month (billing window)."""
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _percent(used: int, limit: int | None) -> float | None:
    """Utilization percentage (None when unlimited), 1 decimal place."""
    if limit is None or limit <= 0:
        return None
    return round(min(1.0, used / limit) * 100, 1)


class UsageService:
    """Owns plan resolution, usage aggregation and limit enforcement."""

    def __init__(
        self,
        *,
        events: UsageEventRepository,
        tenants: TenantRepository,
        websites: WebsiteRepository,
        documents: DocumentRepository,
        subscriptions: SubscriptionRepository | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._events = events
        self._tenants = tenants
        self._websites = websites
        self._documents = documents
        self._subscriptions = subscriptions
        self._now = now or utcnow

    # ------------------------------------------------------------------ reads

    async def get_plan(self, tenant_id: str) -> Plan:
        """Resolve the tenant's plan (active subscription > tenants.plan > Free)."""
        tenant = await self._tenants.find_by_id(tenant_id)
        if tenant is None:
            raise TenantNotFoundError("Tenant not found.")
        if self._subscriptions is not None:
            subscription = await self._subscriptions.find_active_by_tenant(
                tenant_id, now=self._now()
            )
            if subscription is not None:
                return get_plan(subscription.plan_id)
        return get_plan(tenant.plan)

    async def get_current_usage(self, tenant_id: str) -> UsageSnapshot:
        """Compute live counts + monthly events and limit utilization."""
        plan = await self.get_plan(tenant_id)
        totals = await self._events.totals_by_type_since(tenant_id, since=_month_start(self._now()))
        websites = await self._websites.count_by_tenant(tenant_id)
        documents = await self._documents.count_by_tenant(tenant_id)

        def metric(name: str, used: int) -> UsageMetric:
            limit = self._limit_for(plan, name)
            return UsageMetric(metric=name, used=used, limit=limit, percent=_percent(used, limit))

        metrics = [
            metric(USAGE_EVENT_MESSAGES_SENT, totals.messages_sent),
            metric("websites", websites),
            metric(USAGE_EVENT_TOKENS_USED, totals.tokens_used),
            metric("documents", documents),
            metric(USAGE_EVENT_CRAWL_PAGES, totals.crawl_pages),
        ]
        return UsageSnapshot(
            plan=plan,
            totals=totals,
            websites=websites,
            documents=documents,
            metrics=metrics,
        )

    # -------------------------------------------------------------- enforcement

    async def check_limit(
        self,
        tenant_id: str,
        *,
        event_type: str,
        quantity: int = 1,
    ) -> None:
        """Raise `LimitReachedError` if `quantity` more would exceed the cap.

        `event_type` is an enforcement metric (`messages_sent`, `tokens_used`,
        `crawl_pages`, `websites`, `documents`). Plans with no limit for the
        metric (unlimited / Enterprise) never raise.
        """
        if event_type not in ENFORCEMENT_METRICS:
            return
        if quantity <= 0:
            return
        plan = await self.get_plan(tenant_id)
        limit = self._limit_for(plan, event_type)
        if limit is None:
            return
        used = await self._used_for(tenant_id, event_type)
        if used + quantity > limit:
            raise LimitReachedError(
                f"The {plan.name} plan limit for {event_type} has been reached.",
                extra={"metric": event_type, "used": used, "limit": limit},
            )

    async def record_usage(
        self,
        *,
        tenant_id: str,
        user_id: str | None,
        website_id: str | None = None,
        event_type: str,
        quantity: int = 1,
    ) -> None:
        """Append one usage event (validated type, positive quantity)."""
        if event_type not in USAGE_EVENT_TYPES:
            raise ValueError(f"Unknown usage event type: {event_type}")
        if quantity <= 0:
            raise ValueError("Usage event quantity must be positive.")
        await self._events.record(
            UsageEvent.new(
                tenant_id=tenant_id,
                user_id=user_id,
                website_id=website_id,
                event_type=event_type,
                quantity=quantity,
            )
        )

    # ------------------------------------------------------------- internals

    @staticmethod
    def _limit_for(plan: Plan, metric: str) -> int | None:
        """Plan cap for an enforcement metric (None = unlimited)."""
        return {
            USAGE_EVENT_MESSAGES_SENT: plan.max_monthly_messages,
            USAGE_EVENT_TOKENS_USED: plan.max_monthly_tokens,
            USAGE_EVENT_CRAWL_PAGES: plan.max_crawl_pages,
            "websites": plan.max_websites,
            "documents": plan.max_documents,
        }.get(metric)

    async def _used_for(self, tenant_id: str, metric: str) -> int:
        """Current usage for an enforcement metric (live or event count)."""
        if metric == "websites":
            return await self._websites.count_by_tenant(tenant_id)
        if metric == "documents":
            return await self._documents.count_by_tenant(tenant_id)
        totals = await self._events.totals_by_type_since(tenant_id, since=_month_start(self._now()))
        return totals.total(metric)


__all__ = [
    "ENFORCEMENT_METRICS",
    "UsageMetric",
    "UsageService",
    "UsageSnapshot",
]
