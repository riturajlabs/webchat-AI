"""Tenant data access (Protocol + MongoDB implementation).

Phase 12.5 adds the platform-wide `list_tenants`/`count_tenants`/`update`
read-write surface consumed only by the admin service (ADR-006). The list
query is intentionally not tenant-scoped: tenants have no parent tenant, and
the admin router guards these methods behind `role=admin`.
"""

from typing import Any, Protocol

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import DESCENDING

from backend.models.tenant import Tenant


class TenantRepository(Protocol):
    """Data access for the `tenants` collection."""

    async def create(self, tenant: Tenant) -> None: ...

    async def find_by_id(self, tenant_id: str) -> Tenant | None: ...

    # Phase 12.5 admin surface (ADR-006).
    async def list_tenants(
        self,
        *,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Tenant]: ...

    async def count_tenants(self, *, search: str | None = None) -> int: ...

    async def update(self, tenant: Tenant) -> None: ...


class MongoTenantRepository:
    """MongoDB-backed tenant repository."""

    def __init__(self, db: AsyncIOMotorDatabase[Any]) -> None:
        self._collection = db["tenants"]

    async def create(self, tenant: Tenant) -> None:
        await self._collection.insert_one(tenant.to_doc())

    async def find_by_id(self, tenant_id: str) -> Tenant | None:
        doc = await self._collection.find_one({"_id": tenant_id})
        return Tenant.from_doc(doc) if doc else None

    async def list_tenants(
        self,
        *,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Tenant]:
        query = self._query(search=search)
        cursor = (
            self._collection.find(query).sort("created_at", DESCENDING).skip(offset).limit(limit)
        )
        return [Tenant.from_doc(doc) async for doc in cursor]

    async def count_tenants(self, *, search: str | None = None) -> int:
        return await self._collection.count_documents(self._query(search=search))

    async def update(self, tenant: Tenant) -> None:
        await self._collection.replace_one({"_id": tenant.id}, tenant.to_doc())

    @staticmethod
    def _query(*, search: str | None) -> dict[str, Any]:
        if not search:
            return {}
        return {"company_name": {"$regex": search, "$options": "i"}}
