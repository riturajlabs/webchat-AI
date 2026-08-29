"""Tests for request ID middleware (Phase 14.7)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _client() -> TestClient:
    from backend.main import create_app
    return TestClient(create_app(), raise_server_exceptions=False)


class TestRequestIdMiddleware:
    def test_generates_request_id_when_missing(self) -> None:
        client = _client()
        resp = client.get("/api/health/live")
        assert resp.status_code == 200
        rid = resp.headers.get("x-request-id")
        assert rid is not None
        assert len(rid) > 0

    def test_preserves_incoming_request_id(self) -> None:
        client = _client()
        incoming = "my-custom-request-id-abc"
        resp = client.get("/api/health/live", headers={"X-Request-ID": incoming})
        assert resp.status_code == 200
        assert resp.headers.get("x-request-id") == incoming

    def test_response_always_contains_header(self) -> None:
        client = _client()
        for path in ("/api/health/live", "/api/health", "/api/health/ready"):
            resp = client.get(path)
            assert "x-request-id" in resp.headers, f"Missing header for {path}"

    def test_different_requests_get_different_ids(self) -> None:
        client = _client()
        r1 = client.get("/api/health/live")
        r2 = client.get("/api/health/live")
        assert r1.headers["x-request-id"] != r2.headers["x-request-id"]
