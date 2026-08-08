"""Membership document model linking a user to a tenant with a role."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from backend.core.security import new_id, utcnow

MemberRole = str  # "owner" | "admin" | "editor" | "viewer"


class Member(BaseModel):
    """A user's membership in a tenant, carrying the RBAC role."""

    model_config = ConfigDict(extra="allow")

    id: str
    tenant_id: str
    user_id: str
    role: MemberRole = "owner"
    status: str = "active"
    created_at: datetime
    updated_at: datetime
    schema_version: int = 1

    @classmethod
    def new(cls, *, tenant_id: str, user_id: str, role: MemberRole) -> "Member":
        now = utcnow()
        return cls(
            id=new_id(),
            tenant_id=tenant_id,
            user_id=user_id,
            role=role,
            created_at=now,
            updated_at=now,
        )

    @classmethod
    def from_doc(cls, doc: dict[str, Any]) -> "Member":
        doc = dict(doc)
        doc["id"] = str(doc.pop("_id"))
        return cls(**doc)

    def to_doc(self) -> dict[str, Any]:
        doc = self.model_dump(exclude={"id"})
        doc["_id"] = self.id
        return doc
