"""Tenant document model (docs/05-Backend-Schema.md §4)."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from backend.core.security import new_id, utcnow


class Tenant(BaseModel):
    """An organization owning isolated resources."""

    model_config = ConfigDict(extra="allow")

    id: str
    company_name: str
    plan: str = "free"
    status: str = "active"
    created_at: datetime
    updated_at: datetime
    schema_version: int = 1

    @classmethod
    def new(cls, *, company_name: str) -> "Tenant":
        now = utcnow()
        return cls(
            id=new_id(),
            company_name=company_name,
            created_at=now,
            updated_at=now,
        )

    @classmethod
    def from_doc(cls, doc: dict[str, Any]) -> "Tenant":
        doc = dict(doc)
        doc["id"] = str(doc.pop("_id"))
        return cls(**doc)

    def to_doc(self) -> dict[str, Any]:
        doc = self.model_dump(exclude={"id"})
        doc["_id"] = self.id
        return doc
