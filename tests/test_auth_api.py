"""End-to-end HTTP tests for the /api/auth endpoints using fake repositories."""

import pytest
from backend.api.deps import get_auth_service, require_role
from backend.core.config import get_settings
from backend.core.errors import AppError
from backend.core.security import create_password_reset_token
from backend.main import create_app
from fastapi import APIRouter, Depends, FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from tests.auth_helpers import VALID_PASSWORD, build_auth_env, token_from_url


@pytest.fixture
def client(monkeypatch):
    """A TestClient whose auth service is backed by in-memory fakes."""
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    get_settings.cache_clear()
    env = build_auth_env()
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: env.service
    with TestClient(app) as test_client:
        yield test_client, env
    get_settings.cache_clear()


REGISTER_PAYLOAD = {
    "name": "Alice",
    "email": "alice@example.com",
    "password": VALID_PASSWORD,
}


def test_register_sets_cookies_and_returns_tokens(client) -> None:
    test_client, _ = client
    response = test_client.post("/api/auth/register", json=REGISTER_PAYLOAD)

    assert response.status_code == 201
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["csrf_token"]
    assert body["user"]["email"] == "alice@example.com"
    assert body["user"]["role"] == "owner"
    assert body["user"]["email_verified"] is False

    set_cookie = response.headers.get_list("set-cookie")
    assert any("refresh_token=" in value and "HttpOnly" in value for value in set_cookie)
    assert any("csrf_token=" in value and "HttpOnly" not in value for value in set_cookie)


def test_register_duplicate_email_returns_409(client) -> None:
    test_client, _ = client
    assert test_client.post("/api/auth/register", json=REGISTER_PAYLOAD).status_code == 201
    response = test_client.post("/api/auth/register", json=REGISTER_PAYLOAD)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EMAIL_ALREADY_EXISTS"


def test_register_weak_password_returns_422(client) -> None:
    test_client, _ = client
    payload = dict(REGISTER_PAYLOAD, password="short")
    response = test_client.post("/api/auth/register", json=payload)
    assert response.status_code == 422


def test_login_success_returns_tokens(client) -> None:
    test_client, _ = client
    test_client.post("/api/auth/register", json=REGISTER_PAYLOAD)
    response = test_client.post(
        "/api/auth/login",
        json={"email": "alice@example.com", "password": VALID_PASSWORD},
    )
    assert response.status_code == 200
    assert response.json()["access_token"]


