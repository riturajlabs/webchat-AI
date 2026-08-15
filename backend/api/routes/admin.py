"""Platform administration endpoints (Phase 12.5 + Phase 15, SaaS admin).

Phase 12.5 (ADR-006):

    GET    /api/admin/tenants                        list/search tenants (paginated)
    GET    /api/admin/tenants/{tenant_id}            tenant detail (websites, usage, status)
    PATCH  /api/admin/tenants/{tenant_id}            suspend/activate / plan change
    GET    /api/admin/users                          list/search users (paginated)
    POST   /api/admin/tenants/{tenant_id}/users/{user_id}/suspend        suspend a user
    POST   /api/admin/tenants/{tenant_id}/users/{user_id}/force-logout    revoke sessions
    GET    /api/admin/stats                          platform KPIs
    GET    /api/admin/crawl-jobs                     global crawl queue monitor
    GET    /api/admin/audit-logs                     shared audit-log viewer

Phase 15 (SaaS operations panel):

    GET    /api/admin/overview                       dashboard overview (KPIs + counts + revenue)
    GET    /api/admin/tenants                        + `plan`/`status` filters
    POST   /api/admin/tenants/{tenant_id}/suspend    suspend a workspace
    POST   /api/admin/tenants/{tenant_id}/activate   re-activate a workspace
    POST   /api/admin/tenants/{tenant_id}/plan       override a workspace plan
    POST   /api/admin/tenants/{tenant_id}/users/{user_id}/activate       re-activate a user
    GET    /api/admin/revenue                        revenue report (monthly + recent payments)
    GET    /api/admin/usage                          all-time platform usage
    GET    /api/admin/system-health                  dependency probes + collection counts
    GET    /api/admin/audit                          dedicated admin trail (Phase 15)

Every route requires a bearer access token resolving to the platform
`super_admin` role (`require_admin`), granted only through `SUPER_ADMIN_EMAILS`
configuration (backend/core/rbac.py). Owners/tenants below receive the existing
403 `FORBIDDEN`. All mutations write the shared audit AND the dedicated
`admin_audit_logs` trail, and are rate-limited with the admin budget
(ADR-006 §Admin UI).
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response

from backend.api.deps import (
    admin_limiter,
    client_ip,
    current_user,
    get_admin_service,
    require_admin,
)
from backend.core.database import MongoDB
from backend.core.redis import ping_redis
from backend.core.security import utcnow
from backend.repositories import PlatformStats
from backend.schemas.admin import (
    MAX_ADMIN_PAGE_SIZE,
    MAX_ADMIN_SEARCH_LENGTH,
    AdminAdminAuditLogListResponse,
    AdminAdminAuditLogOut,
    AdminAuditLogListResponse,
    AdminAuditLogOut,
    AdminCheckOut,
    AdminCrawlJobListResponse,
    AdminCrawlJobOut,
    AdminCrawlStats,
    AdminOverviewOut,
    AdminRevenuePeriodOut,
    AdminRevenueReportOut,
    AdminStatsOut,
    AdminSubscriptionOut,
    AdminSystemCountsOut,
    AdminSystemHealthOut,
    AdminTenantCounts,
    AdminTenantDetailOut,
    AdminTenantListResponse,
    AdminTenantOut,
    AdminTenantPlanRequest,
    AdminTenantUpdateRequest,
    AdminTenantUsageOut,
    AdminUsageOut,
    AdminUsageTotals,
    AdminUserCounts,
    AdminUserListResponse,
    AdminUserOut,
)
from backend.services.admin import AdminService
from backend.services.auth import Principal

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin())],
)


def _stats_out(stats: PlatformStats) -> AdminStatsOut:
    """Map `PlatformStats` onto the ADR-006 stats response shape."""
    total_tokens = stats.total_input_tokens + stats.total_output_tokens
    error_rate = (
        round(stats.failed_crawl_jobs / stats.total_crawl_jobs, 4)
        if stats.total_crawl_jobs
        else 0.0
    )
    return AdminStatsOut(
        tenants=AdminTenantCounts(
            total=stats.total_tenants,
            active=stats.active_tenants,
            suspended=stats.suspended_tenants,
        ),
        users=AdminUserCounts(
            total=stats.total_users,
            active=stats.active_users,
            suspended=stats.suspended_users,
        ),
        usage=AdminUsageTotals(
            conversations=stats.total_conversations,
            messages=stats.total_messages,
            input_tokens=stats.total_input_tokens,
            output_tokens=stats.total_output_tokens,
            total_tokens=total_tokens,
        ),
        crawl_jobs=AdminCrawlStats(
            total=stats.total_crawl_jobs,
            active=stats.active_crawl_jobs,
            failed=stats.failed_crawl_jobs,
            error_rate=error_rate,
        ),
    )


@router.get("/overview", response_model=AdminOverviewOut)
async def overview(
    service: Annotated[AdminService, Depends(get_admin_service)],
    _: Annotated[None, Depends(admin_limiter)],
) -> AdminOverviewOut:
    """Dashboard overview: KPIs, collection counts, revenue headline (Phase 15)."""
    stats = await service.platform_stats()
    counts = await service.collection_counts()
    revenue = await service.revenue_report(since=None, until=None)
    return AdminOverviewOut(
        stats=_stats_out(stats),
        counts=AdminSystemCountsOut.from_counts(counts),
        active_subscriptions=revenue.active_subscriptions,
        total_revenue_cents=revenue.total_revenue_cents,
        currency=revenue.currency,
    )


@router.get("/tenants", response_model=AdminTenantListResponse)
async def list_tenants(
    service: Annotated[AdminService, Depends(get_admin_service)],
    _: Annotated[None, Depends(admin_limiter)],
    response: Response,
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=MAX_ADMIN_PAGE_SIZE)] = 20,
    search: Annotated[
        str | None, Query(max_length=MAX_ADMIN_SEARCH_LENGTH, description="Filter by company name")
    ] = None,
    plan: Annotated[str | None, Query(description="Filter by plan")] = None,
    status: Annotated[
        str | None, Query(pattern="^(active|suspended)$", description="Filter by status")
    ] = None,
) -> AdminTenantListResponse:
    items, total = await service.list_tenants(
        page=page, per_page=per_page, search=search, plan=plan, status=status
    )
    response.headers["X-Total-Count"] = str(total)
    return AdminTenantListResponse(
        items=[AdminTenantOut.from_tenant(item) for item in items],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/tenants/{tenant_id}", response_model=AdminTenantDetailOut)
async def get_tenant_detail(
    tenant_id: str,
    service: Annotated[AdminService, Depends(get_admin_service)],
    _: Annotated[None, Depends(admin_limiter)],
) -> AdminTenantDetailOut:
    detail = await service.get_tenant_detail(tenant_id)
    tenant = detail.tenant
    return AdminTenantDetailOut(
        id=tenant.id,
        company_name=tenant.company_name,
        plan=tenant.plan,
        status=tenant.status,
        created_at=tenant.created_at,
        updated_at=tenant.updated_at,
        website_count=detail.website_count,
        user_count=detail.user_count,
        active_crawl_jobs=detail.active_crawl_jobs,
        usage=AdminTenantUsageOut(
            conversations=detail.usage.chats,
            messages=detail.usage.messages,
            input_tokens=detail.usage.input_tokens,
            output_tokens=detail.usage.output_tokens,
        ),
    )


@router.patch("/tenants/{tenant_id}", response_model=AdminTenantOut)
async def update_tenant(
    tenant_id: str,
    body: AdminTenantUpdateRequest,
    request: Request,
    principal: Annotated[Principal, Depends(current_user)],
    service: Annotated[AdminService, Depends(get_admin_service)],
    _: Annotated[None, Depends(admin_limiter)],
) -> AdminTenantOut:
    if body.status is None and body.plan is None:
        detail = await service.get_tenant_detail(tenant_id)
        return AdminTenantOut.from_tenant(detail.tenant)
    tenant = await service.update_tenant(
        tenant_id=tenant_id,
        status=body.status,
        plan=body.plan,
        admin_user_id=principal.user_id,
        admin_tenant_id=principal.tenant_id,
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return AdminTenantOut.from_tenant(tenant)


@router.post("/tenants/{tenant_id}/suspend", response_model=AdminTenantOut, status_code=200)
async def suspend_tenant(
    tenant_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(current_user)],
    service: Annotated[AdminService, Depends(get_admin_service)],
    _: Annotated[None, Depends(admin_limiter)],
) -> AdminTenantOut:
    tenant = await service.suspend_tenant(
        tenant_id=tenant_id,
        admin_user_id=principal.user_id,
        admin_tenant_id=principal.tenant_id,
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return AdminTenantOut.from_tenant(tenant)


@router.post("/tenants/{tenant_id}/activate", response_model=AdminTenantOut, status_code=200)
async def activate_tenant(
    tenant_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(current_user)],
    service: Annotated[AdminService, Depends(get_admin_service)],
    _: Annotated[None, Depends(admin_limiter)],
) -> AdminTenantOut:
    tenant = await service.activate_tenant(
        tenant_id=tenant_id,
        admin_user_id=principal.user_id,
        admin_tenant_id=principal.tenant_id,
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return AdminTenantOut.from_tenant(tenant)


@router.post("/tenants/{tenant_id}/plan", response_model=AdminTenantOut, status_code=200)
async def change_tenant_plan(
    tenant_id: str,
    body: AdminTenantPlanRequest,
    request: Request,
    principal: Annotated[Principal, Depends(current_user)],
    service: Annotated[AdminService, Depends(get_admin_service)],
    _: Annotated[None, Depends(admin_limiter)],
) -> AdminTenantOut:
    tenant = await service.change_tenant_plan(
        tenant_id=tenant_id,
        plan_id=body.plan,
        admin_user_id=principal.user_id,
        admin_tenant_id=principal.tenant_id,
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return AdminTenantOut.from_tenant(tenant)


@router.get("/users", response_model=AdminUserListResponse)
async def list_users(
    service: Annotated[AdminService, Depends(get_admin_service)],
    _: Annotated[None, Depends(admin_limiter)],
    response: Response,
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=MAX_ADMIN_PAGE_SIZE)] = 20,
    search: Annotated[
        str | None, Query(max_length=MAX_ADMIN_SEARCH_LENGTH, description="Filter by name or email")
    ] = None,
    status: Annotated[str | None, Query(pattern="^(active|suspended)$")] = None,
) -> AdminUserListResponse:
    items, total = await service.list_users(
        page=page, per_page=per_page, search=search, status=status
    )
    response.headers["X-Total-Count"] = str(total)
    return AdminUserListResponse(
        items=[AdminUserOut.from_user(item) for item in items],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.post(
    "/tenants/{tenant_id}/users/{user_id}/suspend",
    response_model=AdminUserOut,
    status_code=200,
)
async def suspend_user(
    tenant_id: str,
    user_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(current_user)],
    service: Annotated[AdminService, Depends(get_admin_service)],
    _: Annotated[None, Depends(admin_limiter)],
) -> AdminUserOut:
    user = await service.suspend_user(
        tenant_id=tenant_id,
        user_id=user_id,
        admin_user_id=principal.user_id,
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return AdminUserOut.from_user(user)


@router.post(
    "/tenants/{tenant_id}/users/{user_id}/activate",
    response_model=AdminUserOut,
    status_code=200,
)
async def activate_user(
    tenant_id: str,
    user_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(current_user)],
    service: Annotated[AdminService, Depends(get_admin_service)],
    _: Annotated[None, Depends(admin_limiter)],
) -> AdminUserOut:
    user = await service.activate_user(
        tenant_id=tenant_id,
        user_id=user_id,
        admin_user_id=principal.user_id,
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return AdminUserOut.from_user(user)


@router.post(
    "/tenants/{tenant_id}/users/{user_id}/force-logout",
    response_model=AdminUserOut,
    status_code=200,
)
async def force_logout_user(
    tenant_id: str,
    user_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(current_user)],
    service: Annotated[AdminService, Depends(get_admin_service)],
    _: Annotated[None, Depends(admin_limiter)],
) -> AdminUserOut:
    user = await service.force_logout_user(
        tenant_id=tenant_id,
        user_id=user_id,
        admin_user_id=principal.user_id,
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return AdminUserOut.from_user(user)


@router.get("/stats", response_model=AdminStatsOut)
async def platform_stats(
    service: Annotated[AdminService, Depends(get_admin_service)],
    _: Annotated[None, Depends(admin_limiter)],
) -> AdminStatsOut:
    return _stats_out(await service.platform_stats())


@router.get("/usage", response_model=AdminUsageOut)
async def usage(
    service: Annotated[AdminService, Depends(get_admin_service)],
    _: Annotated[None, Depends(admin_limiter)],
) -> AdminUsageOut:
    """All-time platform usage rollups (Phase 15)."""
    totals = await service.usage_totals()
    return AdminUsageOut(
        conversations=totals.conversations,
        messages=totals.messages,
        input_tokens=totals.input_tokens,
        output_tokens=totals.output_tokens,
        total_tokens=totals.total_tokens,
        embeddings_created=totals.embeddings_created,
        vector_queries=totals.vector_queries,
        crawl_pages=totals.crawl_pages,
    )


@router.get("/revenue", response_model=AdminRevenueReportOut)
async def revenue(
    service: Annotated[AdminService, Depends(get_admin_service)],
    _: Annotated[None, Depends(admin_limiter)],
    since: Annotated[datetime | None, Query(description="Inclusive start (ISO)")] = None,
    until: Annotated[datetime | None, Query(description="Inclusive end (ISO)")] = None,
) -> AdminRevenueReportOut:
    """Platform revenue report from the Phase 14 subscription log (Phase 15)."""
    report = await service.revenue_report(since=since, until=until)
    return AdminRevenueReportOut(
        total_revenue_cents=report.total_revenue_cents,
        paid_payments=report.paid_payments,
        active_subscriptions=report.active_subscriptions,
        currency=report.currency,
        periods=[
            AdminRevenuePeriodOut(
                period=period.period,
                revenue_cents=period.revenue_cents,
                payments=period.payments,
            )
            for period in report.periods
        ],
        recent_payments=[
            AdminSubscriptionOut.from_subscription(subscription)
            for subscription in report.recent_payments
        ],
    )


@router.get("/system-health", response_model=AdminSystemHealthOut)
async def system_health(
    service: Annotated[AdminService, Depends(get_admin_service)],
    _: Annotated[None, Depends(admin_limiter)],
) -> AdminSystemHealthOut:
    """Dependency probes + collection counts (Phase 15).

    Fails closed: `status` is `degraded` unless every probe is `ok`, mirroring
    the public `/api/health/ready` contract.
    """
    database_ok = await MongoDB.ping()
    redis_ok = await ping_redis()
    checks = [
        AdminCheckOut(name="database", status="ok" if database_ok else "degraded"),
        AdminCheckOut(name="redis", status="ok" if redis_ok else "degraded"),
    ]
    counts = await service.collection_counts()
    return AdminSystemHealthOut(
        status="ok" if all(check.status == "ok" for check in checks) else "degraded",
        checks=checks,
        counts=AdminSystemCountsOut.from_counts(counts),
        checked_at=utcnow(),
    )


@router.get("/crawl-jobs", response_model=AdminCrawlJobListResponse)
async def list_crawl_jobs(
    service: Annotated[AdminService, Depends(get_admin_service)],
    _: Annotated[None, Depends(admin_limiter)],
    response: Response,
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=MAX_ADMIN_PAGE_SIZE)] = 20,
    status: Annotated[
        str | None,
        Query(pattern="^(pending|running|processing|completed|failed)$"),
    ] = None,
) -> AdminCrawlJobListResponse:
    items, total = await service.list_crawl_jobs(page=page, per_page=per_page, status=status)
    response.headers["X-Total-Count"] = str(total)
    return AdminCrawlJobListResponse(
        items=[AdminCrawlJobOut.from_job(item) for item in items],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/audit-logs", response_model=AdminAuditLogListResponse)
async def list_audit_logs(
    service: Annotated[AdminService, Depends(get_admin_service)],
    _: Annotated[None, Depends(admin_limiter)],
    response: Response,
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=MAX_ADMIN_PAGE_SIZE)] = 20,
    action: Annotated[
        str | None, Query(max_length=50, description="Filter by audit action")
    ] = None,
    tenant_id: Annotated[str | None, Query(description="Filter by affected tenant")] = None,
    user_id: Annotated[str | None, Query(description="Filter by acting user")] = None,
    since: Annotated[datetime | None, Query(description="Inclusive start (ISO)")] = None,
    until: Annotated[datetime | None, Query(description="Inclusive end (ISO)")] = None,
) -> AdminAuditLogListResponse:
    items, total = await service.list_audit_logs(
        page=page,
        per_page=per_page,
        action=action,
        tenant_id=tenant_id,
        user_id=user_id,
        since=since,
        until=until,
    )
    response.headers["X-Total-Count"] = str(total)
    return AdminAuditLogListResponse(
        items=[AdminAuditLogOut.from_log(item) for item in items],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/audit", response_model=AdminAdminAuditLogListResponse)
async def list_admin_audit_logs(
    service: Annotated[AdminService, Depends(get_admin_service)],
    _: Annotated[None, Depends(admin_limiter)],
    response: Response,
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=MAX_ADMIN_PAGE_SIZE)] = 20,
    action: Annotated[
        str | None, Query(max_length=50, description="Filter by admin action")
    ] = None,
    actor_user_id: Annotated[str | None, Query(description="Filter by acting super admin")] = None,
    tenant_id: Annotated[str | None, Query(description="Filter by affected tenant")] = None,
    since: Annotated[datetime | None, Query(description="Inclusive start (ISO)")] = None,
    until: Annotated[datetime | None, Query(description="Inclusive end (ISO)")] = None,
) -> AdminAdminAuditLogListResponse:
    """The dedicated platform admin trail (Phase 15)."""
    items, total = await service.list_admin_audit_logs(
        page=page,
        per_page=per_page,
        action=action,
        actor_user_id=actor_user_id,
        tenant_id=tenant_id,
        since=since,
        until=until,
    )
    response.headers["X-Total-Count"] = str(total)
    return AdminAdminAuditLogListResponse(
        items=[AdminAdminAuditLogOut.from_log(item) for item in items],
        total=total,
        page=page,
        per_page=per_page,
    )


__all__ = ["router"]
