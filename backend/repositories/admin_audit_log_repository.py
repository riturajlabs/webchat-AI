"""Admin audit log data access (Protocol + MongoDB implementation, Phase 15).

Platform operator actions are written to the dedicated `admin_audit_logs`
collection (ADR-006 §Security: a dedicated audit trail for admin actions) and
read by the super-admin-only `GET /api/admin/audit` surface. Filters are
validated by the route; the query is platform-wide by design.
"""

from datetime import datetime
from typing import Any, Protocol

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import DESCENDING

from backend.models.admin_audit_log import AdminAuditLog


class AdminAuditLogRepository(Protocol):
    """Data access for the `admin_audit_logs` collection."""

    async def create(self, log: AdminAuditLog) -> None: ...

    async def list_logs(
        self,
        *,
        action: str | None = None,
        actor_user_id: str | None = None,
        tenant_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AdminAuditLog]: ...

    async def count_logs(
        self,
        *,
        action: str | None = None,
        actor_user_id: str | None = None,
        tenant_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> int: ...


class MongoAdminAuditLogRepository:
    """MongoDB-backed admin audit log repository."""

    def __init__(self, db: AsyncIOMotorDatabase[Any]) -> None:
        self._collection = db["admin_audit_logs"]

    async def create(self, log: AdminAuditLog) -> None:
        await self._collection.insert_one(log.to_doc())

    async def list_logs(
        self,
        *,
        action: str | None = None,
        actor_user_id: str | None = None,
        tenant_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AdminAuditLog]:
        query = self._query(
            action=action,
            actor_user_id=actor_user_id,
            tenant_id=tenant_id,
            since=since,
            until=until,
        )
        cursor = (
            self._collection.find(query).sort("created_at", DESCENDING).skip(offset).limit(limit)
        )
        return [AdminAuditLog.from_doc(doc) async for doc in cursor]

    async def count_logs(
        self,
        *,
        action: str | None = None,
        actor_user_id: str | None = None,
        tenant_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> int:
        query = self._query(
            action=action,
            actor_user_id=actor_user_id,
            tenant_id=tenant_id,
            since=since,
            until=until,
        )
        return await self._collection.count_documents(query)

    @staticmethod
    def _query(
        *,
        action: str | None,
        actor_user_id: str | None,
        tenant_id: str | None,
        since: datetime | None,
        until: datetime | None,
    ) -> dict[str, Any]:
        query: dict[str, Any] = {}
        if action is not None:
            query["action"] = action
        if actor_user_id is not None:
            query["actor_user_id"] = actor_user_id
        if tenant_id is not None:
            query["tenant_id"] = tenant_id
        created_at: dict[str, Any] = {}
        if since is not None:
            created_at["$gte"] = since
        if until is not None:
            created_at["$lte"] = until
        if created_at:
            query["created_at"] = created_at
        return query
