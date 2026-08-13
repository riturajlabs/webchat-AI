"""Audit log data access (Protocol + MongoDB implementation).

Phase 12.5 adds the admin-facing `list_audits`/`count_audits` viewer surface
(ADR-006 §Audit Logs). Filters are validated by the route/service; the query
itself is platform-wide by design and reachable only via `role=admin`.
"""

from datetime import datetime
from typing import Any, Protocol

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import DESCENDING

from backend.models.audit_log import AuditLog


class AuditLogRepository(Protocol):
    """Data access for the `audit_logs` collection."""

    async def create(self, log: AuditLog) -> None: ...

    # Phase 12.5 admin surface (ADR-006 §Audit Logs).
    async def list_audits(
        self,
        *,
        action: str | None = None,
        tenant_id: str | None = None,
        user_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AuditLog]: ...

    async def count_audits(
        self,
        *,
        action: str | None = None,
        tenant_id: str | None = None,
        user_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> int: ...


class MongoAuditLogRepository:
    """MongoDB-backed audit log repository."""

    def __init__(self, db: AsyncIOMotorDatabase[Any]) -> None:
        self._collection = db["audit_logs"]

    async def create(self, log: AuditLog) -> None:
        await self._collection.insert_one(log.to_doc())

    async def list_audits(
        self,
        *,
        action: str | None = None,
        tenant_id: str | None = None,
        user_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AuditLog]:
        query = self._query(
            action=action, tenant_id=tenant_id, user_id=user_id, since=since, until=until
        )
        cursor = (
            self._collection.find(query).sort("created_at", DESCENDING).skip(offset).limit(limit)
        )
        return [AuditLog.from_doc(doc) async for doc in cursor]

    async def count_audits(
        self,
        *,
        action: str | None = None,
        tenant_id: str | None = None,
        user_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> int:
        query = self._query(
            action=action, tenant_id=tenant_id, user_id=user_id, since=since, until=until
        )
        return await self._collection.count_documents(query)

    @staticmethod
    def _query(
        *,
        action: str | None,
        tenant_id: str | None,
        user_id: str | None,
        since: datetime | None,
        until: datetime | None,
    ) -> dict[str, Any]:
        query: dict[str, Any] = {}
        if action is not None:
            query["action"] = action
        if tenant_id is not None:
            query["tenant_id"] = tenant_id
        if user_id is not None:
            query["user_id"] = user_id
        created_at: dict[str, Any] = {}
        if since is not None:
            created_at["$gte"] = since
        if until is not None:
            created_at["$lte"] = until
        if created_at:
            query["created_at"] = created_at
        return query
