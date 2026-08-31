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

    def __init__(self, db: AsyncIOMotorDatabase[Any]) -> None:
        self._db = db

    async def purge_tenant(self, tenant_id: str) -> None:
        for name in _TENANT_COLLECTIONS:
            await self._db[name].delete_many({"tenant_id": tenant_id})
        # The tenant itself and its users share the tenant_id key.
        await self._db["tenants"].delete_many({"_id": tenant_id})
        await self._db["users"].delete_many({"tenant_id": tenant_id})

    async def purge_user_sessions(self, user_id: str) -> None:
        await self._db["refresh_tokens"].delete_many({"user_id": user_id})


__all__ = ["TenantPurgeRepository", "MongoTenantPurgeRepository"]
