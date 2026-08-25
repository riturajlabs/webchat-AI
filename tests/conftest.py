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
import os
from collections.abc import Iterator

import pytest
from backend.core.config import get_settings
from backend.core.database import MongoDB

_LOUD_DB_LOGGERS = ("pymongo", "motor", "gridfs")

# Snapshot of ``os.environ`` captured once at session start so every test can
# be restored to a known-clean environment, even if a test file (or import-
# time side effect) mutated ``os.environ`` directly.
_original_env: dict[str, str] = {}


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


@pytest.fixture(autouse=True, scope="session")
def _snapshot_env() -> None:
    """Capture ``os.environ`` once before any test runs."""
    global _original_env  # noqa: PLW0603
    _original_env = os.environ.copy()


@pytest.fixture(autouse=True)
def _hermetic_infrastructure(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Keep tests off the network: stubbed MongoDB, no driver log spam."""
    # Restore the clean env snapshot before setting test-specific vars so that
    # pollution from import-time side effects (e.g. `_load_dev_env()` in a
    # test module) cannot leak between tests.
    os.environ.clear()
    os.environ.update(_original_env)

    monkeypatch.setenv("MONGODB_SERVER_SELECTION_TIMEOUT_MS", "1000")
    monkeypatch.setenv("MONGODB_URI", "mongodb://127.0.0.1:1")
    get_settings.cache_clear()

    # Reset the MongoDB class-level singleton so no stale client leaks across
    # tests (belt-and-suspenders alongside the ``monkeypatch.setattr`` below).
    MongoDB._client = None  # noqa: SLF001
    monkeypatch.setattr(MongoDB, "client", staticmethod(lambda: _NoopClient()))

    # Reset the Redis module-level singleton so no stale connection leaks.
    import backend.core.redis as _redis_mod

    _redis_mod._redis = None  # noqa: SLF001

    # Reset the crawl-events Redis singleton.
    import backend.core.crawl_events as _crawl_events_mod

    _crawl_events_mod._pubsub_redis = None  # noqa: SLF001

    # Reset the shared httpx client for OpenAI-compatible providers.
    import backend.ai.providers.openai_compat as _oai_mod

    _oai_mod._shared_client = None  # noqa: SLF001

    # Reset the process-global AI provider circuit breakers (Phase 4): state
    # must never leak between tests, or a provider tripped in one test would
    # be silently skipped in another.
    import backend.ai.circuit_breaker as _circuit_mod

    _circuit_mod.reset_circuit_breakers()

    # Clear the mail-service LRU cache so a stale provider (e.g. Resend)
    # created in a prior test with polluted env does not survive.
    from backend.services.mail import get_mail_service

    get_mail_service.cache_clear()

    for name in _LOUD_DB_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    yield

    get_settings.cache_clear()
    get_mail_service.cache_clear()
