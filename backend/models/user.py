"""User document model (docs/05-Backend-Schema.md §3 + ADR-005 §5.2)."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from backend.core.security import new_id, utcnow


class User(BaseModel):
    """A dashboard account. Belongs to exactly one tenant."""

    model_config = ConfigDict(extra="allow")

    id: str
    tenant_id: str
    name: str
    email: str
    password_hash: str
    role: str = "owner"
    status: str = "active"
    email_verified: bool = False
    onboarding_completed: bool = False
    onboarding_step: str = "welcome"
    pwd_token_version: int = 0
    last_login: datetime | None = None
    failed_login_attempts: int = 0
    locked_until: datetime | None = None
    created_at: datetime
    updated_at: datetime
    schema_version: int = 1

    @classmethod
    def new(
        cls,
        *,
        tenant_id: str,
        name: str,
        email: str,
        password_hash: str,
    ) -> "User":
        now = utcnow()
        return cls(
            id=new_id(),
            tenant_id=tenant_id,
            name=name,
            email=email,
            password_hash=password_hash,
            created_at=now,
            updated_at=now,
        )

    @classmethod
    def from_doc(cls, doc: dict[str, Any]) -> "User":
        doc = dict(doc)
        doc["id"] = str(doc.pop("_id"))
        return cls(**doc)

    def to_doc(self) -> dict[str, Any]:
        doc = self.model_dump(exclude={"id"})
        doc["_id"] = self.id
        return doc
