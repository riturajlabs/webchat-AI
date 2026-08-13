"""Pydantic v2 schemas for the admin API (Phase 12.5, ADR-006).

Every response type mirrors an existing model; the admin surface only adds
platform-wide fields (`tenant_id` on crawl jobs, counts on tenant detail).
Pagination bounds are shared with the feedback/conversation list APIs.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

MAX_ADMIN_PAGE_SIZE = 100
MAX_ADMIN_SEARCH_LENGTH = 100

TenantStatus = Literal["active", "suspended"]


class AdminTenantOut(BaseModel):
    """A tenant row in the admin tenant list."""

    id: str
    company_name: str
    plan: str
    status: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_tenant(cls, tenant: Any) -> "AdminTenantOut":
        return cls(
            id=tenant.id,
            company_name=tenant.company_name,
            plan=tenant.plan,
            status=tenant.status,
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
    """Tenant detail with the ADR-006 aggregates (websites, usage, status)."""

    website_count: int
    user_count: int
    active_crawl_jobs: int
    usage: AdminTenantUsageOut


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
    """A platform user row in the admin user list."""

    id: str
    name: str
    email: str
    role: str
    status: str
    email_verified: bool
    tenant_id: str
    last_login: datetime | None
    created_at: datetime

    @classmethod
    def from_user(cls, user: Any) -> "AdminUserOut":
        return cls(
            id=user.id,
            name=user.name,
            email=user.email,
            role=user.role,
            status=user.status,
            email_verified=user.email_verified,
            tenant_id=user.tenant_id,
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
            created_at=log.created_at,
        )


class AdminAuditLogListResponse(BaseModel):
    items: list[AdminAuditLogOut]
    total: int
    page: int
    per_page: int


__all__ = [
    "AdminAuditLogListResponse",
    "AdminAuditLogOut",
    "AdminCrawlJobListResponse",
    "AdminCrawlJobOut",
    "AdminCrawlStats",
    "AdminStatsOut",
    "AdminTenantCounts",
    "AdminTenantDetailOut",
    "AdminTenantListResponse",
    "AdminTenantOut",
    "AdminTenantUpdateRequest",
    "AdminTenantUsageOut",
    "AdminUsageTotals",
    "AdminUserCounts",
    "AdminUserListResponse",
    "AdminUserOut",
    "MAX_ADMIN_PAGE_SIZE",
    "MAX_ADMIN_SEARCH_LENGTH",
]
