"""Tests for backend.api.middleware (request ID + security headers)."""

import pytest
from backend.main import create_app
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _build_client() -> tuple[FastAPI, TestClient]:
    app = FastAPI()

    @app.get("/ping")
    async def ping() -> dict[str, str]:
        return {"ok": "true"}

    from backend.api.middleware import RequestIDMiddleware, SecurityHeadersMiddleware

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestIDMiddleware)
    return app, TestClient(app)


def test_response_includes_request_id() -> None:
    _, client = _build_client()
    response = client.get("/ping")
    assert response.status_code == 200
    assert "x-request-id" in response.headers
    assert response.headers["x-request-id"] != ""


def test_request_id_preserved_from_client() -> None:
    _, client = _build_client()
    response = client.get("/ping", headers={"X-Request-ID": "trace-42"})
    assert response.headers["x-request-id"] == "trace-42"


def test_security_headers_present() -> None:
    _, client = _build_client()
    response = client.get("/ping")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "default-src 'none'" in response.headers["content-security-policy"]
    assert response.headers["referrer-policy"] == "no-referrer"


def test_hsts_only_when_cookie_secure(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.core.config import Settings

    monkeypatch.setattr(
        "backend.api.middleware.get_settings",
        lambda: Settings(_env_file=None, cookie_secure=True),
    )
    _, client = _build_client()
    response = client.get("/ping")
    assert response.headers["strict-transport-security"] == ("max-age=63072000; includeSubDomains")

    monkeypatch.setattr(
        "backend.api.middleware.get_settings",
        lambda: Settings(_env_file=None, cookie_secure=False),
    )
    _, client = _build_client()
    response = client.get("/ping")
    assert "strict-transport-security" not in response.headers


def test_trusted_host_allowlist_accepts_known_host() -> None:
    app = FastAPI()

    @app.get("/ping")
    async def ping() -> dict[str, str]:
        return {"ok": "true"}

    from starlette.middleware.trustedhost import TrustedHostMiddleware

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["api.example.com", "localhost"])
    client = TestClient(app)

    assert client.get("/ping", headers={"Host": "api.example.com"}).status_code == 200
    assert client.get("/ping", headers={"Host": "localhost"}).status_code == 200
    assert client.get("/ping", headers={"Host": "evil.test"}).status_code == 400
    assert client.get("/ping", headers={"Host": ""}).status_code == 400


def test_create_app_rejects_unknown_host() -> None:
    # create_app wires TrustedHostMiddleware from effective_allowed_hosts();
    # the development default list only covers loopback + testserver, so an
    # unknown host must be rejected before any handler runs.
    client = TestClient(create_app())
    response = client.get("/api/health/live", headers={"Host": "evil.test"})
    assert response.status_code == 400
    response = client.get("/api/health/live", headers={"Host": "testserver"})
    assert response.status_code == 200
