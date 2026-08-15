"""Document data access (Protocol + MongoDB implementation).

`documents` stores one cleaned page per crawled URL. The unique
(tenant_id, website_id, url) index makes upserts idempotent: a re-crawl of the
same URL replaces the old content instead of duplicating it (incremental crawl).
"""

from typing import Any, Protocol

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError

from backend.models.document import Document
from backend.models.knowledge_chunk import (
    KNOWLEDGE_STATUS_FAILED,
    KNOWLEDGE_STATUS_NONE,
    KNOWLEDGE_STATUS_PENDING,
    KNOWLEDGE_STATUS_PROCESSING,
)


class DocumentRepository(Protocol):
    """Data access for the `documents` collection (tenant-scoped)."""

    async def upsert(self, document: Document) -> None: ...

    async def count_by_website(self, tenant_id: str, website_id: str) -> int: ...

    async def count_failed_by_website(self, tenant_id: str, website_id: str) -> int: ...

    async def count_non_terminal_by_website(self, tenant_id: str, website_id: str) -> int: ...

    async def all_checksums(self, tenant_id: str, website_id: str) -> list[str]: ...

    async def find_by_id(self, tenant_id: str, document_id: str) -> Document | None: ...

    # Worker-side lookups: the document carries its tenant, so reads resolve
    # ownership from stored data (never from untrusted input).
    async def find_by_id_any(self, document_id: str) -> Document | None: ...

    async def list_by_website(self, tenant_id: str, website_id: str) -> list[Document]: ...


class MongoDocumentRepository:
    """MongoDB-backed document repository (docs/05, Phase 4 ingestion)."""

    def __init__(self, db: AsyncIOMotorDatabase[Any]) -> None:
        self._collection = db["documents"]

    async def upsert(self, document: Document) -> None:
        query = {
            "tenant_id": document.tenant_id,
            "website_id": document.website_id,
            "url": document.url,
        }
        # `$set` never touches `_id` (Mongo forbids mutating it), while the
        # insert path keeps our application-generated `_id`.
        result = await self._collection.update_one(
            query, {"$set": update_payload(document)}, upsert=False
        )
        if result.matched_count > 0:
            return
        try:
            await self._collection.insert_one(document.to_doc())
        except DuplicateKeyError:
            # Concurrent insert raced on the unique (tenant, website, url)
            # index; the document already exists, so apply a plain update.
            await self._collection.update_one(
                query, {"$set": update_payload(document)}, upsert=False
            )

    async def count_by_website(self, tenant_id: str, website_id: str) -> int:
        return await self._collection.count_documents(
            {"tenant_id": tenant_id, "website_id": website_id}
        )

    async def count_failed_by_website(self, tenant_id: str, website_id: str) -> int:
        return await self._collection.count_documents(
            {
                "tenant_id": tenant_id,
                "website_id": website_id,
                "knowledge_status": KNOWLEDGE_STATUS_FAILED,
            }
        )

    async def count_non_terminal_by_website(self, tenant_id: str, website_id: str) -> int:
        """Documents not yet in a terminal knowledge state (pending/processing)."""
        return await self._collection.count_documents(
            {
                "tenant_id": tenant_id,
                "website_id": website_id,
                "knowledge_status": {
                    "$in": [
                        KNOWLEDGE_STATUS_NONE,
                        KNOWLEDGE_STATUS_PENDING,
                        KNOWLEDGE_STATUS_PROCESSING,
                    ],
                },
            }
        )

    async def all_checksums(self, tenant_id: str, website_id: str) -> list[str]:
        cursor = self._collection.find(
            {"tenant_id": tenant_id, "website_id": website_id},
            projection={"checksum": 1, "_id": 0},
        )
        return [str(doc["checksum"]) async for doc in cursor]

    async def find_by_id(self, tenant_id: str, document_id: str) -> Document | None:
        doc = await self._collection.find_one({"_id": document_id, "tenant_id": tenant_id})
        return Document.from_doc(doc) if doc is not None else None

    async def find_by_id_any(self, document_id: str) -> Document | None:
        doc = await self._collection.find_one({"_id": document_id})
        return Document.from_doc(doc) if doc is not None else None

    async def list_by_website(self, tenant_id: str, website_id: str) -> list[Document]:
        cursor = self._collection.find({"tenant_id": tenant_id, "website_id": website_id})
        return [Document.from_doc(doc) async for doc in cursor]


def update_payload(document: Document) -> dict[str, Any]:
    """`$set` payload for a document update (never mutates the `_id` field).

    MongoDB rejects any update that rewrites `_id`, so the application-generated
    id is stripped here while `Document.to_doc()` keeps it for inserts.
    """
    payload = document.to_doc()
    payload.pop("_id", None)
    return payload
