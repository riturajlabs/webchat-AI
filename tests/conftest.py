"""Shared pytest configuration.

Tests are hermetic: they must never touch the real MongoDB. The FastAPI app's
lifespan runs `MongoDB.init_indexes()` on startup and the default service
dependencies build repositories from `MongoDB.db()`, so the shared client is
replaced with stubs - dependency graphs construct cleanly, but the moment
anything actually queries a collection it raises instead of hitting a live
cluster (the lifespan already tolerates startup failures). The MongoDB URI is
also overridden to an unreachable endpoint as a belt-and-suspenders guard, and
driver loggers are silenced to WARNING so DEBUG logging (e.g. `DEBUG=true` in
.env) cannot flood the suite.
"""

import logging
from collections.abc import Iterator

import pytest
from backend.core.config import get_settings
from backend.core.database import MongoDB

_LOUD_DB_LOGGERS = ("pymongo", "motor", "gridfs")


class _NoopCollection:
    """Any collection attribute access raises: a real query is a test bug."""

    def __getattr__(self, _name: str) -> None:
        raise RuntimeError("MongoDB is disabled in tests; use fakes.")


class _NoopDb:
    """`db["collection"]` yields a stub collection; direct attrs raise."""

    def __getitem__(self, _name: str) -> _NoopCollection:
        return _NoopCollection()

    def __getattr__(self, _name: str) -> None:
        raise RuntimeError("MongoDB is disabled in tests; use fakes.")


class _NoopClient:
    """`client[db]` yields a stub db; direct attrs raise (e.g. health pings)."""

    def __getitem__(self, _name: str) -> _NoopDb:
        return _NoopDb()

    def __getattr__(self, _name: str) -> None:
        raise RuntimeError("MongoDB is disabled in tests; use fakes.")


@pytest.fixture(autouse=True)
def _hermetic_infrastructure(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Keep tests off the network: stubbed MongoDB, no driver log spam."""
    monkeypatch.setenv("MONGODB_SERVER_SELECTION_TIMEOUT_MS", "1000")
    monkeypatch.setenv("MONGODB_URI", "mongodb://127.0.0.1:1")
    get_settings.cache_clear()

    monkeypatch.setattr(MongoDB, "client", staticmethod(lambda: _NoopClient()))

    for name in _LOUD_DB_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    yield

    get_settings.cache_clear()
