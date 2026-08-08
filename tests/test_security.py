"""Security primitive tests: password hashing, JWTs, CSRF, purpose separation."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from backend.core.config import get_settings
from backend.core.errors import InvalidTokenError, TokenExpiredError
from backend.core.security import (
    create_access_token,
    create_email_verification_token,
    csrf_tokens_match,
    decode_access_token,
    decode_email_verification_token,
    generate_csrf_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)


def test_password_hash_roundtrip() -> None:
    password_hash = hash_password("Str0ng!Pass")
    assert password_hash != "Str0ng!Pass"
    assert verify_password("Str0ng!Pass", password_hash) is True
    assert verify_password("WrongPass1!", password_hash) is False
    assert verify_password("Str0ng!Pass", "not-a-hash") is False


def test_access_token_roundtrip() -> None:
    token, ttl = create_access_token("user-1", "tenant-1", "owner")
    assert ttl == 15 * 60
    claims = decode_access_token(token)
    assert claims["sub"] == "user-1"
    assert claims["tenant_id"] == "tenant-1"
    assert claims["role"] == "owner"
    assert claims["token_type"] == "access"
    assert claims["jti"]


def test_tampered_access_token_rejected() -> None:
    token, _ = create_access_token("user-1", "tenant-1", "owner")
    bad = token[:-4] + ("abcd" if token[-4:] != "abcd" else "wxyz")
    with pytest.raises(InvalidTokenError):
        decode_access_token(bad)


def test_expired_access_token_rejected() -> None:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": "user-1",
        "tenant_id": "tenant-1",
        "role": "owner",
        "token_type": "access",
        "jti": "jti-1",
        "iat": now - timedelta(hours=1),
        "exp": now - timedelta(minutes=30),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    with pytest.raises(TokenExpiredError):
        decode_access_token(token)


def test_token_purpose_is_separated() -> None:
    access, _ = create_access_token("user-1", "tenant-1", "owner")
    verify = create_email_verification_token("user-1")
    # An access token must not validate as an email-verification token.
    with pytest.raises(InvalidTokenError):
        decode_email_verification_token(access)
    assert decode_email_verification_token(verify) == "user-1"


def test_refresh_token_hash_is_deterministic() -> None:
    raw = generate_refresh_token()
    assert len(raw) >= 32
    assert hash_refresh_token(raw) == hash_refresh_token(raw)
    assert hash_refresh_token(raw) != raw


def test_csrf_tokens_match_is_constant_time() -> None:
    token = generate_csrf_token()
    assert csrf_tokens_match(token, token) is True
    assert csrf_tokens_match(token, "different") is False
    # Empty vs empty matches at the hmac level; the API dependency separately
    # rejects requests with a missing cookie or header.
    assert csrf_tokens_match("", "") is True


def test_password_policy() -> None:
    from backend.schemas.auth import validate_password_policy

    with pytest.raises(ValueError):
        validate_password_policy("short")
    with pytest.raises(ValueError):
        validate_password_policy("alllowercaseletters1")
    with pytest.raises(ValueError):
        validate_password_policy("AllLowercaseLetters")
    assert validate_password_policy("Str0ng!Pass") == "Str0ng!Pass"
