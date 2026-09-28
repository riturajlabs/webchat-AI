"""Phase 17A queue integration test fixtures.

Every Mongo-backed queue test connects to the ISOLATED prototype mongod
(default ``127.0.0.0.1:27019`` -> ``127.0.0.1:27019`` - a dedicated ephemeral
instance, never production Atlas and never the dev docker stack). Each test
gets its own database/collection, dropped afterwards, so tests cannot interfere
with each other, with the application database, or with the prototype's own
collection.

Override the endpoint via ``PROTOTYPE_MONGO_URI`` (shared with the prototype
suite) if the runner must use a different isolated instance.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from backend.prototypes.mongo_queue.config import DEFAULT_MONGO_URI
from backend.queue.mongo_adapter import MongoQueueAdapter
from backend.queue.runtime import reset_worker_queue
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

_TEST_DB = "webchat_ai_queue_test"


@pytest.fixture(autouse=True)
def _isolate_worker_queue() -> Iterator[None]:
    """Drop the process worker-queue singleton around every test.

    Phase 18A: the API producers enqueue through a cached process
    ``WorkerQueue``. Without this, an adapter built by one test (pointing at that
    test's fake Redis or Mongo database) would leak into the next one.
    """
    reset_worker_queue()
    yield
    reset_worker_queue()


def _prototype_uri() -> str:
    return os.environ.get("PROTOTYPE_MONGO_URI", DEFAULT_MONGO_URI)


@pytest.fixture
async def mongo_client() -> AsyncIterator[AsyncIOMotorClient[dict[str, Any]]]:
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        _prototype_uri(), serverSelectionTimeoutMS=3000, tz_aware=True
    )
    try:
        await client.admin.command("ping")
    except Exception as exc:  # noqa: BLE001 - environment guard
        client.close()
        pytest.skip(f"isolated prototype mongod unreachable at {_prototype_uri()}: {exc}")
    yield client
    client.close()


@pytest.fixture
async def queue_db(
    mongo_client: AsyncIOMotorClient[dict[str, Any]],
) -> AsyncIterator[AsyncIOMotorDatabase[dict[str, Any]]]:
    """A test database whose collections are dropped on teardown."""
    database = mongo_client[_TEST_DB]
    yield database
    for name in await database.list_collection_names():
        await database.drop_collection(name)


@pytest.fixture
async def adapter(
    queue_db: AsyncIOMotorDatabase[dict[str, Any]],
) -> AsyncIterator[MongoQueueAdapter]:
    queue = MongoQueueAdapter(queue_db, collection_name="worker_jobs")
    await queue.ensure_indexes()
    return_queue = queue
    yield return_queue
    await queue_db.drop_collection("worker_jobs")


@pytest.fixture
async def retention_adapter(
    queue_db: AsyncIOMotorDatabase[dict[str, Any]],
) -> AsyncIterator[MongoQueueAdapter]:
    """An adapter with retention enabled (TTL index on ``finished_at``)."""
    queue = MongoQueueAdapter(queue_db, collection_name="worker_jobs_retention", retention_days=7.0)
    await queue.ensure_indexes()
    yield queue
    await queue_db.drop_collection("worker_jobs_retention")


@pytest.fixture
async def short_lease_adapter(
    queue_db: AsyncIOMotorDatabase[dict[str, Any]],
) -> AsyncIterator[MongoQueueAdapter]:
    """A 0.5 s lease with a 0.1 s heartbeat, for real dual-execution timing."""
    queue = MongoQueueAdapter(
        queue_db,
        collection_name="worker_jobs_short_lease",
        lease_seconds=0.5,
        heartbeat_seconds=0.1,
    )
    await queue.ensure_indexes()
    yield queue
    await queue_db.drop_collection("worker_jobs_short_lease")


@pytest.fixture
async def isolated_adapter(
    mongo_client: AsyncIOMotorClient[dict[str, Any]],
) -> AsyncIterator[tuple[AsyncIOMotorClient[dict[str, Any]], str, MongoQueueAdapter]]:
    """A uniquely named database + collection, for isolation assertions."""
    from backend.queue.mongo.ids import new_job_id

    db_name = f"{_TEST_DB}_{new_job_id()[:8]}"
    collection = f"worker_jobs_{new_job_id()[:6]}"
    database = mongo_client[db_name]
    queue = MongoQueueAdapter(database, collection_name=collection)
    await queue.ensure_indexes()
    yield mongo_client, db_name, queue
    await mongo_client.drop_database(db_name)
