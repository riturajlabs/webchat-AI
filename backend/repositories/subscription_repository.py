"""Subscription data access (Protocol + MongoDB implementation, Phase 14).

Collection: `subscriptions`. Every query is scoped by `tenant_id` except the
webhook idempotency lookup (`find_by_payment_id`), which the provider gateway
drives - the returned document still carries its tenant so the service never
acts on a foreign tenant.

`find_active_by_tenant` implements the "current plan" rule: the newest
`active`/`trialing` subscription whose `end_date` is `None` (custom/enterprise)
or still in the future. Passing `now` keeps the repository pure.
"""

from datetime import datetime
from typing import Any, Protocol

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import DESCENDING

from backend.models.subscription import (
    SUBSCRIPTION_LIVE_STATUSES,
    Subscription,
)


class SubscriptionRepository(Protocol):
    """Data access for the `subscriptions` collection (tenant-scoped)."""

    async def create(self, subscription: Subscription) -> None: ...

    async def update(self, subscription: Subscription) -> None: ...

    async def find_active_by_tenant(
        self, tenant_id: str, *, now: datetime
    ) -> Subscription | None: ...

    async def count_active(self, *, now: datetime) -> int: ...

    async def find_by_payment_id(self, payment_id: str) -> Subscription | None: ...

    async def list_by_tenant(self, tenant_id: str, *, limit: int = 50) -> list[Subscription]: ...

    # Phase 15 revenue accounting (admin surface). Aggregate the money actually
    # charged for paid billing periods, newest first.
    async def list_paid(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 500,
    ) -> list[Subscription]: ...


class MongoSubscriptionRepository:
    """MongoDB-backed subscription repository."""

    def __init__(self, db: AsyncIOMotorDatabase[Any]) -> None:
        self._collection = db["subscriptions"]

    async def create(self, subscription: Subscription) -> None:
        await self._collection.insert_one(subscription.to_doc())

    async def update(self, subscription: Subscription) -> None:
        await self._collection.replace_one(
            {"_id": subscription.id, "tenant_id": subscription.tenant_id},
            subscription.to_doc(),
        )

    async def find_active_by_tenant(self, tenant_id: str, *, now: datetime) -> Subscription | None:
        doc = await self._collection.find_one(
            {
                "tenant_id": tenant_id,
                "status": {"$in": sorted(SUBSCRIPTION_LIVE_STATUSES)},
                "$or": [
                    {"end_date": None},
                    {"end_date": {"$gte": now}},
                ],
            },
            sort=[("created_at", DESCENDING)],
        )
        return Subscription.from_doc(doc) if doc else None

    async def find_by_payment_id(self, payment_id: str) -> Subscription | None:
        doc = await self._collection.find_one({"payment_id": payment_id})
        return Subscription.from_doc(doc) if doc else None

    async def count_active(self, *, now: datetime) -> int:
        """Count plan-granting subscriptions live at `now` (MRR basis)."""
        return await self._collection.count_documents(
            {
                "status": {"$in": sorted(SUBSCRIPTION_LIVE_STATUSES)},
                "$or": [
                    {"end_date": None},
                    {"end_date": {"$gte": now}},
                ],
            }
        )

    async def list_by_tenant(self, tenant_id: str, *, limit: int = 50) -> list[Subscription]:
        cursor = (
            self._collection.find({"tenant_id": tenant_id})
            .sort("created_at", DESCENDING)
            .limit(limit)
        )
        return [Subscription.from_doc(doc) async for doc in cursor]

    async def list_paid(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 500,
    ) -> list[Subscription]:
        query: dict[str, Any] = {"status": "active", "amount_cents": {"$gt": 0}}
        if since is not None or until is not None:
            created_at: dict[str, Any] = {}
            if since is not None:
                created_at["$gte"] = since
            if until is not None:
                created_at["$lte"] = until
            query["created_at"] = created_at
        cursor = self._collection.find(query).sort("created_at", DESCENDING).limit(limit)
        return [Subscription.from_doc(doc) async for doc in cursor]


__all__ = ["MongoSubscriptionRepository", "SubscriptionRepository"]
