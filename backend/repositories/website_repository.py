"""Website data access (Protocol + MongoDB implementation)."""

from typing import Any, Literal, Protocol

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError

from backend.core.errors import DuplicateWebsiteError
from backend.core.security import utcnow
from backend.models.website import WEBSITE_STATUS_DELETED, Website

WebsiteSortField = Literal["created_at", "name"]
WebsiteSortOrder = Literal["asc", "desc"]


class WebsiteRepository(Protocol):
    """Data access for the `websites` collection (tenant-scoped)."""

    async def create(self, website: Website) -> None: ...

    async def find_by_id(self, tenant_id: str, website_id: str) -> Website | None: ...

    async def find_by_url(self, tenant_id: str, url: str) -> Website | None: ...

    # Worker-side lookup: `process_website_documents(website_id)` runs with only
    # the id; the record itself carries the tenant, which scopes all writes.
    async def find_by_id_any(self, website_id: str) -> Website | None: ...

    async def list_by_tenant(
        self,
        tenant_id: str,
        *,
        status: str | None = None,
        sort: WebsiteSortField = "created_at",
        order: WebsiteSortOrder = "desc",
        limit: int = 50,
        offset: int = 0,
    ) -> list[Website]: ...

    async def count_by_tenant(self, tenant_id: str, *, status: str | None = None) -> int: ...

    async def update(self, website: Website) -> None: ...

    async def delete(self, tenant_id: str, website_id: str) -> None: ...


class MongoWebsiteRepository:
    """MongoDB-backed website repository.

    Every query is scoped by `tenant_id` (00-AI-Development-Rules §7): a
    foreign tenant can never read or mutate another tenant's websites.
    Delete is a soft delete (`status = "deleted"`) - the document is preserved
    but excluded from all tenant-facing reads.
    """

    def __init__(self, db: AsyncIOMotorDatabase[Any]) -> None:
        self._collection = db["websites"]

    async def create(self, website: Website) -> None:
        try:
            await self._collection.insert_one(website.to_doc())
        except DuplicateKeyError as exc:
            # The unique (tenant_id, url) index is the race-free gatekeeper for
            # duplicate registrations (docs/05 §5, ADR-005).
            raise DuplicateWebsiteError("A website with this URL already exists.") from exc

    async def find_by_id(self, tenant_id: str, website_id: str) -> Website | None:
        doc = await self._collection.find_one(
            {
                "_id": website_id,
                "tenant_id": tenant_id,
                "status": {"$ne": WEBSITE_STATUS_DELETED},
            }
        )
        return Website.from_doc(doc) if doc else None

    async def find_by_url(self, tenant_id: str, url: str) -> Website | None:
        # Includes soft-deleted documents: the record persists, so the URL is
        # still considered registered (consistent with the unique index).
        doc = await self._collection.find_one({"tenant_id": tenant_id, "url": url})
        return Website.from_doc(doc) if doc else None

    async def find_by_id_any(self, website_id: str) -> Website | None:
        doc = await self._collection.find_one({"_id": website_id})
        return Website.from_doc(doc) if doc else None

    async def list_by_tenant(
        self,
        tenant_id: str,
        *,
        status: str | None = None,
        sort: WebsiteSortField = "created_at",
        order: WebsiteSortOrder = "desc",
        limit: int = 50,
        offset: int = 0,
    ) -> list[Website]:
        query: dict[str, Any] = {
            "tenant_id": tenant_id,
            "status": {"$ne": WEBSITE_STATUS_DELETED},
        }
        if status is not None:
            query["status"] = status
        direction = ASCENDING if order == "asc" else DESCENDING
        cursor = (
            self._collection.find(query)
            .sort(sort, direction)
            .skip(offset)
            .limit(limit)
        )
        return [Website.from_doc(doc) async for doc in cursor]

    async def count_by_tenant(self, tenant_id: str, *, status: str | None = None) -> int:
        query: dict[str, Any] = {
            "tenant_id": tenant_id,
            "status": {"$ne": WEBSITE_STATUS_DELETED},
        }
        if status is not None:
            query["status"] = status
        return await self._collection.count_documents(query)

    async def update(self, website: Website) -> None:
        await self._collection.replace_one(
            {"_id": website.id, "tenant_id": website.tenant_id}, website.to_doc()
        )

    async def delete(self, tenant_id: str, website_id: str) -> None:
        website = await self._collection.find_one({"_id": website_id, "tenant_id": tenant_id})
        if website is None:
            return
        website = Website.from_doc(website)
        website.status = WEBSITE_STATUS_DELETED
        website.updated_at = utcnow()
        await self._collection.replace_one(
            {"_id": website.id, "tenant_id": website.tenant_id}, website.to_doc()
        )
