"""Widget-session JWT create/decode tests (Phase 8, ADR-004 §3.2)."""

import pytest
from backend.core.errors import InvalidTokenError, TokenExpiredError
from backend.core.security import (
    create_access_token,
    create_widget_session_token,
    decode_widget_session_token,
)


def test_create_and_decode_widget_session_token() -> None:
    token, ttl = create_widget_session_token(
        widget_id="widget-1",
        tenant_id="tenant-a",
        website_id="web-1",
        visitor_id="visitor-123",
    )
    assert ttl == 15 * 60
    claims = decode_widget_session_token(token)
    assert claims["widget_id"] == "widget-1"
    assert claims["tenant_id"] == "tenant-a"
    assert claims["website_id"] == "web-1"
    assert claims["visitor_id"] == "visitor-123"
    assert claims["token_type"] == "widget_session"
    assert claims["jti"]


def test_widget_session_token_allows_none_visitor() -> None:
    token, _ = create_widget_session_token(
        widget_id="widget-1",
        tenant_id="tenant-a",
        website_id="web-1",
        visitor_id=None,
    )
    assert decode_widget_session_token(token)["visitor_id"] is None


def test_widget_session_token_rejects_access_token() -> None:
    token, _ = create_access_token(sub="user-1", tenant_id="tenant-a", role="owner")
    with pytest.raises(InvalidTokenError):
        decode_widget_session_token(token)


def test_widget_session_token_rejects_tampered_signature() -> None:
    token, _ = create_widget_session_token(
        widget_id="widget-1",
        tenant_id="tenant-a",
        website_id="web-1",
        visitor_id=None,
    )
    with pytest.raises(InvalidTokenError):
        decode_widget_session_token(token + "tampered")


def test_widget_session_token_expires(monkeypatch) -> None:
    from datetime import timedelta

    from backend.core import security as security_module
    from backend.core.security import utcnow

    monkeypatch.setattr(
        security_module,
        "utcnow",
        lambda: utcnow() - timedelta(minutes=20),
    )
    token, _ = create_widget_session_token(
        widget_id="widget-1",
        tenant_id="tenant-a",
        website_id="web-1",
        visitor_id=None,
    )
    with pytest.raises(TokenExpiredError):
        decode_widget_session_token(token)
