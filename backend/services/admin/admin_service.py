"""Platform administration service (Phase 12.5, ADR-006).

All business logic for the super-admin surface: tenant/user management,
platform KPIs, the global crawl queue and the audit-log viewer. The routes
guard every call with `role=admin`; this service additionally hard-guards
self-targeting (an admin cannot suspend their own workspace/account) and
reuses the existing audit system for every mutation. No new collections.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from backend.core.errors import (
    ForbiddenError,
    TenantNotFoundError,
    UserNotFoundError,
)
from backend.core.security import utcnow
from backend.models.audit_log import (
    AUDIT_FORCE_LOGOUT,
    AUDIT_TENANT_ACTIVATED,
    AUDIT_TENANT_PLAN_CHANGED,
    AUDIT_TENANT_SUSPENDED,
    AUDIT_USER_SUSPENDED,
    AuditLog,
)
from backend.models.crawl_job import CrawlJob
from backend.models.tenant import Tenant
from backend.models.user import User
from backend.repositories import (
    AdminRepository,
    AuditLogRepository,
    CrawlJobRepository,
    RefreshTokenRepository,
    TenantRepository,
    TenantUsageSummary,
    UsageRecordRepository,
    UserRepository,
    WebsiteRepository,
)


@dataclass(frozen=True)
class TenantDetail:
    """Tenant plus the ADR-006 detail aggregates (websites, usage, status)."""

    tenant: Tenant
    website_count: int
    user_count: int
    active_crawl_jobs: int
    usage: TenantUsageSummary


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
    ) -> None:
        self._tenants = tenants
        self._users = users
        self._websites = websites
        self._usage = usage
        self._crawl_jobs = crawl_jobs
        self._audit = audit
        self._refresh_tokens = refresh_tokens
        self._stats = stats

    # ----------------------------------------------------------- tenant reads

    async def list_tenants(
        self,
        *,
        page: int,
        per_page: int,
        search: str | None,
    ) -> tuple[list[Tenant], int]:
        total = await self._tenants.count_tenants(search=search)
        items = await self._tenants.list_tenants(
            search=search,
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
        if tenant_id == admin_tenant_id:
            raise ForbiddenError("Cannot change your own workspace.")
        tenant = await self._tenants.find_by_id(tenant_id)
        if tenant is None:
            raise TenantNotFoundError("Tenant not found.")

        if status is not None and status != tenant.status:
            tenant.status = status
            tenant.updated_at = utcnow()
            await self._audit.create(
                AuditLog.new(
                    action=(
                        AUDIT_TENANT_SUSPENDED if status == "suspended" else AUDIT_TENANT_ACTIVATED
                    ),
                    tenant_id=tenant_id,
                    user_id=admin_user_id,
                    ip_address=ip_address,
                    user_agent=user_agent,
                )
            )
        if plan is not None and plan != tenant.plan:
            tenant.plan = plan
            tenant.updated_at = utcnow()
            await self._audit.create(
                AuditLog.new(
                    action=AUDIT_TENANT_PLAN_CHANGED,
                    tenant_id=tenant_id,
                    user_id=admin_user_id,
                    ip_address=ip_address,
                    user_agent=user_agent,
                )
            )

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
            await self._users.set_status(user.id, "suspended", utcnow())
            user.status = "suspended"
            user.updated_at = utcnow()
            await self._audit.create(
                AuditLog.new(
                    action=AUDIT_USER_SUSPENDED,
                    tenant_id=tenant_id,
                    user_id=admin_user_id,
                    ip_address=ip_address,
                    user_agent=user_agent,
                )
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
        await self._audit.create(
            AuditLog.new(
                action=AUDIT_FORCE_LOGOUT,
                tenant_id=tenant_id,
                user_id=admin_user_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )
        return user

    # --------------------------------------------------- platform reads

    async def platform_stats(self) -> Any:
        """Platform KPIs for the admin overview (ADR-006 §Platform Analytics)."""
        return await self._stats.platform_stats()

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

    # ------------------------------------------------------------ internals

    async def _require_user_in_tenant(self, tenant_id: str, user_id: str) -> User:
        tenant = await self._tenants.find_by_id(tenant_id)
        if tenant is None:
            raise TenantNotFoundError("Tenant not found.")
        user = await self._users.find_by_id(user_id)
        if user is None or user.tenant_id != tenant_id:
            raise UserNotFoundError("User not found in this tenant.")
        return user


__all__ = ["AdminService", "TenantDetail"]
