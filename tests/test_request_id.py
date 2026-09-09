"""Tests for request ID middleware (Phase 14.7, SEC-M05)."""

from __future__ import annotations

from fastapi.testclient import TestClient

_INBOUND_UUID = "3f0c5f6a-2c1a-4d8e-9b7a-1a2b3c4d5e6f"


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

    def test_preserves_incoming_uuid_request_id(self) -> None:
        client = _client()
        resp = client.get("/api/health/live", headers={"X-Request-ID": _INBOUND_UUID})
        assert resp.status_code == 200
        assert resp.headers.get("x-request-id") == _INBOUND_UUID

    def test_rejects_malformed_incoming_request_id(self) -> None:
        # SEC-M05: attacker-supplied garbage must never enter log correlation.
        client = _client()
        for bad in (
            "my-custom-request-id-abc",
            "not-a-uuid",
            _INBOUND_UUID.upper(),
            f"{_INBOUND_UUID}extra",
        ):
            resp = client.get("/api/health/live", headers={"X-Request-ID": bad})
            assert resp.status_code == 400, f"expected 400 for {bad!r}"

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
