"""Pydantic v2 schemas for the admin API (Phase 12.5, ADR-006; extended for
Phase 15 SaaS ops and Phase 16 manual plan grants).

Every response type mirrors an existing model; the admin surface only adds
platform-wide fields (`tenant_id` on crawl jobs, counts on tenant detail).
Pagination bounds are shared with the feedback/conversation list APIs.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

MAX_ADMIN_PAGE_SIZE = 100
MAX_ADMIN_SEARCH_LENGTH = 100
MAX_ADMIN_GRANT_REASON_LENGTH = 500

# Effective-plan provenance (mirrors AdminService.ENTITLEMENT_SOURCE_*).
ENTITLEMENT_SOURCE_ADMIN_GRANT = "admin_grant"
ENTITLEMENT_SOURCE_SUBSCRIPTION = "subscription"
ENTITLEMENT_SOURCE_TENANT_PLAN = "tenant_plan"

TenantStatus = Literal["active", "suspended"]


class AdminTenantOut(BaseModel):
    """A tenant row in the admin tenant list.

    `effective_plan` is what the workspace actually gets right now - an active
    admin grant beats a paid subscription, which beats `tenants.plan`.
    """

    id: str
    company_name: str
    plan: str
    status: str
    effective_plan: str
    entitlement_source: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_tenant(cls, tenant: Any, *, entitlement: Any | None = None) -> "AdminTenantOut":
        return cls(
            id=tenant.id,
            company_name=tenant.company_name,
            plan=tenant.plan,
            status=tenant.status,
            effective_plan=(entitlement.effective_plan if entitlement is not None else tenant.plan),
            entitlement_source=(
                entitlement.source if entitlement is not None else ENTITLEMENT_SOURCE_TENANT_PLAN
            ),
            created_at=tenant.created_at,
            updated_at=tenant.updated_at,
        )


class AdminTenantUsageOut(BaseModel):
    """All-time usage totals for a tenant's detail view."""

    conversations: int
    messages: int
    input_tokens: int
    output_tokens: int


class AdminTenantDetailOut(AdminTenantOut):
    """Tenant detail with the ADR-006 aggregates and current subscription."""

    website_count: int
    user_count: int
    active_crawl_jobs: int
    usage: AdminTenantUsageOut
    active_subscription: "AdminSubscriptionOut | None" = None


class AdminTenantUpdateRequest(BaseModel):
    """PATCH body: suspend/activate and optional plan change (ADR-006)."""

    status: TenantStatus | None = None
    plan: str | None = Field(default=None, min_length=1, max_length=50)


class AdminTenantListResponse(BaseModel):
    items: list[AdminTenantOut]
    total: int
    page: int
    per_page: int


class AdminUserOut(BaseModel):
    """A platform user row in the admin user list.

    `effective_plan` mirrors the tenant's resolved entitlement so operators
    can see which workspace plan the user's account falls under.
    """

    id: str
    name: str
    email: str
    role: str
    status: str
    email_verified: bool
    tenant_id: str
    effective_plan: str = "free"
    entitlement_source: str = ENTITLEMENT_SOURCE_TENANT_PLAN
    last_login: datetime | None
    created_at: datetime

    @classmethod
    def from_user(cls, user: Any, *, entitlement: Any | None = None) -> "AdminUserOut":
        return cls(
            id=user.id,
            name=user.name,
            email=user.email,
            role=user.role,
            status=user.status,
            email_verified=user.email_verified,
            tenant_id=user.tenant_id,
            effective_plan=(entitlement.effective_plan if entitlement is not None else "free"),
            entitlement_source=(
                entitlement.source if entitlement is not None else ENTITLEMENT_SOURCE_TENANT_PLAN
            ),
            last_login=user.last_login,
            created_at=user.created_at,
        )


class AdminUserListResponse(BaseModel):
    items: list[AdminUserOut]
    total: int
    page: int
    per_page: int


class AdminTenantCounts(BaseModel):
    total: int
    active: int
    suspended: int


class AdminUserCounts(BaseModel):
    total: int
    active: int
    suspended: int


class AdminUsageTotals(BaseModel):
    conversations: int
    messages: int
    input_tokens: int
    output_tokens: int
    total_tokens: int


class AdminCrawlStats(BaseModel):
    total: int
    active: int
    failed: int
    error_rate: float


class AdminStatsOut(BaseModel):
    """Platform KPIs (`GET /api/admin/stats`, ADR-006 §Platform Analytics)."""

    tenants: AdminTenantCounts
    users: AdminUserCounts
    usage: AdminUsageTotals
    crawl_jobs: AdminCrawlStats


