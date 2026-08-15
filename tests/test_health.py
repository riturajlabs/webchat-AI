"""Health endpoint tests."""

import pytest
from backend.api.routes import health as health_module
from backend.core.config import get_settings
from backend.main import create_app
from fastapi.testclient import TestClient


def test_health_returns_ok() -> None:
    client = TestClient(create_app())
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "database" in body["checks"]
    assert "redis" in body["checks"]
    assert body["version"] == "0.1.0"
    assert "environment" in body


def test_health_live_returns_alive_without_dependency_io() -> None:
    # Liveness must not touch Mongo/Redis: a partition on either must not stall
    # the probe (orchestrators use this for restart decisions).
    client = TestClient(create_app())
    response = client.get("/api/health/live")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "alive"
    assert body["version"] == "0.1.0"


def test_health_ready_includes_service_info() -> None:
    client = TestClient(create_app())
    response = client.get("/api/health/ready")
    assert response.status_code in {200, 503}
    body = response.json()
    assert "version" in body
    assert "environment" in body


def test_health_ready_returns_503_when_dependencies_unavailable(monkeypatch) -> None:
    # Simulate both dependencies being down: the readiness probe must fail
    # closed with 503 rather than report 200 + "degraded".
    async def fake_ping_fail() -> bool:
        return False

    monkeypatch.setattr(health_module.MongoDB, "ping", fake_ping_fail)
    monkeypatch.setattr(health_module, "ping_redis", fake_ping_fail)

    client = TestClient(create_app())
    response = client.get("/api/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["database"] is False
    assert body["checks"]["redis"] is False


@pytest.mark.parametrize(
    ("database_ok", "redis_ok", "expected_status"),
    [
        (True, True, 200),
        (True, False, 503),
        (False, True, 503),
        (False, False, 503),
    ],
)
async def test_health_ready_status_by_dependency_state(
    monkeypatch, database_ok: bool, redis_ok: bool, expected_status: int
) -> None:
    async def fake_db_ping() -> bool:
        return database_ok

    async def fake_redis_ping() -> bool:
        return redis_ok

    monkeypatch.setattr(health_module.MongoDB, "ping", fake_db_ping)
    monkeypatch.setattr(health_module, "ping_redis", fake_redis_ping)

    client = TestClient(create_app())
    response = client.get("/api/health/ready")
    assert response.status_code == expected_status
    if expected_status == 200:
        assert response.json()["status"] == "ready"
    else:
        assert response.json()["status"] == "degraded"


def test_openapi_docs_disabled_by_default(monkeypatch) -> None:
    # No DEBUG: the default is debug=False so docs are disabled. Env vars
    # override the developer's .env, keeping this assertion hermetic.
    monkeypatch.setenv("DEBUG", "false")
    get_settings.cache_clear()
    client = TestClient(create_app())
    assert client.get("/api/docs").status_code == 404
    get_settings.cache_clear()


def test_openapi_docs_enabled_in_debug(monkeypatch) -> None:
    monkeypatch.setenv("DEBUG", "true")
    get_settings.cache_clear()
    client = TestClient(create_app())
    assert client.get("/api/docs").status_code in {200, 307}
    get_settings.cache_clear()
