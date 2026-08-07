"""Tests for backend.api.middleware (request ID + security headers)."""

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