class AdminCrawlJobOut(BaseModel):
    """A crawl job row in the global queue monitor."""

    id: str
    tenant_id: str
    website_id: str
    status: str
    pages_total: int
    pages_completed: int
    error_message: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_job(cls, job: Any) -> "AdminCrawlJobOut":
        return cls(
            id=job.id,
            tenant_id=job.tenant_id,
            website_id=job.website_id,
            status=job.status,
            pages_total=job.pages_total,
            pages_completed=job.pages_completed,
            error_message=job.error_message,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )


class AdminCrawlJobListResponse(BaseModel):
    items: list[AdminCrawlJobOut]
    total: int
    page: int
    per_page: int


class AdminAuditLogOut(BaseModel):
    """An audit event row in the admin viewer."""

    id: str
    tenant_id: str | None
    user_id: str | None
    action: str
    ip_address: str | None
    user_agent: str | None
    grant_reason: str | None = None
    created_at: datetime

    @classmethod
    def from_log(cls, log: Any) -> "AdminAuditLogOut":
        return cls(
            id=log.id,
            tenant_id=log.tenant_id,
            user_id=log.user_id,
            action=log.action,
            ip_address=log.ip_address,
            user_agent=log.user_agent,
            grant_reason=getattr(log, "grant_reason", None),
            created_at=log.created_at,
        )


class AdminAuditLogListResponse(BaseModel):
    items: list[AdminAuditLogOut]
    total: int
    page: int
    per_page: int


class AdminSystemCountsOut(BaseModel):
    """Per-collection row counts for the system page (Phase 15)."""

    users: int
    tenants: int
    websites: int
    widgets: int
    documents: int
    chat_sessions: int
    messages: int
    usage_records: int
    api_keys: int
    subscriptions: int
    audit_logs: int
    admin_audit_logs: int

    @classmethod
    def from_counts(cls, counts: Any) -> "AdminSystemCountsOut":
        return cls(
            users=counts.users,
            tenants=counts.tenants,
            websites=counts.websites,
            widgets=counts.widgets,
            documents=counts.documents,
            chat_sessions=counts.chat_sessions,
            messages=counts.messages,
            usage_records=counts.usage_records,
            api_keys=counts.api_keys,
            subscriptions=counts.subscriptions,
            audit_logs=counts.audit_logs,
            admin_audit_logs=counts.admin_audit_logs,
        )


class AdminOverviewOut(BaseModel):
    """Dashboard overview (`GET /api/admin/overview`, Phase 15).

    One payload for the overview page: the KPI stats, collection counts, and
    the revenue headline (active subscriptions + total collected).
    """

    stats: AdminStatsOut
    counts: AdminSystemCountsOut
    active_subscriptions: int
    total_revenue_cents: int
    currency: str


class AdminUsageOut(BaseModel):
    """All-time platform usage (`GET /api/admin/usage`, Phase 15)."""

    conversations: int
    messages: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    embeddings_created: int
    vector_queries: int
    crawl_pages: int


class AdminSubscriptionOut(BaseModel):
    """A subscription-history row for the revenue page (Phase 15).

    Includes Phase 16 admin-grant provenance (`source`, `granted_*`) so paid
    subscriptions and operator grants are distinguishable at a glance.
    """

    id: str
    tenant_id: str
    plan_id: str
    status: str
    source: str = "payment"
    payment_provider: str | None
    payment_id: str | None
    start_date: datetime
    end_date: datetime | None
    amount_cents: int | None
    currency: str | None
    granted_by: str | None = None
    granted_at: datetime | None = None
    grant_reason: str | None = None
    created_at: datetime

    @classmethod
    def from_subscription(cls, subscription: Any) -> "AdminSubscriptionOut":
        return cls(
            id=subscription.id,
            tenant_id=subscription.tenant_id,
            plan_id=subscription.plan_id,
            status=subscription.status,
            source=subscription.source,
            payment_provider=subscription.payment_provider,
            payment_id=subscription.payment_id,
            start_date=subscription.start_date,
            end_date=subscription.end_date,
            amount_cents=subscription.amount_cents,
            currency=subscription.currency,
            granted_by=subscription.granted_by,
            granted_at=subscription.granted_at,
            grant_reason=subscription.grant_reason,
            created_at=subscription.created_at,
        )


class AdminRevenuePeriodOut(BaseModel):
    """One calendar month of collected revenue (Phase 15)."""

    period: str
    revenue_cents: int
    payments: int


