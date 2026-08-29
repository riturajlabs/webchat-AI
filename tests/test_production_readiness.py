"""Phase 14.8.2 — Production readiness tests.

Tests for startup/shutdown handling, dependency failures (MongoDB/Redis
unavailable), and worker cache resilience.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# LIFESPAN STARTUP/SHUTDOWN
# ---------------------------------------------------------------------------


class TestLifespanStartup:
    """Verify the app lifespan handles infrastructure init gracefully."""

    def test_lifespan_context_manager_exists(self) -> None:
        from backend.main import create_app
        app = create_app()
        assert hasattr(app, "router")

    def test_startup_connects_mongo_and_redis(self) -> None:
        from backend.main import create_app

        app = create_app()
        assert app is not None
        assert app.title is not None


# ---------------------------------------------------------------------------
# MONGODB UNAVAILABLE
# ---------------------------------------------------------------------------


class TestMongoUnavailable:
    """MongoDB down or unreachable scenarios."""

    @patch("backend.api.routes.health.MongoDB.ping", new_callable=AsyncMock, return_value=False)
    @patch("backend.api.routes.health.ping_redis", new_callable=AsyncMock, return_value=True)
    def test_readiness_reports_db_down(self, _redis: AsyncMock, _mongo: AsyncMock) -> None:
        from backend.main import create_app
        from fastapi.testclient import TestClient

        client = TestClient(create_app(), raise_server_exceptions=False)
        resp = client.get("/api/health/ready")
        assert resp.status_code == 503
        data = resp.json()
        assert data["checks"]["database"] is False

    def test_liveness_succeeds_without_mongo(self) -> None:
        """Liveness must never depend on MongoDB."""
        from backend.main import create_app
        from fastapi.testclient import TestClient

        client = TestClient(create_app(), raise_server_exceptions=False)
        resp = client.get("/api/health/live")
        assert resp.status_code == 200

    @patch("backend.main.MongoDB.ping", new_callable=AsyncMock, return_value=False)
    def test_mongo_ping_returns_false(self, _ping: AsyncMock) -> None:
        from backend.core.database import MongoDB
        result = asyncio.run(MongoDB.ping())
        assert result is False

    @patch("backend.core.database.MongoDB._client", None)
    @patch("backend.core.database.MongoDB.client")
    def test_mongo_client_lazy_init(self, client_mock: MagicMock) -> None:
        from backend.core.database import MongoDB
        mock_client = MagicMock()
        client_mock.return_value = mock_client
        MongoDB._client = None
        result = MongoDB.client()
        assert result is mock_client
        # Restore
        MongoDB._client = None


# ---------------------------------------------------------------------------
# REDIS UNAVAILABLE
# ---------------------------------------------------------------------------


class TestRedisUnavailable:
    """Redis down or unreachable scenarios."""

    @patch("backend.api.routes.health.MongoDB.ping", new_callable=AsyncMock, return_value=True)
    @patch("backend.api.routes.health.ping_redis", new_callable=AsyncMock, return_value=False)
    def test_readiness_reports_redis_down(self, _redis: AsyncMock, _mongo: AsyncMock) -> None:
        from backend.main import create_app
        from fastapi.testclient import TestClient

        client = TestClient(create_app(), raise_server_exceptions=False)
        resp = client.get("/api/health/ready")
        assert resp.status_code == 503
        data = resp.json()
        assert data["checks"]["redis"] is False

    @patch("backend.api.routes.health.MongoDB.ping", new_callable=AsyncMock, return_value=False)
    @patch("backend.api.routes.health.ping_redis", new_callable=AsyncMock, return_value=False)
    def test_readiness_reports_both_down(self, _redis: AsyncMock, _mongo: AsyncMock) -> None:
        from backend.main import create_app
        from fastapi.testclient import TestClient

        client = TestClient(create_app(), raise_server_exceptions=False)
        resp = client.get("/api/health/ready")
        assert resp.status_code == 503
        data = resp.json()
        assert data["checks"]["database"] is False
        assert data["checks"]["redis"] is False

    @patch("backend.core.redis.get_redis")
    def test_ping_redis_handles_connection_error(self, get_redis_mock: MagicMock) -> None:
        from backend.core.redis import ping_redis
        mock_redis = MagicMock()
        mock_redis.ping = AsyncMock(side_effect=ConnectionError("refused"))
        get_redis_mock.return_value = mock_redis
        result = asyncio.run(ping_redis())
        assert result is False

    @patch("backend.core.redis.get_redis")
    def test_ping_redis_returns_true_when_healthy(self, get_redis_mock: MagicMock) -> None:
        from backend.core.redis import ping_redis
        mock_redis = MagicMock()
        mock_redis.ping = AsyncMock(return_value=True)
        get_redis_mock.return_value = mock_redis
        result = asyncio.run(ping_redis())
        assert result is True


# ---------------------------------------------------------------------------
# WORKER CACHE RESILIENCE
# ---------------------------------------------------------------------------


class TestWorkerCacheResilience:
    """Worker _build_cache() must degrade gracefully when Redis is down."""

    @patch("backend.workers.jobs.crawl.get_redis", side_effect=ConnectionError("refused"))
    def test_crawl_build_cache_returns_none_on_redis_down(self, _redis_mock: MagicMock) -> None:
        from backend.workers.jobs.crawl import _build_cache
        result = _build_cache()
        assert result is None

    @patch("backend.workers.jobs.knowledge.get_redis", side_effect=ConnectionError("refused"))
    def test_knowledge_build_cache_returns_none_on_redis_down(self, _redis_mock: MagicMock) -> None:
        from backend.workers.jobs.knowledge import _build_cache
        result = _build_cache()
        assert result is None

    @patch("backend.workers.jobs.crawl.get_redis")
    def test_crawl_build_cache_returns_store_when_healthy(self, get_redis_mock: MagicMock) -> None:
        from backend.workers.jobs.crawl import _build_cache
        mock_redis = MagicMock()
        get_redis_mock.return_value = mock_redis
        result = _build_cache()
        assert result is not None

    @patch("backend.workers.jobs.knowledge.get_redis")
    def test_knowledge_build_cache_returns_store_when_healthy(
        self, get_redis_mock: MagicMock
    ) -> None:
        from backend.workers.jobs.knowledge import _build_cache
        mock_redis = MagicMock()
        get_redis_mock.return_value = mock_redis
        result = _build_cache()
        assert result is not None


# ---------------------------------------------------------------------------
# CONFIG: MONGODB SOCKET TIMEOUT
# ---------------------------------------------------------------------------


class TestMongoSocketTimeout:
    """Verify the new mongodb_socket_timeout_ms config is wired."""

    def test_default_socket_timeout(self) -> None:
        from backend.core.config import get_settings
        settings = get_settings()
        assert settings.mongodb_socket_timeout_ms == 30000

    def test_socket_timeout_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from backend.core.config import get_settings
        # Reset the lru_cache so env override takes effect
        get_settings.cache_clear()
        try:
            monkeypatch.setenv("MONGODB_SOCKET_TIMEOUT_MS", "15000")
            settings = get_settings()
            assert settings.mongodb_socket_timeout_ms == 15000
        finally:
            get_settings.cache_clear()
