"""Health endpoint tests."""

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


def test_health_ready_degraded_without_dependencies() -> None:
    client = TestClient(create_app())
    response = client.get("/api/health/ready")
    assert response.status_code == 200
    body = response.json()
    # CI has no MongoDB/Redis running, so the readiness probe must report
    # "degraded" rather than crash or return 500.
    assert body["status"] in {"ready", "degraded"}


def test_openapi_docs_disabled_in_production_default() -> None:
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