class AdminRevenueReportOut(BaseModel):
    """Platform revenue report (`GET /api/admin/revenue`, Phase 15)."""

    total_revenue_cents: int
    paid_payments: int
    active_subscriptions: int
    currency: str
    periods: list[AdminRevenuePeriodOut]
    recent_payments: list[AdminSubscriptionOut]


class AdminCheckOut(BaseModel):
    """A dependency probe result for the system page (Phase 15)."""

    name: str
    status: str  # "ok" | "degraded"


class AdminSystemHealthOut(BaseModel):
    """System health (`GET /api/admin/system-health`, Phase 15).

    Fails closed on any probe: `status` is `degraded` unless every check is
    `ok`. `counts` reuses the per-collection row counts so the system page
    renders storage at a glance.
    """

    status: str
    checks: list[AdminCheckOut]
    counts: AdminSystemCountsOut
    checked_at: datetime


class AdminTenantPlanRequest(BaseModel):
    """POST body for `POST /api/admin/tenants/{tenant_id}/plan` (Phase 15)."""

    plan: str = Field(min_length=1, max_length=50)


class AdminGrantPlanRequest(BaseModel):
    """POST body for `POST /api/admin/tenants/{tenant_id}/grant-plan` (Phase 16).

    `expires_at` may be `null` for an open-ended grant; when set it must lie in
    the future. `reason` is an optional operator note stored on the grant and
    surfaced in audit trails.
    """

    plan: str = Field(min_length=1, max_length=50)
    expires_at: datetime | None = None
    reason: str | None = Field(default=None, max_length=MAX_ADMIN_GRANT_REASON_LENGTH)


class AdminGrantResultOut(BaseModel):
    """Response for grant/revoke operations (Phase 16).

    `grant` is the active admin-grant subscription after the operation (None on
    revoke); `changed` distinguishes a no-op idempotent re-grant (audit trail is
    only written when `True`).
    """

    tenant: AdminTenantOut
    grant: AdminSubscriptionOut | None
    changed: bool


class AdminAdminAuditLogOut(BaseModel):
    """A platform operator action row (dedicated admin trail, Phase 15)."""

    id: str
    actor_user_id: str | None
    action: str
    tenant_id: str | None
    user_id: str | None
    plan_id: str | None
    ip_address: str | None
    user_agent: str | None
    grant_reason: str | None = None
    created_at: datetime

    @classmethod
    def from_log(cls, log: Any) -> "AdminAdminAuditLogOut":
        return cls(
            id=log.id,
            actor_user_id=log.actor_user_id,
            action=log.action,
            tenant_id=log.tenant_id,
            user_id=log.user_id,
            plan_id=log.plan_id,
            ip_address=log.ip_address,
            user_agent=log.user_agent,
            grant_reason=getattr(log, "grant_reason", None),
            created_at=log.created_at,
        )


class AdminAdminAuditLogListResponse(BaseModel):
    items: list[AdminAdminAuditLogOut]
    total: int
    page: int
    per_page: int


__all__ = [
    "ENTITLEMENT_SOURCE_ADMIN_GRANT",
    "ENTITLEMENT_SOURCE_SUBSCRIPTION",
    "ENTITLEMENT_SOURCE_TENANT_PLAN",
    "MAX_ADMIN_GRANT_REASON_LENGTH",
    "AdminAdminAuditLogListResponse",
    "AdminAdminAuditLogOut",
    "AdminAuditLogListResponse",
    "AdminAuditLogOut",
    "AdminCheckOut",
    "AdminCrawlJobListResponse",
    "AdminCrawlJobOut",
    "AdminCrawlStats",
    "AdminGrantPlanRequest",
    "AdminGrantResultOut",
    "AdminOverviewOut",
    "AdminRevenuePeriodOut",
    "AdminRevenueReportOut",
    "AdminStatsOut",
    "AdminSubscriptionOut",
    "AdminSystemCountsOut",
    "AdminSystemHealthOut",
    "AdminTenantCounts",
    "AdminTenantDetailOut",
    "AdminTenantListResponse",
    "AdminTenantOut",
    "AdminTenantPlanRequest",
    "AdminTenantUpdateRequest",
    "AdminTenantUsageOut",
    "AdminUsageOut",
    "AdminUsageTotals",
    "AdminUserCounts",
    "AdminUserListResponse",
    "AdminUserOut",
    "MAX_ADMIN_PAGE_SIZE",
    "MAX_ADMIN_SEARCH_LENGTH",
]
