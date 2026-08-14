"""Audit log document model (docs/05-Backend-Schema.md §13)."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from backend.core.security import new_id, utcnow

AuditAction = str
# Known actions used across the codebase.
AUDIT_REGISTER = "REGISTER"
AUDIT_LOGIN = "LOGIN"
AUDIT_LOGIN_FAILED = "LOGIN_FAILED"
AUDIT_EMAIL_VERIFIED = "EMAIL_VERIFIED"
AUDIT_VERIFICATION_RESENT = "VERIFICATION_RESENT"
AUDIT_TOKEN_REFRESHED = "TOKEN_REFRESHED"
AUDIT_REFRESH_REUSE_DETECTED = "REFRESH_REUSE_DETECTED"
AUDIT_LOGOUT = "LOGOUT"
AUDIT_FORGOT_PASSWORD = "FORGOT_PASSWORD"
AUDIT_PASSWORD_RESET = "PASSWORD_RESET"
AUDIT_WEBSITE_CREATED = "WEBSITE_CREATED"
AUDIT_WEBSITE_UPDATED = "WEBSITE_UPDATED"
AUDIT_WEBSITE_DELETED = "WEBSITE_DELETED"
# Phase 11.5 widget customization (dashboard widget builder).
AUDIT_WIDGET_UPDATED = "WIDGET_UPDATED"
# Phase 4 ingestion engine (docs/05 §8, ADR-002).
AUDIT_CRAWL_STARTED = "CRAWL_STARTED"
AUDIT_CRAWL_COMPLETED = "CRAWL_COMPLETED"
AUDIT_CRAWL_FAILED = "CRAWL_FAILED"
# Phase 5 knowledge processing (docs/06, ADR-008).
AUDIT_KNOWLEDGE_PROCESSED = "KNOWLEDGE_PROCESSED"
AUDIT_KNOWLEDGE_FAILED = "KNOWLEDGE_FAILED"
# Phase 11.2 conversation management.
AUDIT_CONVERSATION_DELETED = "CONVERSATION_DELETED"
# API key management (docs/05 §12).
AUDIT_API_KEY_CREATED = "API_KEY_CREATED"
AUDIT_API_KEY_REVOKED = "API_KEY_REVOKED"
# API key authentication (Sprint 2): every attempt is audited, success or not.
AUDIT_API_KEY_AUTHENTICATED = "API_KEY_AUTHENTICATED"
AUDIT_API_KEY_REJECTED = "API_KEY_REJECTED"
# Phase 12.5 admin panel (ADR-006 §Scope).
AUDIT_TENANT_SUSPENDED = "TENANT_SUSPENDED"
AUDIT_TENANT_ACTIVATED = "TENANT_ACTIVATED"
AUDIT_TENANT_PLAN_CHANGED = "TENANT_PLAN_CHANGED"
AUDIT_USER_SUSPENDED = "USER_SUSPENDED"
AUDIT_FORCE_LOGOUT = "FORCE_LOGOUT"


class AuditLog(BaseModel):
    """A security/activity event."""

    model_config = ConfigDict(extra="allow")

    id: str
    tenant_id: str | None
    user_id: str | None
    action: AuditAction
    ip_address: str | None
    user_agent: str | None
    created_at: datetime
    schema_version: int = 1

    @classmethod
    def new(
        cls,
        *,
        action: AuditAction,
        tenant_id: str | None = None,
        user_id: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> "AuditLog":
        return cls(
            id=new_id(),
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            ip_address=ip_address,
            user_agent=user_agent,
            created_at=utcnow(),
        )

    @classmethod
    def from_doc(cls, doc: dict[str, Any]) -> "AuditLog":
        doc = dict(doc)
        doc["id"] = str(doc.pop("_id"))
        return cls(**doc)

    def to_doc(self) -> dict[str, Any]:
        doc = self.model_dump(exclude={"id"})
        doc["_id"] = self.id
        return doc
