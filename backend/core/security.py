"""Cryptographic primitives: password hashing, JWTs, opaque tokens, CSRF.

See docs/07-Architecture-Decisions.md ADR-003 for the token strategy.
"""

import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from backend.core.config import get_settings
from backend.core.errors import InvalidTokenError, TokenExpiredError

TokenPurpose = Literal["access", "email_verify", "password_reset", "widget_session"]

# ADR-003: Argon2id, memory 19 MiB, time 2, parallelism 1.
_argon2 = PasswordHasher(memory_cost=19 * 1024, time_cost=2, parallelism=1)

# SHA-256 for opaque refresh tokens (ADR-003: hashed in DB, never stored raw).
_SHA256 = hashlib.sha256

# Recognizable prefix for tenant-issued API keys (docs/05 §12). The full raw
# value is shown once at creation; only its hash is persisted (ADR-004).
API_KEY_PREFIX = "wc_"


def utcnow() -> datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(UTC)


def new_id() -> str:
    """Return a new UUID string used as a document identifier."""
    return str(uuid.uuid4())


def hash_password(password: str) -> str:
    """Hash a password with Argon2id."""
    return _argon2.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against an Argon2id hash. Never raises."""
    try:
        return _argon2.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def _encode(payload: dict[str, Any], expires_in_seconds: int) -> str:
    settings = get_settings()
    now = utcnow()
    token = {
        "iat": now,
        "exp": now + timedelta(seconds=expires_in_seconds),
        **payload,
    }
    return jwt.encode(token, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _decode(token: str, expected_purpose: TokenPurpose) -> dict[str, Any]:
    settings = get_settings()
    # `leeway` tolerates small clock skew between the node that minted the
    # token and the node verifying it (normal in distributed deployments), and
    # avoids spurious `ImmatureSignatureError`/`ExpiredSignatureError` at the
    # iat/exp second boundaries.
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "iat"]},
            leeway=timedelta(seconds=30),
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError("Token has expired.") from exc
    except jwt.PyJWTError as exc:
        raise InvalidTokenError("Token is invalid.") from exc
    if payload.get("token_type") != expected_purpose:
        raise InvalidTokenError("Token is invalid.")
    return payload


def create_access_token(sub: str, tenant_id: str, role: str) -> tuple[str, int]:
    """Create a short-lived access JWT (ADR-003 claims). Returns (token, ttl_s)."""
    settings = get_settings()
    ttl = settings.jwt_access_token_expire_minutes * 60
    payload = {
        "sub": sub,
        "tenant_id": tenant_id,
        "role": role,
        "token_type": "access",
        "jti": new_id(),
    }
    return _encode(payload, ttl), ttl


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate an access JWT, returning its claims."""
    return _decode(token, "access")


def create_email_verification_token(user_id: str) -> str:
    """Create the signed email-verification JWT (ADR-001)."""
    settings = get_settings()
    payload = {"sub": user_id, "token_type": "email_verify", "jti": new_id()}
    return _encode(payload, settings.email_verify_token_expire_minutes * 60)


def decode_email_verification_token(token: str) -> str:
    """Validate an email-verification JWT and return the user id."""
    return str(_decode(token, "email_verify")["sub"])


def create_password_reset_token(user_id: str, pwd_token_version: int) -> str:
    """Create the signed password-reset JWT (ADR-001, versioned)."""
    settings = get_settings()
    payload = {
        "sub": user_id,
        "token_type": "password_reset",
        "pwd_token_version": pwd_token_version,
        "jti": new_id(),
    }
    return _encode(payload, settings.password_reset_token_expire_minutes * 60)


def decode_password_reset_token(token: str) -> tuple[str, int]:
    """Validate a password-reset JWT; returns (user_id, token_version)."""
    payload = _decode(token, "password_reset")
    return str(payload["sub"]), int(payload["pwd_token_version"])


def create_widget_session_token(
    *,
    widget_id: str,
    tenant_id: str,
    website_id: str,
    visitor_id: str | None,
) -> tuple[str, int]:
    """Create a short-lived public widget-session JWT (Phase 8, ADR-004).

    The token is scoped to a single widget (and thus one tenant+website) and
    carries the anonymous visitor id so per-visitor rate limits and session
    continuity work without any cookie reaching the API (ADR-003 CSRF
    exemption). Returns (token, ttl_s).
    """
    settings = get_settings()
    ttl = settings.widget_session_token_minutes * 60
    payload = {
        "widget_id": widget_id,
        "tenant_id": tenant_id,
        "website_id": website_id,
        "visitor_id": visitor_id,
        "token_type": "widget_session",
        "jti": new_id(),
    }
    return _encode(payload, ttl), ttl


def decode_widget_session_token(token: str) -> dict[str, Any]:
    """Decode and validate a widget-session JWT, returning its claims."""
    return _decode(token, "widget_session")


def generate_refresh_token() -> str:
    """Return a 256-bit opaque refresh token (urlsafe base64)."""
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    """Return the SHA-256 hex digest stored in the database."""
    return _SHA256(token.encode("utf-8")).hexdigest()


def generate_api_key() -> str:
    """Return a new tenant-issued API key (docs/05 §12).

    The raw value is returned to the tenant exactly once; only its hash is
    stored so a DB leak never exposes usable secrets (ADR-004).
    """
    return f"{API_KEY_PREFIX}{secrets.token_urlsafe(32)}"


def hash_api_key(raw_key: str) -> str:
    """Return the SHA-256 hex digest persisted on the api_key document."""
    return _SHA256(raw_key.encode("utf-8")).hexdigest()


def generate_csrf_token() -> str:
    """Return a 192-bit CSRF token stored in a readable cookie."""
    return secrets.token_urlsafe(24)


def csrf_tokens_match(cookie: str, header: str) -> bool:
    """Constant-time comparison of the CSRF cookie and header values."""
    return hmac.compare_digest(cookie, header)
