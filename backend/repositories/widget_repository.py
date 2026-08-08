"""Widget data access (Protocol + MongoDB implementation)."""

from typing import Any, Protocol

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.models.widget import Widget


class WidgetRepository(Protocol):
    """Data access for the `widgets` collection (tenant-scoped)."""

    async def create(self, widget: Widget) -> None: ...

    async def find_by_website_id(self, tenant_id: str, website_id: str) -> Widget | None: ...

    async def list_by_website_ids(self, tenant_id: str, website_ids: list[str]) -> list[Widget]: ...

    async def delete_by_website_id(self, tenant_id: str, website_id: str) -> None: ...


class MongoWidgetRepository:
    """MongoDB-backed widget repository. All queries are tenant-scoped."""

    def __init__(self, db: AsyncIOMotorDatabase[Any]) -> None:
        self._collection = db["widgets"]

    async def create(self, widget: Widget) -> None:
        await self._collection.insert_one(widget.to_doc())

    async def find_by_website_id(self, tenant_id: str, website_id: str) -> Widget | None:
        doc = await self._collection.find_one(
            {"tenant_id": tenant_id, "website_id": website_id}
        )
        return Widget.from_doc(doc) if doc else None

    async def list_by_website_ids(self, tenant_id: str, website_ids: list[str]) -> list[Widget]:
        if not website_ids:
            return []
        cursor = self._collection.find(
            {"tenant_id": tenant_id, "website_id": {"$in": website_ids}}
        )
        return [Widget.from_doc(doc) async for doc in cursor]

    async def delete_by_website_id(self, tenant_id: str, website_id: str) -> None:
        await self._collection.delete_many(
            {"tenant_id": tenant_id, "website_id": website_id}
        )
