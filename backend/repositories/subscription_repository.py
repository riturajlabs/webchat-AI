"""Subscription data access (Protocol + MongoDB implementation, Phase 14).

Collection: `subscriptions`. Every query is scoped by `tenant_id` except the
webhook idempotency lookup (`find_by_payment_id`), which the provider gateway
drives - the returned document still carries its tenant so the service never
acts on a foreign tenant.

`find_active_by_tenant` implements the "current plan" rule with deterministic
precedence: an active `admin_grant` wins over any paid subscription, then the
newest `payment` subscription whose `end_date` is `None` (custom/enterprise)
or still in the future. Passing `now` keeps the repository pure.
"""

from datetime import datetime
from typing import Any, Protocol

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import DESCENDING

from backend.models.subscription import (
    SUBSCRIPTION_LIVE_STATUSES,
    SUBSCRIPTION_SOURCE_ADMIN_GRANT,
    Subscription,
)


def _live_query(now: datetime, *, source_override: dict[str, Any] | None = None) -> dict[str, Any]:
    """Mongo query for subscriptions granting plan limits at `now`."""
    query: dict[str, Any] = {
        "status": {"$in": sorted(SUBSCRIPTION_LIVE_STATUSES)},
        "$or": [
            {"end_date": None},
            {"end_date": {"$gte": now}},
        ],
    }
    if source_override:
        query.update(source_override)
    return query


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

    # Phase 16 admin grants (manual plan grants).
    async def find_active_admin_grant_by_tenant(
        self, tenant_id: str, *, now: datetime
    ) -> Subscription | None: ...

    async def find_active_for_tenant_ids(
        self, tenant_ids: list[str], *, now: datetime
    ) -> dict[str, Subscription]: ...


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

    async def find_active_admin_grant_by_tenant(
        self, tenant_id: str, *, now: datetime
    ) -> Subscription | None:
        query = _live_query(now, source_override={"source": SUBSCRIPTION_SOURCE_ADMIN_GRANT})
        query["tenant_id"] = tenant_id
        doc = await self._collection.find_one(query, sort=[("created_at", DESCENDING)])
        return Subscription.from_doc(doc) if doc else None

    async def find_active_by_tenant(self, tenant_id: str, *, now: datetime) -> Subscription | None:
        # Deterministic precedence: an active admin grant wins over any paid
        # subscription, then the newest paid (`payment`) subscription.
        grant = await self.find_active_admin_grant_by_tenant(tenant_id, now=now)
        if grant is not None:
            return grant
        query = _live_query(
            now, source_override={"source": {"$ne": SUBSCRIPTION_SOURCE_ADMIN_GRANT}}
        )
        query["tenant_id"] = tenant_id
        doc = await self._collection.find_one(query, sort=[("created_at", DESCENDING)])
        return Subscription.from_doc(doc) if doc else None

    async def find_active_for_tenant_ids(
        self, tenant_ids: list[str], *, now: datetime
    ) -> dict[str, Subscription]:
        """One active plan-granting subscription per tenant (grant-first).

        Used by the admin read surface to resolve effective plans for a page of
        tenants/users without N+1 lookups. Precedence matches
        `find_active_by_tenant` per tenant.
        """
        if not tenant_ids:
            return {}
        result: dict[str, Subscription] = {}
        grant_query = _live_query(now, source_override={"source": SUBSCRIPTION_SOURCE_ADMIN_GRANT})
        grant_query["tenant_id"] = {"$in": tenant_ids}
        grant_cursor = self._collection.find(grant_query).sort("created_at", DESCENDING)
        async for doc in grant_cursor:
            grant = Subscription.from_doc(doc)
            result.setdefault(grant.tenant_id, grant)
        remaining = [tenant_id for tenant_id in tenant_ids if tenant_id not in result]
        if not remaining:
            return result
        payment_query = _live_query(
            now, source_override={"source": {"$ne": SUBSCRIPTION_SOURCE_ADMIN_GRANT}}
        )
        payment_query["tenant_id"] = {"$in": remaining}
        payment_cursor = self._collection.find(payment_query).sort("created_at", DESCENDING)
        async for doc in payment_cursor:
            subscription = Subscription.from_doc(doc)
            result.setdefault(subscription.tenant_id, subscription)
        return result

    async def find_by_payment_id(self, payment_id: str) -> Subscription | None:
        doc = await self._collection.find_one({"payment_id": payment_id})
        return Subscription.from_doc(doc) if doc else None

    async def count_active(self, *, now: datetime) -> int:
        """Count plan-granting paid subscriptions live at `now` (MRR basis).

        Admin grants (`amount_cents=0`, `source="admin_grant"`) are exempt so
        the headline subscription count reflects paying tenants only.
        """
        query = _live_query(
            now, source_override={"source": {"$ne": SUBSCRIPTION_SOURCE_ADMIN_GRANT}}
        )
        return await self._collection.count_documents(query)

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
