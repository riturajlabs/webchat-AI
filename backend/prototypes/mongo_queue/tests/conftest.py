"""Prototype test fixtures.

Connects to the ISOLATED prototype mongod (default 127.0.0.1:27019 - a
dedicated ephemeral instance, never production Atlas and never the dev docker
stack). The collection is emptied before and dropped after every test so
prototype tests cannot interfere with anything else.

Override the endpoint via ``PROTOTYPE_MONGO_URI`` if the test runner must use
a different isolated instance.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any

import pytest
from backend.prototypes.mongo_queue.config import (
    DEFAULT_MONGO_URI,
    QueueConfig,
)
from backend.prototypes.mongo_queue.queue import MongoQueue
from motor.motor_asyncio import AsyncIOMotorClient

Prototype = tuple[AsyncIOMotorClient[Any], MongoQueue]


def _prototype_uri() -> str:
    return os.environ.get("PROTOTYPE_MONGO_URI", DEFAULT_MONGO_URI)


@pytest.fixture
async def mongo_client() -> AsyncIterator[AsyncIOMotorClient[Any]]:
    client: AsyncIOMotorClient[Any] = AsyncIOMotorClient(
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
async def queue(mongo_client: AsyncIOMotorClient[Any]) -> AsyncIterator[MongoQueue]:
    config = QueueConfig()
    database = mongo_client[config.db_name]
    await database.drop_collection(config.collection_name)
    q = MongoQueue(database, config)
    await q.ensure_indexes()
    yield q
    await database.drop_collection(config.collection_name)