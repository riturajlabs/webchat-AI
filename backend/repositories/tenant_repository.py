"""Tenant data access (Protocol + MongoDB implementation).

Phase 12.5 adds the platform-wide `list_tenants`/`count_tenants`/`update`
read-write surface consumed only by the admin service (ADR-006). The list
query is intentionally not tenant-scoped: tenants have no parent tenant, and
the admin router guards these methods behind `role=admin`.
"""

import re
from typing import Any, Protocol

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import DESCENDING

from backend.models.tenant import Tenant

# SEC-H05: bounded length for the admin search term so an unbounded string can
# never be turned into a `$regex` against the tenants collection. The admin
# route already applies `max_length=100`; this is defense-in-depth for any
# other caller of the data-access layer.
MAX_TENANT_SEARCH_LENGTH = 100


class TenantRepository(Protocol):
    """Data access for the `tenants` collection."""

    async def create(self, tenant: Tenant) -> None: ...

    async def find_by_id(self, tenant_id: str) -> Tenant | None: ...

    # Phase 16: batch lookup for the admin user list's entitlement resolution
    # (bounded by the admin page size).
    async def find_many(self, tenant_ids: list[str]) -> list[Tenant]: ...

    # Phase 12.5 admin surface (ADR-006). Phase 15 adds `plan`/`status`
    # filters so the SaaS operations panel can segment the tenant base.
    async def list_tenants(
        self,
        *,
        search: str | None = None,
        plan: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Tenant]: ...

    async def count_tenants(
        self,
        *,
        search: str | None = None,
        plan: str | None = None,
        status: str | None = None,
    ) -> int: ...

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

    async def find_many(self, tenant_ids: list[str]) -> list[Tenant]:
        if not tenant_ids:
            return []
        cursor = self._collection.find({"_id": {"$in": tenant_ids}})
        return [Tenant.from_doc(doc) async for doc in cursor]

    async def list_tenants(
        self,
        *,
        search: str | None = None,
        plan: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Tenant]:
        query = self._query(search=search, plan=plan, status=status)
        cursor = (
            self._collection.find(query).sort("created_at", DESCENDING).skip(offset).limit(limit)
        )
        return [Tenant.from_doc(doc) async for doc in cursor]

    async def count_tenants(
        self,
        *,
        search: str | None = None,
        plan: str | None = None,
        status: str | None = None,
    ) -> int:
        return await self._collection.count_documents(
            self._query(search=search, plan=plan, status=status)
        )

    async def update(self, tenant: Tenant) -> None:
        await self._collection.replace_one({"_id": tenant.id}, tenant.to_doc())

    @staticmethod
    def _query(*, search: str | None, plan: str | None, status: str | None) -> dict[str, Any]:
        query: dict[str, Any] = {}
        if search:
            if len(search) > MAX_TENANT_SEARCH_LENGTH:
                raise ValueError(f"Search term exceeds {MAX_TENANT_SEARCH_LENGTH} characters.")
            # PERF-K03: this is deliberately a case-insensitive substring
            # `$regex` (find "Acme" inside "Acme Corporation"), bounded by
            # MAX_TENANT_SEARCH_LENGTH. MongoDB text indexes only serve the
            # `$text` operator and *cannot* accelerate `$regex`; migrating to
            # `$text` would change matching from substring to word-based and
            # silently alter admin search behavior. The admin surface is the
            # only caller and the 100-char cap keeps the scan bounded, so no
            # text index is created here.
            query["company_name"] = {"$regex": re.escape(search), "$options": "i"}
        if plan:
            query["plan"] = plan
        if status:
            query["status"] = status
        return query
