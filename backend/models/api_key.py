"""API key document model (docs/05-Backend-Schema.md §12 + ADR-004)."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from backend.core.security import API_KEY_PREFIX, new_id, utcnow

# Key lifecycle states (docs/05 §12). "revoked" mirrors the soft-delete rule
# (00-AI-Development-Rules: never destroy data): the record is kept for audit
# but hidden from every tenant-facing query.
API_KEY_STATUS_ACTIVE = "active"
API_KEY_STATUS_REVOKED = "revoked"

API_KEY_STATUSES = {API_KEY_STATUS_ACTIVE, API_KEY_STATUS_REVOKED}


class ApiKey(BaseModel):
    """A tenant-scoped credential for programmatic API access.

    Only `hashed_secret` (SHA-256) is persisted - the raw secret is returned
    to the tenant exactly once at creation and never stored (ADR-004).
    """

    model_config = ConfigDict(extra="allow")

    id: str
    tenant_id: str
    name: str
    key_prefix: str = API_KEY_PREFIX
    hashed_secret: str
    status: str = API_KEY_STATUS_ACTIVE
    # Optional expiry (UTC). When set, the key stops authenticating after this
    # moment even if its status is still `active` (Sprint 2).
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    schema_version: int = 1

    @classmethod
    def new(
        cls,
        *,
        tenant_id: str,
        name: str,
        hashed_secret: str,
        expires_at: datetime | None = None,
    ) -> "ApiKey":
        now = utcnow()
        return cls(
            id=new_id(),
            tenant_id=tenant_id,
            name=name,
            hashed_secret=hashed_secret,
            expires_at=expires_at,
            created_at=now,
            updated_at=now,
        )

    @classmethod
    def from_doc(cls, doc: dict[str, Any]) -> "ApiKey":
        doc = dict(doc)
        doc["id"] = str(doc.pop("_id"))
        return cls(**doc)

    def to_doc(self) -> dict[str, Any]:
        doc = self.model_dump(exclude={"id"})
        doc["_id"] = self.id
        return doc


__all__ = [
    "API_KEY_STATUS_ACTIVE",
    "API_KEY_STATUS_REVOKED",
    "API_KEY_STATUSES",
    "ApiKey",
]
