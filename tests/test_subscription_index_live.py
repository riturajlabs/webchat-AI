"""Real-MongoDB integration tests for the subscriptions payment_id index fix.

The P0 regression (grant -> revoke -> grant returning E11000 on the
non-partial `payment_id_1` unique index) is a *collection-level* index
collision, so it can only be conclusively proven fixed against a real
MongoDB - FakeSubscriptionRepository never hits the real index. These tests
run the migration helper and the grant/revoke lifecycle through the real
`MongoSubscriptionRepository`.

Self-skipping, matching the e2e convention: the suite is inert unless
`LIVE_MONGO_URI` is set, so the regular hermetic unit run stays green. Each
run uses a throwaway database and drops it on teardown.

Usage:
    LIVE_MONGO_URI=mongodb://localhost:27017 \\\
        .venv/bin/python -m pytest tests/test_subscription_index_live.py -q
"""

from __future__ import annotations

import os
import uuid
from datetime import timedelta
from typing import Any

import pytest
from backend.core.database import _ensure_subscription_payment_id_index
from backend.core.security import utcnow
from backend.models.subscription import (
    SUBSCRIPTION_SOURCE_ADMIN_GRANT,
    SUBSCRIPTION_SOURCE_PAYMENT,
    SUBSCRIPTION_STATUS_ACTIVE,
    SUBSCRIPTION_STATUS_CANCELLED,
    Subscription,
)
from backend.repositories.subscription_repository import MongoSubscriptionRepository
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import DuplicateKeyError

LIVE_MONGO_URI = os.environ.get("LIVE_MONGO_URI")

pytestmark = pytest.mark.skipif(
    not LIVE_MONGO_URI,
    reason="LIVE_MONGO_URI not set (real-Mongo integration test)",
)


@pytest.fixture
async def mongo_db() -> Any:
    client = AsyncIOMotorClient(LIVE_MONGO_URI, serverSelectionTimeoutMS=3000)
    db = client[f"webchat_ai_index_integration_{uuid.uuid4().hex[:8]}"]
    try:
        yield db
    finally:
        await client.drop_database(db.name)
        client.close()


def _paid_sub(tenant_id: str, payment_id: str) -> Subscription:
    now = utcnow()
    return Subscription.new(
        tenant_id=tenant_id,
        plan_id="pro",
        status=SUBSCRIPTION_STATUS_ACTIVE,
        source=SUBSCRIPTION_SOURCE_PAYMENT,
        payment_provider="mock",
        payment_id=payment_id,
        start_date=now,
        end_date=now + timedelta(days=30),
        amount_cents=2500,
        currency="usd",
    )


def _grant_sub(tenant_id: str, *, grant_reason: str) -> Subscription:
    now = utcnow()
    return Subscription.new(
        tenant_id=tenant_id,
        plan_id="pro",
        status=SUBSCRIPTION_STATUS_ACTIVE,
        source=SUBSCRIPTION_SOURCE_ADMIN_GRANT,
        payment_provider="admin",
        payment_id=None,
        start_date=now,
        end_date=now + timedelta(days=30),
        amount_cents=0,
        currency=None,
        granted_by="super_admin@example.com",
        granted_at=now,
        grant_reason=grant_reason,
    )


async def _create_legacy_non_partial_index(db: Any) -> None:
    await db["subscriptions"].create_index("payment_id", unique=True)


async def test_migrates_legacy_index_and_allows_multiple_grants(mongo_db: Any) -> None:
    repo = MongoSubscriptionRepository(mongo_db)
    await _create_legacy_non_partial_index(mongo_db)
    first_grant = _grant_sub("tenant-1", grant_reason="original")
    await repo.create(first_grant)
    await repo.create(_paid_sub("tenant-1", "pm_1"))

    second_grant = _grant_sub("tenant-1", grant_reason="regrant")
    with pytest.raises(DuplicateKeyError):
        await repo.create(second_grant)

    await _ensure_subscription_payment_id_index(mongo_db)

    info = await mongo_db["subscriptions"].index_information()
    payment = info["payment_id_1"]
    assert payment["unique"] is True
    assert payment["partialFilterExpression"] == {"payment_id": {"$type": "string"}}

    await repo.create(second_grant)
    with pytest.raises(DuplicateKeyError):
        await repo.create(_paid_sub("tenant-1", "pm_1"))
    await repo.create(_paid_sub("tenant-1", "pm_2"))

    await _ensure_subscription_payment_id_index(mongo_db)
    still_partial = await mongo_db["subscriptions"].index_information()
    assert still_partial["payment_id_1"]["partialFilterExpression"] == {
        "payment_id": {"$type": "string"}
    }


async def test_grant_revoke_regrant_lifecycle(mongo_db: Any) -> None:
    repo = MongoSubscriptionRepository(mongo_db)
    await _ensure_subscription_payment_id_index(mongo_db)
    tenant = "tenant-lifecycle"
    now = utcnow()

    grant = _grant_sub(tenant, grant_reason="first")
    await repo.create(grant)
    active = await repo.find_active_by_tenant(tenant, now=now)
    assert active is not None and active.source == SUBSCRIPTION_SOURCE_ADMIN_GRANT

    revoked = grant.model_copy(
        update={"status": SUBSCRIPTION_STATUS_CANCELLED, "updated_at": utcnow()}
    )
    await repo.update(revoked)
    assert await repo.find_active_by_tenant(tenant, now=now) is None

    regrant = _grant_sub(tenant, grant_reason="second")
    await repo.create(regrant)
    active_after = await repo.find_active_by_tenant(tenant, now=now)
    assert active_after is not None and active_after.id == regrant.id

    history = await repo.list_by_tenant(tenant)
    assert len(history) == 2
    assert {item.status for item in history} == {
        SUBSCRIPTION_STATUS_ACTIVE,
        SUBSCRIPTION_STATUS_CANCELLED,
    }


async def test_cross_tenant_grants_do_not_collide(mongo_db: Any) -> None:
    repo = MongoSubscriptionRepository(mongo_db)
    await _ensure_subscription_payment_id_index(mongo_db)
    now = utcnow()

    tenant_a_grant = _grant_sub("tenant-a", grant_reason="a")
    await repo.create(tenant_a_grant)
    revoked_a = tenant_a_grant.model_copy(
        update={"status": SUBSCRIPTION_STATUS_CANCELLED, "updated_at": utcnow()}
    )
    await repo.update(revoked_a)

    tenant_b_grant = _grant_sub("tenant-b", grant_reason="b")
    await repo.create(tenant_b_grant)

    assert await repo.find_active_by_tenant("tenant-a", now=now) is None
    active_b = await repo.find_active_by_tenant("tenant-b", now=now)
    assert active_b is not None and active_b.id == tenant_b_grant.id


async def test_paid_payment_ids_remain_unique(mongo_db: Any) -> None:
    repo = MongoSubscriptionRepository(mongo_db)
    await _ensure_subscription_payment_id_index(mongo_db)

    await repo.create(_paid_sub("tenant-paid", "pm_dup"))
    with pytest.raises(DuplicateKeyError):
        await repo.create(_paid_sub("tenant-paid", "pm_dup"))
