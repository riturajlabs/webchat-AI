"""Worker lifecycle tests: graceful shutdown releases browser, Mongo and Redis."""

import logging

from backend.core import redis as redis_module
from backend.core.database import MongoDB
from backend.services.ingestion import browser as browser_module
from backend.workers import app as worker_app


async def test_shutdown_closes_browser_mongo_and_redis(monkeypatch) -> None:
    closed: list[str] = []

    async def close_browser() -> None:
        closed.append("browser")

    async def close_mongo() -> None:
        closed.append("mongo")

    async def close_redis() -> None:
        closed.append("redis")

    monkeypatch.setattr(worker_app, "close_browser", close_browser)
    monkeypatch.setattr(MongoDB, "close", close_mongo)
    monkeypatch.setattr(worker_app, "close_redis", close_redis)

    await worker_app.shutdown({})

    assert closed == ["browser", "mongo", "redis"]


async def test_shutdown_tolerates_missing_resources(monkeypatch) -> None:
    monkeypatch.setattr(MongoDB, "_client", None)
    monkeypatch.setattr(redis_module, "_redis", None)
    monkeypatch.setattr(browser_module, "_browser", None)
    monkeypatch.setattr(browser_module, "_playwright", None)

    await worker_app.shutdown({})


async def test_shutdown_survives_cleanup_failures(monkeypatch, caplog) -> None:
    closed: list[str] = []

    async def close_browser() -> None:
        raise RuntimeError("browser teardown failed")

    async def close_mongo() -> None:
        closed.append("mongo")

    async def close_redis() -> None:
        raise RuntimeError("redis teardown failed")

    monkeypatch.setattr(worker_app, "close_browser", close_browser)
    monkeypatch.setattr(MongoDB, "close", close_mongo)
    monkeypatch.setattr(worker_app, "close_redis", close_redis)

    with caplog.at_level(logging.ERROR, logger="webchat_ai"):
        await worker_app.shutdown({})

    assert closed == ["mongo"]
    assert "Playwright browser" in caplog.text
    assert "Redis client" in caplog.text
