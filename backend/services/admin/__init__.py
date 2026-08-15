"""Admin service (Phase 12.5, ADR-006; extended for Phase 15 SaaS ops)."""

from backend.services.admin.admin_service import (
    AdminService,
    RevenuePeriod,
    RevenueReport,
    TenantDetail,
)

__all__ = ["AdminService", "RevenuePeriod", "RevenueReport", "TenantDetail"]
