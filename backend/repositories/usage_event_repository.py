"""Usage event data access (Phase 13, SaaS billing foundation).

Append-only `usage_events` writes via `record` (atomic `insert_one` per event)
and windowed tenant sums via `totals_by_type_since` (one `$group` aggregation).
Event types are validated against `USAGE_EVENT_TYPES` so a typo fails fast
instead of creating an untracked bucket.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.models.usage_event import (
    USAGE_EVENT_TYPES,
    UsageEvent,
)


@dataclass(frozen=True)
class UsageEventTotals:
    """Sum of every event type for one tenant over a window."""

    messages_sent: int = 0
    ai_responses: int = 0
    tokens_used: int = 0
    documents_created: int = 0
    crawl_pages: int = 0

    def total(self, event_type: str) -> int:
        """Return the summed quantity for `event_type` (0 for unknown)."""
        if event_type not in USAGE_EVENT_TYPES:
            return 0
        return int(getattr(self, event_type))


class UsageEventRepository(Protocol):
    """Append-only usage events (tenant-scoped reads)."""

    async def record(self, event: UsageEvent) -> None: ...

    async def totals_by_type_since(
        self, tenant_id: str, since: datetime
    ) -> UsageEventTotals: ...


class MongoUsageEventRepository:
    """MongoDB-backed usage event repository."""

    def __init__(self, db: AsyncIOMotorDatabase[Any]) -> None:
        self._collection = db["usage_events"]

    async def record(self, event: UsageEvent) -> None:
        if event.event_type not in USAGE_EVENT_TYPES:
            raise ValueError(f"Unknown usage event type: {event.event_type}")
        await self._collection.insert_one(event.to_doc())

    async def totals_by_type_since(
        self, tenant_id: str, since: datetime
    ) -> UsageEventTotals:
        rows: dict[str, int] = {}
        cursor = self._collection.aggregate(
            [
                {"$match": {"tenant_id": tenant_id, "created_at": {"$gte": since}}},
                {
                    "$group": {
                        "_id": "$event_type",
                        "quantity": {"$sum": "$quantity"},
                    }
                },
            ]
        )
        async for doc in cursor:
            rows[str(doc["_id"])] = int(doc["quantity"])
        return UsageEventTotals(
            messages_sent=rows.get("messages_sent", 0),
            ai_responses=rows.get("ai_responses", 0),
            tokens_used=rows.get("tokens_used", 0),
            documents_created=rows.get("documents_created", 0),
            crawl_pages=rows.get("crawl_pages", 0),
        )


__all__ = [
    "MongoUsageEventRepository",
    "UsageEventRepository",
    "UsageEventTotals",
]
