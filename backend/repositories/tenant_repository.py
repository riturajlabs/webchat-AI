"""Tenant data access (Protocol + MongoDB implementation)."""

from typing import Any, Protocol

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.models.tenant import Tenant


class TenantRepository(Protocol):
    """Data access for the `tenants` collection."""

    async def create(self, tenant: Tenant) -> None: ...

    async def find_by_id(self, tenant_id: str) -> Tenant | None: ...


class MongoTenantRepository:
    """MongoDB-backed tenant repository."""

    def __init__(self, db: AsyncIOMotorDatabase[Any]) -> None:
        self._collection = db["tenants"]

    async def create(self, tenant: Tenant) -> None:
        await self._collection.insert_one(tenant.to_doc())

    async def find_by_id(self, tenant_id: str) -> Tenant | None:
        doc = await self._collection.find_one({"_id": tenant_id})
        return Tenant.from_doc(doc) if doc else None
