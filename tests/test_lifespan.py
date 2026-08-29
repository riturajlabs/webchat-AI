"""API lifespan reliability tests (Phase 14.8.2).

Verify FastAPI startup/shutdown lifecycle:
  * startup runs index init + vector validation,
  * shutdown releases MongoDB and Redis,
  * startup tolerates MongoDB being unavailable (degrades gracefully),
  * startup fails fast on an incompatible vector-dimension config,
  * shutdown still runs cleanup when a closer raises.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from backend.main import VectorConfigurationError, create_app
from fastapi.testclient import TestClient


def _record() -> AsyncMock:
    mock: AsyncMock = AsyncMock()
    return mock


def test_lifespan_runs_startup_and_shutdown_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    init_indexes = _record()
    close_mongo = _record()
    close_redis = _record()
    validate = _record()

    monkeypatch.setattr("backend.core.database.MongoDB.init_indexes", init_indexes)
    monkeypatch.setattr("backend.main._validate_vector_dimensions", validate)
    monkeypatch.setattr("backend.core.database.MongoDB.close", close_mongo)
    monkeypatch.setattr("backend.main.close_redis", close_redis)

    with TestClient(create_app()):
        pass

    init_indexes.assert_awaited_once()
    validate.assert_awaited_once()
    close_mongo.assert_awaited_once()
    close_redis.assert_awaited_once()


def test_lifespan_tolerates_mongo_unavailable_at_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Startup must not crash when MongoDB is unreachable; shutdown still runs."""

    async def boom() -> None:
        raise RuntimeError("mongo down")

    close_mongo = _record()
    close_redis = _record()
    validate = _record()

    monkeypatch.setattr("backend.core.database.MongoDB.init_indexes", boom)
    monkeypatch.setattr("backend.main._validate_vector_dimensions", validate)
    monkeypatch.setattr("backend.core.database.MongoDB.close", close_mongo)
    monkeypatch.setattr("backend.main.close_redis", close_redis)

    # Entering the context must not raise even though init_indexes failed.
    with TestClient(create_app()):
        pass

    close_mongo.assert_awaited_once()
    close_redis.assert_awaited_once()


def test_lifespan_fails_fast_on_vector_dimension_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An incompatible vector-dimension config must abort startup."""
    init_indexes = _record()
    validate = AsyncMock(side_effect=VectorConfigurationError("dim mismatch"))

    monkeypatch.setattr("backend.core.database.MongoDB.init_indexes", init_indexes)
    monkeypatch.setattr("backend.main._validate_vector_dimensions", validate)

    with pytest.raises(VectorConfigurationError):
        with TestClient(create_app()):
            pass


def test_lifespan_shutdown_survives_cleanup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failing closer must not prevent the other closers from running."""
    init_indexes = _record()
    validate = _record()
    close_mongo = AsyncMock(side_effect=RuntimeError("mongo close failed"))
    close_redis = _record()

    monkeypatch.setattr("backend.core.database.MongoDB.init_indexes", init_indexes)
    monkeypatch.setattr("backend.main._validate_vector_dimensions", validate)
    monkeypatch.setattr("backend.core.database.MongoDB.close", close_mongo)
    monkeypatch.setattr("backend.main.close_redis", close_redis)

    with TestClient(create_app()):
        pass

    close_mongo.assert_awaited_once()
    close_redis.assert_awaited_once()
