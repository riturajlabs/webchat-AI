"""Tenant-wide data purge (application-level cascade for account deletion).

MongoDB has no foreign-key CASCADE, so deleting an account (and therefore its
tenant) requires purging every tenant-scoped collection explicitly. This
repository owns that purge in one cohesive unit: it hard-deletes every
document belonging to a tenant across all collections, plus the tenant's own
record and its users/members.

The caller is responsible for resolving the account from the authenticated
principal — never from client-supplied identifiers — and for sequencing the
purge (e.g. revoking/removing auth records) around it.
"""

from typing import Any, Protocol

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.core.errors import StorageError
from backend.services.storage.base import StorageService

# Tenant-scoped collections that must be emptied when a tenant is deleted.
# Kept in dependency order so dependent resources (documents, chunks) are
# removed before their parents where it reads naturally; all are hard deletes.
_TENANT_COLLECTIONS: tuple[str, ...] = (
    "crawl_jobs",
    "chat_sessions",
    "messages",
    "feedback",
    "api_keys",
    "subscriptions",
    "usage_events",
    "usage_records",
    "audit_logs",
    "refresh_tokens",
    "members",
    "widgets",
    "knowledge_chunks",
    "documents",
    "websites",
)


class TenantPurgeRepository(Protocol):
    """Purge every document owned by a tenant (account-deletion cascade)."""

    async def purge_tenant(self, tenant_id: str) -> None:
        """Hard-delete all tenant-scoped resources, users and the tenant itself."""
        ...

    async def purge_user_sessions(self, user_id: str) -> None:
        """Remove all refresh-token sessions for a user."""
        ...


class MongoTenantPurgeRepository:
    """MongoDB-backed tenant purge (docs/05, account deletion)."""

    def __init__(
        self,
        db: AsyncIOMotorDatabase[Any],
        storage: StorageService | None = None,
    ) -> None:
        self._db = db
        # FU-01: uploaded-file binaries live in GridFS outside the tenant-scoped
        # collections, so they must be removed through the StorageService before
        # their document records (and the storage_key they carry) are purged.
        # Optional so pre-existing call sites/tests keep working without storage.
        self._storage = storage

    async def purge_tenant(self, tenant_id: str) -> None:
        # FU-01: delete the tenant's uploaded file binaries first, while the
        # `documents` rows still hold the storage keys. The enumeration and
        # every deletion are strict tenant-scoped (never an unscoped GridFS
        # wipe). A storage failure raises before any collection is purged so
        # the purge never reports success while still retaining the files that
        # back the tenant's (about-to-be-deleted) document records.
        await self._delete_file_storage(tenant_id)
        for name in _TENANT_COLLECTIONS:
            await self._db[name].delete_many({"tenant_id": tenant_id})
        # The tenant itself and its users share the tenant_id key.
        await self._db["tenants"].delete_many({"_id": tenant_id})
        await self._db["users"].delete_many({"tenant_id": tenant_id})

    async def _delete_file_storage(self, tenant_id: str) -> None:
        """Tenant-scoped GridFS cleanup for uploaded files (FU-01)."""
        if self._storage is None:
            return
        cursor = self._db["documents"].find(
            {
                "tenant_id": tenant_id,
                "source_type": "file",
                "storage_key": {"$nin": [None, ""]},
            },
            projection={"_id": 1, "storage_key": 1},
        )
        # Every deletion is attributable to (tenant_id, document_id, storage_key):
        # the storage_key is the GridFS id whose own metadata records the same
        # tenant/document, and `StorageService.delete` validates ownership.
        pending: list[tuple[str, str]] = []
        async for doc in cursor:
            pending.append((str(doc["_id"]), str(doc["storage_key"])))
        if not pending:
            return
        failed: list[tuple[str, str]] = []
        for document_id, storage_key in pending:
            deleted = await self._storage.delete(
                tenant_id=tenant_id,
                storage_key=storage_key,
            )
            if not deleted:
                failed.append((document_id, storage_key))
        if failed:
            raise StorageError(f"Failed to delete stored files for tenant {tenant_id}: {failed}")

    async def purge_user_sessions(self, user_id: str) -> None:
        await self._db["refresh_tokens"].delete_many({"user_id": user_id})


__all__ = ["TenantPurgeRepository", "MongoTenantPurgeRepository"]
