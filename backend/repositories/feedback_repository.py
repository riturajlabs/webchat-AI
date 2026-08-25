"""Visitor feedback data access (Phase 12.4, ADR-005 §5.6).

Protocol + MongoDB implementation for the `feedback` collection. Every query
is tenant-scoped (00-AI-Development-Rules.md §7): a tenant can only ever read
or deduplicate its own ratings. `summary_by_tenant` drives the dashboard
"User Satisfaction" breakdown (avg rating + 1-5 distribution), using the
`rating` + `tenant_id` indexes defined in ADR-005 §5.6.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import DESCENDING
from pymongo.errors import DuplicateKeyError

from backend.models.feedback import FEEDBACK_MAX_RATING, Feedback


@dataclass(frozen=True)
class FeedbackSummary:
    """Dashboard satisfaction summary (UI/UX §12 "User Satisfaction")."""

    total: int
    average_rating: float | None
    distribution: dict[int, int]


class FeedbackRepository(Protocol):
    """Data access for the `feedback` collection (tenant-scoped)."""

    async def create(self, feedback: Feedback) -> None: ...

    async def find_by_message(self, tenant_id: str, message_id: str) -> Feedback | None: ...

    async def list_by_tenant(
        self,
        tenant_id: str,
        *,
        website_id: str | None = None,
        category: str | None = None,
        rating: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Feedback]: ...

    async def count_by_tenant(
        self,
        tenant_id: str,
        *,
        website_id: str | None = None,
        category: str | None = None,
        rating: int | None = None,
    ) -> int: ...

    async def summary_by_tenant(
        self,
        tenant_id: str,
        *,
        website_id: str | None = None,
        since: datetime | None = None,
    ) -> FeedbackSummary: ...


class MongoFeedbackRepository:
    """MongoDB-backed feedback repository."""

    def __init__(self, db: AsyncIOMotorDatabase[Any]) -> None:
        self._collection = db["feedback"]

    async def create(self, feedback: Feedback) -> None:
        """Insert one rating; idempotent on the unique (tenant_id, message_id) index.

        A concurrent duplicate submit (the TOCTOU window between the service's
        `find_by_message` dedup check and this insert) loses the race here as
        a `DuplicateKeyError`. Swallowing it keeps `create` an idempotent
        success — "a message is rated at most once" means the loser already
        got what it asked for. pymongo stays confined to the repository layer.
        """
        try:
            await self._collection.insert_one(feedback.to_doc())
        except DuplicateKeyError:
            return

    async def find_by_message(self, tenant_id: str, message_id: str) -> Feedback | None:
        doc = await self._collection.find_one({"tenant_id": tenant_id, "message_id": message_id})
        return Feedback.from_doc(doc) if doc else None

    async def list_by_tenant(
        self,
        tenant_id: str,
        *,
        website_id: str | None = None,
        category: str | None = None,
        rating: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Feedback]:
        query = self._query(tenant_id, website_id=website_id, category=category, rating=rating)
        cursor = (
            self._collection.find(query).sort("created_at", DESCENDING).skip(offset).limit(limit)
        )
        return [Feedback.from_doc(doc) async for doc in cursor]

    async def count_by_tenant(
        self,
        tenant_id: str,
        *,
        website_id: str | None = None,
        category: str | None = None,
        rating: int | None = None,
    ) -> int:
        query = self._query(tenant_id, website_id=website_id, category=category, rating=rating)
        return await self._collection.count_documents(query)

    async def summary_by_tenant(
        self,
        tenant_id: str,
        *,
        website_id: str | None = None,
        since: datetime | None = None,
    ) -> FeedbackSummary:
        """Aggregate ratings for the satisfaction summary.

        A single `$group` pass buckets by `rating` and yields the per-rating
        counts plus the total; the average is computed in the service so this
        stays a pure count read (cheap even for large collections).
        """
        match: dict[str, Any] = {"tenant_id": tenant_id}
        if website_id is not None:
            match["website_id"] = website_id
        if since is not None:
            match["created_at"] = {"$gte": since}
        pipeline: list[dict[str, Any]] = [
            {"$match": match},
            {
                "$group": {
                    "_id": "$rating",
                    "count": {"$sum": 1},
                }
            },
        ]
        cursor = self._collection.aggregate(pipeline)
        distribution: dict[int, int] = {}
        total = 0
        async for doc in cursor:
            rating = int(doc["_id"])
            if not 1 <= rating <= FEEDBACK_MAX_RATING:
                continue
            count = int(doc.get("count", 0))
            distribution[rating] = count
            total += count
        return FeedbackSummary(
            total=total,
            average_rating=None,
            distribution=distribution,
        )

    @staticmethod
    def _query(
        tenant_id: str,
        *,
        website_id: str | None,
        category: str | None,
        rating: int | None,
    ) -> dict[str, Any]:
        query: dict[str, Any] = {"tenant_id": tenant_id}
        if website_id is not None:
            query["website_id"] = website_id
        if category is not None:
            query["category"] = category
        if rating is not None:
            query["rating"] = rating
        return query


__all__ = ["FeedbackRepository", "FeedbackSummary", "MongoFeedbackRepository"]
