"""HTTP-level helpers for building authenticated TestClient scenarios.

The email-verification gate (Sprint 1 P1) means a freshly registered account
cannot call authenticated endpoints until its email is verified. `register_verified`
registers and verifies in one call and returns bearer headers, so feature tests
stay focused on their endpoint rather than the verification flow.
"""

from backend.core.security import create_email_verification_token
from fastapi.testclient import TestClient

from tests.auth_helpers import VALID_PASSWORD


def register_verified_account(
    test_client: TestClient,
    *,
    name: str = "Alice",
    email: str,
    password: str = VALID_PASSWORD,
) -> dict:
    """Register a user, verify its email out-of-band, and return the body.

    The verification token is minted directly (the caller already holds the
    freshly registered user id), which keeps the helper independent of the
    mail transport while still exercising the real `/verify-email` endpoint.
    The returned body is the `/register` response (`access_token`, `csrf_token`,
    `user` with `id`/`tenant_id`, `role`).
    """
    response = test_client.post(
        "/api/auth/register",
        json={"name": name, "email": email, "password": password},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    user_id = body["user"]["id"]
    token = create_email_verification_token(user_id)
    verify = test_client.post("/api/auth/verify-email", json={"token": token})
    assert verify.status_code == 200, verify.text
    return body


def register_verified(
    test_client: TestClient,
    *,
    name: str = "Alice",
    email: str,
    password: str = VALID_PASSWORD,
) -> dict[str, str]:
    """Register + verify a user and return bearer headers for authenticated calls."""
    body = register_verified_account(
        test_client,
        name=name,
        email=email,
        password=password,
    )
    return {"Authorization": f"Bearer {body['access_token']}"}


__all__ = ["register_verified", "register_verified_account"]
