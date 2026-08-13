"""Daily usage rollup data access (Phase 6, ADR-005 §5.5).

`increment` is an atomic `$inc` upsert on the unique (tenant_id, website_id,
date) key: concurrent requests never lose counts (no read-modify-write).
Counter names are validated against `USAGE_COUNTERS` before hitting Mongo so
typos fail fast instead of creating stray fields.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.core.security import new_id, utcnow
from backend.models.usage_record import USAGE_COUNTERS, UsageRecord


@dataclass(frozen=True)
class TenantUsageSummary:
    """All-time platform totals for one tenant (Phase 12.5, ADR-006)."""

    chats: int
    messages: int
    input_tokens: int
    output_tokens: int


class UsageRecordRepository(Protocol):
    """Daily per-website usage rollups (tenant-scoped)."""

    async def increment(
        self,
        *,
        tenant_id: str,
        website_id: str,
        date: str,
        counters: Mapping[str, int],
    ) -> None: ...

    async def get(self, tenant_id: str, website_id: str, date: str) -> UsageRecord | None: ...

    # Phase 12.5 admin surface (ADR-006 §Tenant Management / detail).
    async def sum_by_tenant(self, tenant_id: str) -> TenantUsageSummary: ...


class MongoUsageRecordRepository:
    """MongoDB-backed usage rollup repository."""

    def __init__(self, db: AsyncIOMotorDatabase[Any]) -> None:
        self._collection = db["usage_records"]

    async def increment(
        self,
        *,
        tenant_id: str,
        website_id: str,
        date: str,
        counters: Mapping[str, int],
    ) -> None:
        unknown = set(counters) - set(USAGE_COUNTERS)
        if unknown:
            raise ValueError(f"Unknown usage counter(s): {sorted(unknown)}")
        increments = {f"counters.{name}": value for name, value in counters.items() if value}
        if not increments:
            return
        now = utcnow()
        await self._collection.update_one(
            {"tenant_id": tenant_id, "website_id": website_id, "date": date},
            {
                "$inc": increments,
                "$setOnInsert": {
                    "_id": new_id(),
                    "created_at": now,
                },
                "$set": {"updated_at": now, "schema_version": 1},
            },
            upsert=True,
        )

    async def get(self, tenant_id: str, website_id: str, date: str) -> UsageRecord | None:
        doc = await self._collection.find_one(
            {"tenant_id": tenant_id, "website_id": website_id, "date": date}
        )
        return UsageRecord.from_doc(doc) if doc else None

    async def sum_by_tenant(self, tenant_id: str) -> TenantUsageSummary:
        doc = await self._first(
            self._collection.aggregate(
                [
                    {"$match": {"tenant_id": tenant_id}},
                    {
                        "$group": {
                            "_id": None,
                            "chats": {"$sum": "$counters.chats"},
                            "messages": {"$sum": "$counters.messages"},
                            "input_tokens": {"$sum": "$counters.input_tokens"},
                            "output_tokens": {"$sum": "$counters.output_tokens"},
                        }
                    },
                ]
            )
        )
        return TenantUsageSummary(
            chats=int(doc.get("chats", 0)) if doc else 0,
            messages=int(doc.get("messages", 0)) if doc else 0,
            input_tokens=int(doc.get("input_tokens", 0)) if doc else 0,
            output_tokens=int(doc.get("output_tokens", 0)) if doc else 0,
        )

    @staticmethod
    async def _first(cursor: Any) -> dict[str, Any] | None:
        async for doc in cursor:
            return dict(doc)
        return None


__all__ = [
    "MongoUsageRecordRepository",
    "TenantUsageSummary",
    "UsageRecordRepository",
]
