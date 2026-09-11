"""Admin service (Phase 12.5, ADR-006; extended for Phase 15 SaaS ops and
Phase 16 manual Pro grants)."""

from backend.services.admin.admin_service import (
    ENTITLEMENT_SOURCE_ADMIN_GRANT,
    ENTITLEMENT_SOURCE_SUBSCRIPTION,
    ENTITLEMENT_SOURCE_TENANT_PLAN,
    GRANTABLE_PLANS,
    AdminService,
    Entitlement,
    GrantResult,
    RevenuePeriod,
    RevenueReport,
    TenantDetail,
)

__all__ = [
    "ENTITLEMENT_SOURCE_ADMIN_GRANT",
    "ENTITLEMENT_SOURCE_SUBSCRIPTION",
    "ENTITLEMENT_SOURCE_TENANT_PLAN",
    "AdminService",
    "Entitlement",
    "GRANTABLE_PLANS",
    "GrantResult",
    "RevenuePeriod",
    "RevenueReport",
    "TenantDetail",
]
