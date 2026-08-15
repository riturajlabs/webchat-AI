"""Admin audit log document model (Phase 15, SaaS admin operations).

A dedicated `admin_audit_logs` collection for platform operator actions so
SaaS operations keep their own tamper-evident trail (ADR-006 §Security:
"a dedicated audit trail for admin actions"). Tenant-scoped events (login,
websites, crawls, ...) continue to use the shared `audit_logs` collection;
only *platform* mutations by a super admin land here:

    TENANT_SUSPENDED          tenant suspended by a platform operator
    TENANT_ACTIVATED          tenant re-activated by a platform operator
    TENANT_PLAN_CHANGED       tenant plan overridden by a platform operator
    USER_SUSPENDED            user suspended by a platform operator
    USER_ACTIVATED            user re-activated by a platform operator
    FORCE_LOGOUT              all refresh tokens revoked for a user

The collection mirrors `audit_logs` (same shape) but is written exclusively
by `AdminService` and read by `GET /api/admin/audit`. It is retained for the
platform compliance window (10 years) rather than the 1-year tenant audit TTL.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from backend.core.security import new_id, utcnow

AdminAuditAction = str
ADMIN_AUDIT_TENANT_SUSPENDED = "TENANT_SUSPENDED"
ADMIN_AUDIT_TENANT_ACTIVATED = "TENANT_ACTIVATED"
ADMIN_AUDIT_TENANT_PLAN_CHANGED = "TENANT_PLAN_CHANGED"
ADMIN_AUDIT_USER_SUSPENDED = "USER_SUSPENDED"
ADMIN_AUDIT_USER_ACTIVATED = "USER_ACTIVATED"
ADMIN_AUDIT_FORCE_LOGOUT = "FORCE_LOGOUT"

ADMIN_AUDIT_LOG_SCHEMA_VERSION = 1
# Platform compliance retention (docs/05 §13): 10 years.
ADMIN_AUDIT_LOG_RETENTION_SECONDS = 10 * 365 * 24 * 60 * 60


class AdminAuditLog(BaseModel):
    """A platform operator action (dedicated admin trail)."""

    model_config = ConfigDict(extra="allow")

    id: str
    actor_user_id: str | None = None
    action: AdminAuditAction
    tenant_id: str | None = None
    user_id: str | None = None
    plan_id: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    created_at: datetime
    schema_version: int = ADMIN_AUDIT_LOG_SCHEMA_VERSION

    @classmethod
    def new(
        cls,
        *,
        action: AdminAuditAction,
        actor_user_id: str | None = None,
        tenant_id: str | None = None,
        user_id: str | None = None,
        plan_id: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> "AdminAuditLog":
        return cls(
            id=new_id(),
            actor_user_id=actor_user_id,
            action=action,
            tenant_id=tenant_id,
            user_id=user_id,
            plan_id=plan_id,
            ip_address=ip_address,
            user_agent=user_agent,
            created_at=utcnow(),
        )

    @classmethod
    def from_doc(cls, doc: dict[str, Any]) -> "AdminAuditLog":
        doc = dict(doc)
        doc["id"] = str(doc.pop("_id"))
        return cls(**doc)

    def to_doc(self) -> dict[str, Any]:
        doc = self.model_dump(exclude={"id"})
        doc["_id"] = self.id
        return doc


__all__ = [
    "ADMIN_AUDIT_FORCE_LOGOUT",
    "ADMIN_AUDIT_LOG_RETENTION_SECONDS",
    "ADMIN_AUDIT_LOG_SCHEMA_VERSION",
    "ADMIN_AUDIT_TENANT_ACTIVATED",
    "ADMIN_AUDIT_TENANT_PLAN_CHANGED",
    "ADMIN_AUDIT_TENANT_SUSPENDED",
    "ADMIN_AUDIT_USER_ACTIVATED",
    "ADMIN_AUDIT_USER_SUSPENDED",
    "AdminAuditAction",
    "AdminAuditLog",
]
