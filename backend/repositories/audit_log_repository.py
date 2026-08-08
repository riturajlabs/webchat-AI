"""Audit log data access (Protocol + MongoDB implementation)."""

from typing import Any, Protocol

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.models.audit_log import AuditLog


class AuditLogRepository(Protocol):
    """Data access for the `audit_logs` collection."""

    async def create(self, log: AuditLog) -> None: ...


class MongoAuditLogRepository:
    """MongoDB-backed audit log repository."""

    def __init__(self, db: AsyncIOMotorDatabase[Any]) -> None:
        self._collection = db["audit_logs"]

    async def create(self, log: AuditLog) -> None:
        await self._collection.insert_one(log.to_doc())
