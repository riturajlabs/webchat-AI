"""Document model: a cleaned, checksummed page stored for the knowledge base.

`documents` is the Phase 4 output and the Phase 5 input: one row per crawled
URL holding the extracted text plus a SHA-256 `checksum` so Phase 5 can detect
content changes and only re-embed what actually changed.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from backend.core.security import new_id, utcnow

DOCUMENT_STATUS_READY = "ready"

DOCUMENT_STATUSES = {DOCUMENT_STATUS_READY}


class Document(BaseModel):
    """Cleaned page content for one crawled URL of a tenant's website."""

    model_config = ConfigDict(extra="allow")

    id: str
    tenant_id: str
    website_id: str
    url: str
    title: str
    content: str
    checksum: str
    language: str = ""
    status: str = DOCUMENT_STATUS_READY
    created_at: datetime
    updated_at: datetime
    schema_version: int = 1

    @classmethod
    def new(
        cls,
        *,
        tenant_id: str,
        website_id: str,
        url: str,
        title: str,
        content: str,
        checksum: str,
        language: str = "",
    ) -> "Document":
        now = utcnow()
        return cls(
            id=new_id(),
            tenant_id=tenant_id,
            website_id=website_id,
            url=url,
            title=title,
            content=content,
            checksum=checksum,
            language=language,
            created_at=now,
            updated_at=now,
        )

    @classmethod
    def from_doc(cls, doc: dict[str, Any]) -> "Document":
        doc = dict(doc)
        doc["id"] = str(doc.pop("_id"))
        return cls(**doc)

    def to_doc(self) -> dict[str, Any]:
        doc = self.model_dump(exclude={"id"})
        doc["_id"] = self.id
        return doc
