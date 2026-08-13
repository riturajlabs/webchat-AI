"""Platform administration endpoints (Phase 12.5, ADR-006).

    GET    /api/admin/tenants                        list/search tenants (paginated)
    GET    /api/admin/tenants/{tenant_id}            tenant detail (websites, usage, status)
    PATCH  /api/admin/tenants/{tenant_id}            suspend/activate / plan change
    GET    /api/admin/users                          list/search users (paginated)
    POST   /api/admin/tenants/{tenant_id}/users/{user_id}/suspend        suspend a user
    POST   /api/admin/tenants/{tenant_id}/users/{user_id}/force-logout    revoke sessions
    GET    /api/admin/stats                          platform KPIs
    GET    /api/admin/crawl-jobs                     global crawl queue monitor
    GET    /api/admin/audit-logs                     audit log viewer (filters + pagination)

Every route requires a bearer access token with tenant role `admin`; owner
users (and below) receive the existing 403 `FORBIDDEN` error. All mutations
write audit logs through the shared audit system and are rate-limited with the
dedicated admin budget (ADR-006 §Admin UI).
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response

from backend.api.deps import (
    admin_limiter,
    client_ip,
    current_user,
    get_admin_service,
    require_role,
)
from backend.schemas.admin import (
    MAX_ADMIN_PAGE_SIZE,
    MAX_ADMIN_SEARCH_LENGTH,
    AdminAuditLogListResponse,
    AdminAuditLogOut,
    AdminCrawlJobListResponse,
    AdminCrawlJobOut,
    AdminCrawlStats,
    AdminStatsOut,
    AdminTenantCounts,
    AdminTenantDetailOut,
    AdminTenantListResponse,
    AdminTenantOut,
    AdminTenantUpdateRequest,
    AdminTenantUsageOut,
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
    dependencies=[Depends(require_role("admin"))],
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
) -> AdminTenantListResponse:
    items, total = await service.list_tenants(page=page, per_page=per_page, search=search)
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
    stats = await service.platform_stats()
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


__all__ = ["router"]
