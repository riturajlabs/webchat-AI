"""Refresh token document model (ADR-005 §5.4).

Only the SHA-256 hash of the opaque token is stored; the raw value lives solely
in the httpOnly cookie presented by the client.
"""

from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict

from backend.core.config import get_settings
from backend.core.security import new_id, utcnow


class RefreshToken(BaseModel):
    """A stateful, rotating refresh token."""

    model_config = ConfigDict(extra="allow")

    id: str
    tenant_id: str
    user_id: str
    token_hash: str
    expires_at: datetime
    created_at: datetime
    last_rotated_at: datetime | None = None
    revoked_at: datetime | None = None
    replaced_by: str | None = None
    schema_version: int = 1

    @classmethod
    def new(cls, *, tenant_id: str, user_id: str, token_hash: str) -> "RefreshToken":
        now = utcnow()
        ttl = get_settings().jwt_refresh_token_expire_days
        return cls(
            id=new_id(),
            tenant_id=tenant_id,
            user_id=user_id,
            token_hash=token_hash,
            expires_at=now + timedelta(days=ttl),
            created_at=now,
            last_rotated_at=now,
        )

    @classmethod
    def from_doc(cls, doc: dict[str, Any]) -> "RefreshToken":
        doc = dict(doc)
        doc["id"] = str(doc.pop("_id"))
        return cls(**doc)

    def to_doc(self) -> dict[str, Any]:
        doc = self.model_dump(exclude={"id"})
        doc["_id"] = self.id
        return doc

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    @property
    def is_expired(self) -> bool:
        return self.expires_at <= utcnow()
