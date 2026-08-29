"""Tests for health endpoints (Phase 14.7)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


def _client() -> TestClient:
    from backend.main import create_app
    return TestClient(create_app(), raise_server_exceptions=False)


class TestHealthLive:
    def test_returns_200(self) -> None:
        client = _client()
        resp = client.get("/api/health/live")
        assert resp.status_code == 200

    def test_body_has_status_alive(self) -> None:
        client = _client()
        resp = client.get("/api/health/live")
        data = resp.json()
        assert data["status"] == "alive"
        assert "version" in data
        assert "environment" in data

    def test_always_succeeds_without_io(self) -> None:
        """Liveness probe must not depend on MongoDB or Redis."""
        client = _client()
        resp = client.get("/api/health/live")
        assert resp.status_code == 200


class TestHealthReady:
    @patch("backend.api.routes.health.MongoDB.ping", new_callable=AsyncMock, return_value=True)
    @patch("backend.api.routes.health.ping_redis", new_callable=AsyncMock, return_value=True)
    def test_healthy_returns_200(self, _redis: AsyncMock, _mongo: AsyncMock) -> None:
        client = _client()
        resp = client.get("/api/health/ready")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ready"

    @patch("backend.api.routes.health.MongoDB.ping", new_callable=AsyncMock, return_value=False)
    @patch("backend.api.routes.health.ping_redis", new_callable=AsyncMock, return_value=True)
    def test_db_down_returns_503(self, _redis: AsyncMock, _mongo: AsyncMock) -> None:
        client = _client()
        resp = client.get("/api/health/ready")
        assert resp.status_code == 503
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["checks"]["database"] is False

    @patch("backend.api.routes.health.MongoDB.ping", new_callable=AsyncMock, return_value=True)
    @patch("backend.api.routes.health.ping_redis", new_callable=AsyncMock, return_value=False)
    def test_redis_down_returns_503(self, _redis: AsyncMock, _mongo: AsyncMock) -> None:
        client = _client()
        resp = client.get("/api/health/ready")
        assert resp.status_code == 503
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["checks"]["redis"] is False

    @patch("backend.api.routes.health.MongoDB.ping", new_callable=AsyncMock, return_value=False)
    @patch("backend.api.routes.health.ping_redis", new_callable=AsyncMock, return_value=False)
    def test_both_down_returns_503(self, _redis: AsyncMock, _mongo: AsyncMock) -> None:
        client = _client()
        resp = client.get("/api/health/ready")
        assert resp.status_code == 503


class TestHealthLegacy:
    @patch("backend.api.routes.health.MongoDB.ping", new_callable=AsyncMock, return_value=True)
    @patch("backend.api.routes.health.ping_redis", new_callable=AsyncMock, return_value=True)
    def test_always_200_even_if_deps_down(self, _redis: AsyncMock, _mongo: AsyncMock) -> None:
        client = _client()
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    @patch("backend.api.routes.health.MongoDB.ping", new_callable=AsyncMock, return_value=False)
    @patch("backend.api.routes.health.ping_redis", new_callable=AsyncMock, return_value=True)
    def test_reports_dependency_status(self, _redis: AsyncMock, _mongo: AsyncMock) -> None:
        client = _client()
        resp = client.get("/api/health")
        data = resp.json()
        assert data["checks"]["database"] is False
        assert data["checks"]["redis"] is True
        # Legacy /health always returns 200
        assert resp.status_code == 200
