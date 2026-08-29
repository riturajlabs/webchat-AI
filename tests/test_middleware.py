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


# --- Phase 14.3: RequestBodyLimitMiddleware ---


def _build_limit_client(max_bytes: int = 1024) -> tuple[FastAPI, TestClient]:
    app = FastAPI()

    @app.post("/echo")
    async def echo() -> dict[str, str]:
        return {"ok": "true"}

    @app.get("/echo")
    async def echo_get() -> dict[str, str]:
        return {"ok": "true"}

    from backend.api.middleware import RequestBodyLimitMiddleware

    app.add_middleware(RequestBodyLimitMiddleware, max_bytes=max_bytes)
    return app, TestClient(app)


def test_request_within_limit_accepted() -> None:
    _, client = _build_limit_client(max_bytes=1024)
    response = client.post("/echo", content=b"x" * 512)
    assert response.status_code == 200


def test_request_exceeding_limit_rejected() -> None:
    _, client = _build_limit_client(max_bytes=1024)
    response = client.post("/echo", content=b"x" * 2048)
    assert response.status_code == 413


def test_request_exact_limit_accepted() -> None:
    _, client = _build_limit_client(max_bytes=1024)
    response = client.post("/echo", content=b"x" * 1024)
    assert response.status_code == 200


def test_get_request_skips_body_limit() -> None:
    _, client = _build_limit_client(max_bytes=10)
    response = client.get("/echo")
    assert response.status_code == 200


def test_request_without_content_length_accepted() -> None:
    _, client = _build_limit_client(max_bytes=10)
    response = client.post("/echo", content=b"")
    assert response.status_code == 200


# --- Phase 14.4: AuthCacheHeadersMiddleware ---


def _build_auth_client() -> tuple[FastAPI, TestClient]:
    app = FastAPI()

    @app.post("/api/auth/login")
    async def login() -> dict[str, str]:
        return {"ok": "true"}

    @app.get("/api/auth/me")
    async def me() -> dict[str, str]:
        return {"ok": "true"}

    @app.get("/other")
    async def other() -> dict[str, str]:
        return {"ok": "true"}

    from backend.api.middleware import AuthCacheHeadersMiddleware

    app.add_middleware(AuthCacheHeadersMiddleware)
    return app, TestClient(app)


def test_auth_login_response_has_no_store_cache() -> None:
    _, client = _build_auth_client()
    response = client.post("/api/auth/login")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"


def test_auth_me_response_has_no_store_cache() -> None:
    _, client = _build_auth_client()
    response = client.get("/api/auth/me")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"


def test_non_auth_route_no_extra_cache_headers() -> None:
    _, client = _build_auth_client()
    response = client.get("/other")
    assert "cache-control" not in response.headers
