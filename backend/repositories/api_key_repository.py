"""API key data access (Protocol + MongoDB implementation).

Collection: `api_keys` (docs/05-Backend-Schema.md §12). Every query is scoped
by `tenant_id` (00-AI-Development-Rules §7): a foreign tenant can never read
or mutate another tenant's keys. Revoke is a soft delete (`status = "revoked"`)
- the document is preserved for audit but excluded from all tenant-facing reads.
"""

from datetime import datetime
from typing import Any, Protocol

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import DESCENDING

from backend.core.security import utcnow
from backend.models.api_key import API_KEY_STATUS_ACTIVE, API_KEY_STATUS_REVOKED, ApiKey


class ApiKeyRepository(Protocol):
    """Data access for the `api_keys` collection (tenant-scoped)."""

    async def create(self, key: ApiKey) -> None: ...

    async def find_by_id(self, tenant_id: str, key_id: str) -> ApiKey | None: ...

    async def list_by_tenant(self, tenant_id: str) -> list[ApiKey]: ...

    async def revoke(self, tenant_id: str, key_id: str) -> None: ...

    # Authentication lookup by hashed secret (Sprint 2). Not tenant-scoped: the
    # SHA-256 hash uniquely identifies the key; tenant ownership is validated
    # by the service after the lookup.
    async def find_by_hash(self, hashed_secret: str) -> ApiKey | None: ...

    async def touch_last_used(self, key_id: str, used_at: datetime) -> None: ...


class MongoApiKeyRepository:
    """MongoDB-backed API key repository.

    Only active keys are returned: revoked keys remain on disk for audit but
    are invisible to create/list/revoke operations.
    """

    def __init__(self, db: AsyncIOMotorDatabase[Any]) -> None:
        self._collection = db["api_keys"]

    async def create(self, key: ApiKey) -> None:
        await self._collection.insert_one(key.to_doc())

    async def find_by_id(self, tenant_id: str, key_id: str) -> ApiKey | None:
        doc = await self._collection.find_one(
            {
                "_id": key_id,
                "tenant_id": tenant_id,
                "status": API_KEY_STATUS_ACTIVE,
            }
        )
        return ApiKey.from_doc(doc) if doc else None

    async def list_by_tenant(self, tenant_id: str) -> list[ApiKey]:
        cursor = self._collection.find(
            {"tenant_id": tenant_id, "status": API_KEY_STATUS_ACTIVE}
        ).sort("created_at", DESCENDING)
        return [ApiKey.from_doc(doc) async for doc in cursor]

    async def revoke(self, tenant_id: str, key_id: str) -> None:
        doc = await self._collection.find_one(
            {
                "_id": key_id,
                "tenant_id": tenant_id,
                "status": API_KEY_STATUS_ACTIVE,
            }
        )
        if doc is None:
            return
        key = ApiKey.from_doc(doc)
        key.status = API_KEY_STATUS_REVOKED
        key.updated_at = utcnow()
        await self._collection.replace_one(
            {"_id": key.id, "tenant_id": key.tenant_id}, key.to_doc()
        )

    async def find_by_hash(self, hashed_secret: str) -> ApiKey | None:
        doc = await self._collection.find_one({"hashed_secret": hashed_secret})
        return ApiKey.from_doc(doc) if doc else None

    async def touch_last_used(self, key_id: str, used_at: datetime) -> None:
        await self._collection.update_one(
            {"_id": key_id},
            {"$set": {"last_used_at": used_at, "updated_at": used_at}},
        )


__all__ = ["ApiKeyRepository", "MongoApiKeyRepository"]