def test_login_wrong_password_returns_401(client) -> None:
    test_client, _ = client
    test_client.post("/api/auth/register", json=REGISTER_PAYLOAD)
    response = test_client.post(
        "/api/auth/login",
        json={"email": "alice@example.com", "password": "WrongPass1!"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_refresh_rotates_refresh_cookie_with_valid_csrf(client) -> None:
    test_client, _ = client
    test_client.post("/api/auth/register", json=REGISTER_PAYLOAD)
    csrf = test_client.cookies.get("csrf_token")
    assert csrf
    old_refresh = test_client.cookies.get("refresh_token")

    response = test_client.post(
        "/api/auth/refresh", headers={"X-CSRF-Token": csrf}
    )

    assert response.status_code == 200
    assert response.json()["access_token"]
    assert test_client.cookies.get("refresh_token") != old_refresh


def test_refresh_rejects_missing_csrf(client) -> None:
    test_client, _ = client
    test_client.post("/api/auth/register", json=REGISTER_PAYLOAD)
    response = test_client.post("/api/auth/refresh")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_FAILED"


def test_refresh_rejects_mismatched_csrf(client) -> None:
    test_client, _ = client
    test_client.post("/api/auth/register", json=REGISTER_PAYLOAD)
    response = test_client.post("/api/auth/refresh", headers={"X-CSRF-Token": "wrong-token"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_FAILED"


def test_logout_clears_cookies(client) -> None:
    test_client, _ = client
    test_client.post("/api/auth/register", json=REGISTER_PAYLOAD)
    csrf = test_client.cookies.get("csrf_token")

    response = test_client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf})

    assert response.status_code == 200
    assert response.json()["message"] == "Logged out."
    assert test_client.cookies.get("refresh_token") is None


def test_me_requires_bearer_token(client) -> None:
    test_client, _ = client
    assert test_client.get("/api/auth/me").status_code == 401

    access_token = test_client.post("/api/auth/register", json=REGISTER_PAYLOAD).json()[
        "access_token"
    ]
    response = test_client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert response.status_code == 200
    assert response.json()["email"] == "alice@example.com"


def test_verify_email_endpoint(client) -> None:
    test_client, env = client
    test_client.post("/api/auth/register", json=REGISTER_PAYLOAD)
    verification_token = token_from_url(env.mail.sent[0])

    response = test_client.post(
        "/api/auth/verify-email", json={"token": verification_token}
    )

    assert response.status_code == 200
    assert response.json()["message"] == "Email verified."
    user = next(iter(env.users.users.values()))
    assert user.email_verified is True


def test_forgot_password_endpoint_is_always_successful(client) -> None:
    test_client, env = client
    test_client.post("/api/auth/register", json=REGISTER_PAYLOAD)

    response = test_client.post(
        "/api/auth/forgot-password", json={"email": "alice@example.com"}
    )

    assert response.status_code == 200
    assert len(env.mail.sent) == 2
    assert env.mail.sent[-1].subject == "Reset your password"


def test_reset_password_endpoint_allows_new_password(client) -> None:
    test_client, env = client
    test_client.post("/api/auth/register", json=REGISTER_PAYLOAD)
    user = next(iter(env.users.users.values()))
    reset_token = create_password_reset_token(user.id, user.pwd_token_version)

    response = test_client.post(
        "/api/auth/reset-password",
        json={"token": reset_token, "new_password": "NewStr0ng!Pass"},
    )

    assert response.status_code == 200
    assert user.pwd_token_version == 1
    login = test_client.post(
        "/api/auth/login",
        json={"email": "alice@example.com", "password": "NewStr0ng!Pass"},
    )
    assert login.status_code == 200


# --------------------------------------------------------------------- RBAC


def _role_guard_app(env) -> FastAPI:
    """A minimal app exposing role-guarded routes backed by `env` fakes."""

    def _handler(_: FastAPI, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    router = APIRouter()

    @router.get("/guard/owner", dependencies=[Depends(require_role("owner"))])
    async def owner_only() -> dict[str, bool]:
        return {"ok": True}

    @router.get("/guard/admin", dependencies=[Depends(require_role("admin"))])
    async def admin_only() -> dict[str, bool]:
        return {"ok": True}

    @router.get("/guard/multi", dependencies=[Depends(require_role("owner", "admin"))])
    async def multi_role() -> dict[str, bool]:
        return {"ok": True}

    app = FastAPI()
    app.dependency_overrides[get_auth_service] = lambda: env.service
    app.add_exception_handler(AppError, _handler)
    app.include_router(router)
    return app


def test_require_role_allows_authorized_role(client) -> None:
    test_client, env = client
    access_token = test_client.post("/api/auth/register", json=REGISTER_PAYLOAD).json()[
        "access_token"
    ]
    headers = {"Authorization": f"Bearer {access_token}"}

    with TestClient(_role_guard_app(env)) as guard:
        assert guard.get("/guard/owner", headers=headers).status_code == 200
        assert guard.get("/guard/multi", headers=headers).status_code == 200


def test_require_role_forbids_unauthorized_role(client) -> None:
    test_client, env = client
    access_token = test_client.post("/api/auth/register", json=REGISTER_PAYLOAD).json()[
        "access_token"
    ]
    headers = {"Authorization": f"Bearer {access_token}"}

    with TestClient(_role_guard_app(env)) as guard:
        response = guard.get("/guard/admin", headers=headers)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "FORBIDDEN"


def test_require_role_requires_authentication(client) -> None:
    _, env = client
    with TestClient(_role_guard_app(env)) as guard:
        assert guard.get("/guard/owner").status_code == 401
        assert guard.get("/guard/admin").status_code == 401
