"""Platform administration service (Phase 12.5 + Phase 15, SaaS admin).

Phase 12.5 (ADR-006) contributed the original super-admin surface: tenant/user
management, platform KPIs, the global crawl queue and the audit-log viewer.

Phase 15 extends it into a full SaaS operations panel:

    * RBAC is now `super_admin` only (see backend/core/rbac.py); every route
      is guarded by `require_admin` at the router boundary.
    * Tenant mutations gain dedicated actions (suspend / activate / change
      plan) that keep the shared `audit_logs` write AND append a platform-wide
      `admin_audit_logs` entry (the dedicated admin trail, ADR-006 §Security).
    * New read surface: `usage_totals`, `revenue_report` (from the Phase 14
      `subscriptions` append-log) and `collection_counts` for the system page.
    * `GET /api/admin/audit` reads the dedicated admin trail.

Self-targeting is hard-guarded: a super admin cannot suspend/plan-change their
own workspace or suspend/force-logout their own account.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from backend.core.errors import (
    ForbiddenError,
    PlanNotFoundError,
    TenantNotFoundError,
    UserNotFoundError,
)
from backend.core.security import utcnow
from backend.models.admin_audit_log import (
    ADMIN_AUDIT_FORCE_LOGOUT,
    ADMIN_AUDIT_TENANT_ACTIVATED,
    ADMIN_AUDIT_TENANT_PLAN_CHANGED,
    ADMIN_AUDIT_TENANT_SUSPENDED,
    ADMIN_AUDIT_USER_ACTIVATED,
    ADMIN_AUDIT_USER_SUSPENDED,
    AdminAuditLog,
)
from backend.models.audit_log import (
    AUDIT_FORCE_LOGOUT,
    AUDIT_TENANT_ACTIVATED,
    AUDIT_TENANT_PLAN_CHANGED,
    AUDIT_TENANT_SUSPENDED,
    AUDIT_USER_ACTIVATED,
    AUDIT_USER_SUSPENDED,
    AuditLog,
)
from backend.models.crawl_job import CrawlJob
from backend.models.plan import VALID_PLAN_IDS
from backend.models.subscription import Subscription
from backend.models.tenant import Tenant
from backend.models.user import User
from backend.repositories import (
    AdminAuditLogRepository,
    AdminRepository,
    AuditLogRepository,
    CollectionCounts,
    CrawlJobRepository,
    PlatformStats,
    PlatformUsage,
    RefreshTokenRepository,
    SubscriptionRepository,
    TenantRepository,
    TenantUsageSummary,
    UsageRecordRepository,
    UserRepository,
    WebsiteRepository,
)

# Cap on the revenue report's recent-payment detail.
REVENUE_RECENT_PAYMENTS_LIMIT = 20


@dataclass(frozen=True)
class TenantDetail:
    """Tenant plus the ADR-006 detail aggregates (websites, usage, status)."""

    tenant: Tenant
    website_count: int
    user_count: int
    active_crawl_jobs: int
    usage: TenantUsageSummary


@dataclass(frozen=True)
class RevenuePeriod:
    """One calendar month of collected revenue (Phase 15)."""

    period: str  # "2026-08"
    revenue_cents: int
    payments: int


@dataclass(frozen=True)
class RevenueReport:
    """Platform revenue from the Phase 14 `subscriptions` append-log."""

    total_revenue_cents: int
    paid_payments: int
    active_subscriptions: int
    currency: str
    periods: list[RevenuePeriod]
    recent_payments: list[Subscription]


class AdminService:
    """Super-admin operations over the existing collections."""

    def __init__(
        self,
        *,
        tenants: TenantRepository,
        users: UserRepository,
        websites: WebsiteRepository,
        usage: UsageRecordRepository,
        crawl_jobs: CrawlJobRepository,
        audit: AuditLogRepository,
        refresh_tokens: RefreshTokenRepository,
        stats: AdminRepository,
        subscriptions: SubscriptionRepository,
        admin_audit: AdminAuditLogRepository,
        currency: str = "USD",
    ) -> None:
        self._tenants = tenants
        self._users = users
        self._websites = websites
        self._usage = usage
        self._crawl_jobs = crawl_jobs
        self._audit = audit
        self._refresh_tokens = refresh_tokens
        self._stats = stats
        self._subscriptions = subscriptions
        self._admin_audit = admin_audit
        self._currency = currency

    # ----------------------------------------------------------- tenant reads

    async def list_tenants(
        self,
        *,
        page: int,
        per_page: int,
        search: str | None,
        plan: str | None,
        status: str | None,
    ) -> tuple[list[Tenant], int]:
        total = await self._tenants.count_tenants(search=search, plan=plan, status=status)
        items = await self._tenants.list_tenants(
            search=search,
            plan=plan,
            status=status,
            limit=per_page,
            offset=(page - 1) * per_page,
        )
        return items, total

    async def get_tenant_detail(self, tenant_id: str) -> TenantDetail:
        tenant = await self._tenants.find_by_id(tenant_id)
        if tenant is None:
            raise TenantNotFoundError("Tenant not found.")
        return TenantDetail(
            tenant=tenant,
            website_count=await self._websites.count_by_tenant(tenant_id),
            user_count=await self._users.count_by_tenant(tenant_id),
            active_crawl_jobs=await self._crawl_jobs.count_active_for_tenant(tenant_id),
            usage=await self._usage.sum_by_tenant(tenant_id),
        )

    # ----------------------------------------------------- tenant mutations

    async def update_tenant(
        self,
        *,
        tenant_id: str,
        status: str | None,
        plan: str | None,
        admin_user_id: str,
        admin_tenant_id: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> Tenant:
        """Legacy PATCH surface; Phase 15 actions are `suspend_tenant` etc."""
        if tenant_id == admin_tenant_id:
            raise ForbiddenError("Cannot change your own workspace.")
        tenant = await self._tenants.find_by_id(tenant_id)
        if tenant is None:
            raise TenantNotFoundError("Tenant not found.")

        if status is not None and status != tenant.status:
            await self._change_tenant_status(
                tenant=tenant,
                status=status,
                admin_user_id=admin_user_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        if plan is not None and plan != tenant.plan:
            await self._change_tenant_plan(
                tenant=tenant,
                plan_id=plan,
                admin_user_id=admin_user_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )

        await self._tenants.update(tenant)
        return tenant

    async def suspend_tenant(
        self,
        *,
        tenant_id: str,
        admin_user_id: str,
        admin_tenant_id: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> Tenant:
        """Suspend a workspace (idempotent; no-op when already suspended)."""
        return await self._require_tenant_mutation(
            tenant_id=tenant_id,
            admin_tenant_id=admin_tenant_id,
            action=lambda tenant: self._change_tenant_status(
                tenant=tenant,
                status="suspended",
                admin_user_id=admin_user_id,
                ip_address=ip_address,
                user_agent=user_agent,
            ),
        )

    async def activate_tenant(
        self,
        *,
        tenant_id: str,
        admin_user_id: str,
        admin_tenant_id: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> Tenant:
        """Re-activate a workspace (idempotent; no-op when already active)."""
        return await self._require_tenant_mutation(
            tenant_id=tenant_id,
            admin_tenant_id=admin_tenant_id,
            action=lambda tenant: self._change_tenant_status(
                tenant=tenant,
                status="active",
                admin_user_id=admin_user_id,
                ip_address=ip_address,
                user_agent=user_agent,
            ),
        )

    async def change_tenant_plan(
        self,
        *,
        tenant_id: str,
        plan_id: str,
        admin_user_id: str,
        admin_tenant_id: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> Tenant:
        """Override a workspace's plan (idempotent; no-op when already on it)."""
        if plan_id not in VALID_PLAN_IDS:
            raise PlanNotFoundError(f"Unknown plan: {plan_id}.")
        return await self._require_tenant_mutation(
            tenant_id=tenant_id,
            admin_tenant_id=admin_tenant_id,
            action=lambda tenant: self._change_tenant_plan(
                tenant=tenant,
                plan_id=plan_id,
                admin_user_id=admin_user_id,
                ip_address=ip_address,
                user_agent=user_agent,
            ),
        )

    async def _require_tenant_mutation(
        self,
        *,
        tenant_id: str,
        admin_tenant_id: str,
        action: Any,
    ) -> Tenant:
        if tenant_id == admin_tenant_id:
            raise ForbiddenError("Cannot change your own workspace.")
        tenant = await self._tenants.find_by_id(tenant_id)
        if tenant is None:
            raise TenantNotFoundError("Tenant not found.")
        await action(tenant)
        await self._tenants.update(tenant)
        return tenant

    # ------------------------------------------------------------ user reads

    async def list_users(
        self,
        *,
        page: int,
        per_page: int,
        search: str | None,
        status: str | None,
    ) -> tuple[list[User], int]:
        total = await self._users.count_users(search=search, status=status)
        items = await self._users.list_users(
            search=search,
            status=status,
            limit=per_page,
            offset=(page - 1) * per_page,
        )
        return items, total

    # --------------------------------------------------- user mutations

    async def suspend_user(
        self,
        *,
        tenant_id: str,
        user_id: str,
        admin_user_id: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> User:
        if user_id == admin_user_id:
            raise ForbiddenError("Cannot suspend your own account.")
        user = await self._require_user_in_tenant(tenant_id, user_id)
        if user.status != "suspended":
            await self._set_user_status(
                user=user,
                status="suspended",
                admin_user_id=admin_user_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        return user

    async def activate_user(
        self,
        *,
        tenant_id: str,
        user_id: str,
        admin_user_id: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> User:
        if user_id == admin_user_id:
            raise ForbiddenError("Cannot change your own account.")
        user = await self._require_user_in_tenant(tenant_id, user_id)
        if user.status != "active":
            await self._set_user_status(
                user=user,
                status="active",
                admin_user_id=admin_user_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        return user

    async def force_logout_user(
        self,
        *,
        tenant_id: str,
        user_id: str,
        admin_user_id: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> User:
        if user_id == admin_user_id:
            raise ForbiddenError("Cannot force logout your own account.")
        user = await self._require_user_in_tenant(tenant_id, user_id)
        await self._refresh_tokens.revoke_all_for_user(user.id, utcnow())
        await self._record_audits(
            action=AUDIT_FORCE_LOGOUT,
            admin_action=ADMIN_AUDIT_FORCE_LOGOUT,
            admin_user_id=admin_user_id,
            tenant_id=tenant_id,
            user_id=user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return user

    # --------------------------------------------------- platform reads

    async def platform_stats(self) -> PlatformStats:
        """Platform KPIs for the admin overview (ADR-006 §Platform Analytics)."""
        return await self._stats.platform_stats()

    async def usage_totals(self) -> PlatformUsage:
        """All-time platform usage for `GET /api/admin/usage` (Phase 15)."""
        return await self._stats.usage_totals()

    async def collection_counts(self) -> CollectionCounts:
        """Per-collection row counts for the system page (Phase 15)."""
        return await self._stats.collection_counts()

    async def revenue_report(
        self,
        *,
        since: datetime | None,
        until: datetime | None,
    ) -> RevenueReport:
        """Platform revenue from the `subscriptions` append-log (Phase 15).

        Only `active` subscriptions with a recorded `amount_cents` count as
        paid payments (a completed checkout creates such a document); months
        with no payments are omitted so the chart is data-driven.
        """
        paid = await self._subscriptions.list_paid(since=since, until=until)
        total_revenue_cents = sum(subscription.amount_cents or 0 for subscription in paid)
        periods: dict[str, list[int]] = {}
        for subscription in paid:
            key = subscription.created_at.strftime("%Y-%m")
            bucket = periods.setdefault(key, [0, 0])
            bucket[0] += subscription.amount_cents or 0
            bucket[1] += 1
        return RevenueReport(
            total_revenue_cents=total_revenue_cents,
            paid_payments=len(paid),
            active_subscriptions=await self._subscriptions.count_active(now=utcnow()),
            currency=self._currency,
            periods=[
                RevenuePeriod(period=key, revenue_cents=values[0], payments=values[1])
                for key, values in sorted(periods.items(), reverse=True)
            ],
            recent_payments=paid[:REVENUE_RECENT_PAYMENTS_LIMIT],
        )

    async def list_crawl_jobs(
        self,
        *,
        page: int,
        per_page: int,
        status: str | None,
    ) -> tuple[list[CrawlJob], int]:
        total = await self._crawl_jobs.count_any(status=status)
        items = await self._crawl_jobs.list_any(
            status=status,
            limit=per_page,
            offset=(page - 1) * per_page,
        )
        return items, total

    async def list_audit_logs(
        self,
        *,
        page: int,
        per_page: int,
        action: str | None,
        tenant_id: str | None,
        user_id: str | None,
        since: datetime | None,
        until: datetime | None,
    ) -> tuple[list[AuditLog], int]:
        total = await self._audit.count_audits(
            action=action,
            tenant_id=tenant_id,
            user_id=user_id,
            since=since,
            until=until,
        )
        items = await self._audit.list_audits(
            action=action,
            tenant_id=tenant_id,
            user_id=user_id,
            since=since,
            until=until,
            limit=per_page,
            offset=(page - 1) * per_page,
        )
        return items, total

    async def list_admin_audit_logs(
        self,
        *,
        page: int,
        per_page: int,
        action: str | None,
        actor_user_id: str | None,
        tenant_id: str | None,
        since: datetime | None,
        until: datetime | None,
    ) -> tuple[list[AdminAuditLog], int]:
        """The dedicated platform admin trail (Phase 15 `GET /api/admin/audit`)."""
        total = await self._admin_audit.count_logs(
            action=action,
            actor_user_id=actor_user_id,
            tenant_id=tenant_id,
            since=since,
            until=until,
        )
        items = await self._admin_audit.list_logs(
            action=action,
            actor_user_id=actor_user_id,
            tenant_id=tenant_id,
            since=since,
            until=until,
            limit=per_page,
            offset=(page - 1) * per_page,
        )
        return items, total

    # ------------------------------------------------------------ internals

    async def _change_tenant_status(
        self,
        *,
        tenant: Tenant,
        status: str,
        admin_user_id: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> None:
        if status == tenant.status:
            return
        tenant.status = status
        tenant.updated_at = utcnow()
        await self._record_audits(
            action=AUDIT_TENANT_SUSPENDED if status == "suspended" else AUDIT_TENANT_ACTIVATED,
            admin_action=(
                ADMIN_AUDIT_TENANT_SUSPENDED
                if status == "suspended"
                else ADMIN_AUDIT_TENANT_ACTIVATED
            ),
            admin_user_id=admin_user_id,
            tenant_id=tenant.id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def _change_tenant_plan(
        self,
        *,
        tenant: Tenant,
        plan_id: str,
        admin_user_id: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> None:
        if plan_id == tenant.plan:
            return
        tenant.plan = plan_id
        tenant.updated_at = utcnow()
        await self._record_audits(
            action=AUDIT_TENANT_PLAN_CHANGED,
            admin_action=ADMIN_AUDIT_TENANT_PLAN_CHANGED,
            admin_user_id=admin_user_id,
            tenant_id=tenant.id,
            plan_id=plan_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def _set_user_status(
        self,
        *,
        user: User,
        status: str,
        admin_user_id: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> None:
        await self._users.set_status(user.id, status, utcnow())
        user.status = status
        user.updated_at = utcnow()
        await self._record_audits(
            action=AUDIT_USER_SUSPENDED if status == "suspended" else AUDIT_USER_ACTIVATED,
            admin_action=(
                ADMIN_AUDIT_USER_SUSPENDED if status == "suspended" else ADMIN_AUDIT_USER_ACTIVATED
            ),
            admin_user_id=admin_user_id,
            tenant_id=user.tenant_id,
            user_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def _record_audits(
        self,
        *,
        action: str,
        admin_action: str,
        admin_user_id: str,
        tenant_id: str | None,
        user_id: str | None = None,
        plan_id: str | None = None,
        ip_address: str | None,
        user_agent: str | None,
    ) -> None:
        """Write the shared tenant audit AND the dedicated admin trail."""
        await self._audit.create(
            AuditLog.new(
                action=action,
                tenant_id=tenant_id,
                user_id=admin_user_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )
        await self._admin_audit.create(
            AdminAuditLog.new(
                action=admin_action,
                actor_user_id=admin_user_id,
                tenant_id=tenant_id,
                user_id=user_id,
                plan_id=plan_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

    async def _require_user_in_tenant(self, tenant_id: str, user_id: str) -> User:
        tenant = await self._tenants.find_by_id(tenant_id)
        if tenant is None:
            raise TenantNotFoundError("Tenant not found.")
        user = await self._users.find_by_id(user_id)
        if user is None or user.tenant_id != tenant_id:
            raise UserNotFoundError("User not found in this tenant.")
        return user


__all__ = [
    "AdminService",
    "RevenuePeriod",
    "RevenueReport",
    "TenantDetail",
]
