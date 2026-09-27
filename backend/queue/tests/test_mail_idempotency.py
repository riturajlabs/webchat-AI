"""Deterministic mail idempotency keys (Phase 17A §18).

The keys are computed here, offline. Nothing in this module sends mail or
touches a provider SDK, so the tests are hermetic.
"""

from __future__ import annotations

import json

import pytest
from backend.queue.mail_idempotency import (
    CANONICAL_FIELDS,
    KEY_PREFIX,
    RESEND_MAX_IDEMPOTENCY_KEY_LENGTH,
    build_idempotency_key,
    canonical_message,
    key_for_payload,
    message_digest,
    redact_key,
)

_PAYLOAD = {"to": "a@b.c", "subject": "Welcome", "text": "hi", "html": "<p>hi</p>"}


def _key(**overrides: object) -> str:
    fields: dict[str, object] = {"to": "a@b.c", "subject": "S", "text": "T", "html": "<p>H</p>"}
    fields.update(overrides)
    return build_idempotency_key(
        "tenant-a", to=str(fields["to"]), subject=str(fields["subject"]),
        text=str(fields["text"]), html=str(fields["html"]),
    )


def test_key_shape_is_tenant_scoped_and_hashed() -> None:
    key = _key()
    assert key.startswith(f"{KEY_PREFIX}tenant-a:")
    digest = key.rsplit(":", 1)[1]
    assert len(digest) == 64
    canonical = canonical_message(to="a@b.c", subject="S", text="T", html="<p>H</p>")
    assert message_digest(canonical) == digest


def test_key_is_deterministic_across_calls() -> None:
    assert _key() == _key()


def test_key_is_deterministic_across_dict_ordering() -> None:
    """Dict insertion order must not change the key."""
    a = canonical_message(to="a@b.c", subject="S", text="T", html="<p>H</p>")
    b = canonical_message(html="<p>H</p>", text="T", subject="S", to="a@b.c")
    assert a == b


@pytest.mark.parametrize(
    "overrides",
    [
        {"to": "other@b.c"},
        {"subject": "Different"},
        {"text": "different"},
        {"html": "<p>different</p>"},
    ],
)
def test_any_content_change_changes_the_key(overrides: dict[str, object]) -> None:
    assert _key(**overrides) != _key()


def test_a_different_tenant_gets_a_different_key() -> None:
    """One tenant's key must never be able to suppress another tenant's mail."""
    a = build_idempotency_key("tenant-a", to="a@b.c", subject="S", text="T", html="H")
    b = build_idempotency_key("tenant-b", to="a@b.c", subject="S", text="T", html="H")
    assert a != b


def test_key_requires_a_tenant() -> None:
    with pytest.raises(ValueError, match="tenant_id"):
        build_idempotency_key("", to="a@b.c", subject="S", text="T", html="H")


def test_key_respects_the_provider_length_limit() -> None:
    """Resend rejects an Idempotency-Key over 256 characters (Phase 16)."""
    assert len(_key()) <= RESEND_MAX_IDEMPOTENCY_KEY_LENGTH
    with pytest.raises(ValueError, match="maximum"):
        build_idempotency_key("t" * 300, to="a@b.c", subject="S", text="T", html="H")


def test_key_carries_no_secret_or_timestamp() -> None:
    """A key derived from random or time-varying data would not deduplicate."""
    assert _key() == _key()
    source = json.loads(canonical_message(to="a@b.c", subject="S", text="T", html="H"))
    assert set(source) == {"to", "subject", "text", "html"}
    assert not any(char.isdigit() and "ts" in str(source) for char in source)


def test_extra_is_folded_in_deterministically() -> None:
    a = build_idempotency_key("t", to="a@b.c", subject="S", text="T", html="H",
                              extra={"template": "welcome"})
    b = build_idempotency_key("t", to="a@b.c", subject="S", text="T", html="H",
                              extra={"template": "welcome"})
    c = build_idempotency_key("t", to="a@b.c", subject="S", text="T", html="H",
                              extra={"template": "receipt"})
    assert a == b != c


# ----------------------------------------------------------------------
# payload entry point
# ----------------------------------------------------------------------


def test_key_for_payload_matches_the_canonical_fields() -> None:
    assert key_for_payload("tenant-a", _PAYLOAD) == build_idempotency_key(
        "tenant-a", to=_PAYLOAD["to"], subject=_PAYLOAD["subject"],
        text=_PAYLOAD["text"], html=_PAYLOAD["html"],
    )


def test_canonical_fields_match_the_email_payload_contract() -> None:
    """Must stay aligned with ``EmailMessage.to_payload()`` and the registry."""
    from backend.queue.registry import _EMAIL_PAYLOAD_FIELDS
    from backend.services.mail.base import EmailMessage

    assert set(CANONICAL_FIELDS) == set(_EMAIL_PAYLOAD_FIELDS)
    message = EmailMessage(to="a@b.c", subject="S", text="T", html="<p>H</p>")
    assert set(CANONICAL_FIELDS) <= set(message.to_payload())


def test_key_for_payload_never_invents_a_missing_field() -> None:
    incomplete = dict(_PAYLOAD)
    del incomplete["html"]
    with pytest.raises(KeyError):
        key_for_payload("tenant-a", incomplete)


def test_key_for_payload_requires_a_tenant() -> None:
    with pytest.raises(ValueError):
        key_for_payload("", _PAYLOAD)


# ----------------------------------------------------------------------
# redaction
# ----------------------------------------------------------------------


def test_redaction_hides_the_tenant() -> None:
    key = _key()
    redacted = redact_key(key)
    assert "tenant-a" not in redacted
    assert "<redacted>" in redacted
    assert redacted.endswith(key.rsplit(":", 1)[1][-8:])


def test_redaction_of_a_malformed_key_is_safe() -> None:
    assert redact_key("garbage") == "email:<redacted>"
