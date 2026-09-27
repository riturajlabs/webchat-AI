"""Deterministic mail idempotency keys (Phase 17A).

Phase 15/16 proved the queue-independent duplicate-delivery risk: under an
at-least-once queue, a crash *after* the provider accepted the send but
*before* the queue completion is written causes a second delivery on re-run.
The queue cannot fix this; only the provider can, via an idempotency key.

The production provider is Resend (``get_mail_service()``), which accepts an
``Idempotency-Key`` per request with a **24-hour** retention window and a
**256-character** maximum (verified against the Resend API reference and the
installed SDK during Phase 16).

This module is the *integration abstraction* only:

* it computes a deterministic key from the message content,
* it never sends anything, never imports the mail service, and never touches a
  provider SDK, so it is fully testable offline;
* ``backend/workers/jobs/email.py`` is deliberately **not** modified in Phase
  17A - see the report's known limitations. Production adoption is a Phase 17B
  change, made once it can be exercised against a real provider sandbox.

Key shape
---------
``email:<tenant_id>:<sha256(canonical content)>``  (Phase 17A - the content key)

Phase 17B.1 replaces this with the **delivery key**:

``email:<tenant_id>:<delivery_id>``

Why the content key had to go
-----------------------------
Hashing the rendered message makes two *different* logical deliveries collide:
a user who requests two password resets, or a test that sends the same
deterministic body twice, produce byte-identical content and therefore one key.
The second send is then suppressed as a "duplicate" and the user never gets the
email they asked for. The current auth flows only escape this by accident -
their JWTs carry a fresh ``jti``, so the content happens to differ - which makes
it a latent bug that only fires for any future template with a fixed body.

The delivery key removes the class of bug rather than the instance. The key is
derived from an identity minted **once per enqueue** and carried in the payload,
so:

* every retry, re-delivery and worker reclaim reuses the same key by
  construction (that is the deduplication we want);
* two enqueues are two logical deliveries and get two keys, so a legitimate
  repeat send is never suppressed;
* a key can no longer be influenced by recipient, subject or body, so no
  message content can cause one delivery to suppress another.

``build_idempotency_key`` is retained for the falsification tests that prove the
old content-derived behaviour was unsafe, and ``message_digest`` is still used to
store a non-identifying content fingerprint on the delivery record for
debugging. Neither is used on the production send path any more.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from typing import Any, Final

from backend.core.privacy import redact_secret_key

#: Resend rejects an Idempotency-Key longer than this (Phase 16, VERIFIED).
RESEND_MAX_IDEMPOTENCY_KEY_LENGTH: Final[int] = 256

#: The fields that define a logical email, in canonical (sorted) order.
CANONICAL_FIELDS: Final[tuple[str, ...]] = ("to", "subject", "text", "html")

KEY_PREFIX: Final[str] = "email:"


def new_delivery_id() -> str:
    """Mint the identity of one logical delivery.

    Called exactly once per ``enqueue_email``, and the result is persisted in
    the queue payload, so every later attempt at that delivery - retry, lease
    reclaim, duplicate execution - reuses it and cannot fork into two keys.
    Random (not content-derived) on purpose: the identity must be independent of
    what is sent, so that two sends of identical content are still two
    deliveries.
    """
    return uuid.uuid4().hex


def new_attempt_token() -> str:
    """Mint a token identifying one concrete *attempt* at a delivery.

    Distinct from :func:`new_delivery_id`: the delivery is the logical thing and
    persists across attempts, while the attempt token fences concurrent
    executions so a slow one cannot overwrite the outcome recorded by another.
    """
    return uuid.uuid4().hex


def build_delivery_key(tenant_id: str, delivery_id: str) -> str:
    """Return the provider idempotency key for one logical delivery.

    Scoped by tenant so one tenant's key can never suppress another tenant's
    mail, and derived from the delivery identity so content can never influence
    it. Length is asserted against
    :data:`RESEND_MAX_IDEMPOTENCY_KEY_LENGTH` so an unexpectedly long tenant id
    fails loudly at the enqueue site rather than being rejected by the provider
    at send time.
    """
    if not tenant_id:
        raise ValueError("tenant_id is required to build a mail idempotency key")
    if not delivery_id:
        raise ValueError("delivery_id is required to build a mail idempotency key")
    key = f"{KEY_PREFIX}{tenant_id}:{delivery_id}"
    if len(key) > RESEND_MAX_IDEMPOTENCY_KEY_LENGTH:
        raise ValueError(
            f"mail idempotency key is {len(key)} characters, over Resend's "
            f"{RESEND_MAX_IDEMPOTENCY_KEY_LENGTH}-character maximum"
        )
    return key


def canonical_message(
    *,
    to: str,
    subject: str,
    text: str,
    html: str,
    extra: Mapping[str, Any] | None = None,
) -> str:
    """Return the stable canonical string hashed into an idempotency key.

    Uses ``json.dumps`` with sorted keys and fixed separators so the encoding
    cannot drift with dict insertion order or whitespace. ``extra`` exists so a
    caller can fold in a further stable discriminator (e.g. a template name)
    without changing the hashing contract; it is hashed with sorted keys too.
    """
    body: dict[str, Any] = {"to": to, "subject": subject, "text": text, "html": html}
    if extra:
        body["extra"] = {str(k): extra[k] for k in sorted(extra)}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def message_digest(canonical: str) -> str:
    """Return the sha256 hex digest of a canonical message string."""
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_idempotency_key(
    tenant_id: str,
    *,
    to: str,
    subject: str,
    text: str,
    html: str,
    extra: Mapping[str, Any] | None = None,
) -> str:
    """Return the *content-derived* key from Phase 17A (legacy, unsent).

    Superseded by :func:`build_delivery_key` and deliberately kept: it is the
    behaviour Phase 17B.1 proved unsafe, so the falsification tests still build
    it to demonstrate that identical content yields one colliding key. Nothing on
    the production send path calls this.
    """
    if not tenant_id:
        raise ValueError("tenant_id is required to build a mail idempotency key")
    digest = message_digest(
        canonical_message(to=to, subject=subject, text=text, html=html, extra=extra)
    )
    key = f"{KEY_PREFIX}{tenant_id}:{digest}"
    if len(key) > RESEND_MAX_IDEMPOTENCY_KEY_LENGTH:
        raise ValueError(
            f"mail idempotency key is {len(key)} characters, over Resend's "
            f"{RESEND_MAX_IDEMPOTENCY_KEY_LENGTH}-character maximum"
        )
    return key


def key_for_payload(tenant_id: str, payload: Mapping[str, Any]) -> str:
    """Build the legacy content key from a ``send_email`` queue payload.

    Superseded by :func:`key_for_delivery`; retained for the falsification
    tests only.

    Raises ``KeyError`` for a payload missing a canonical field, which is the
    same failure ``registry.validate_payload`` rejects at enqueue time - the
    helper never invents a default for a missing recipient or body.
    """
    missing = [field for field in CANONICAL_FIELDS if field not in payload]
    if missing:
        raise KeyError(f"send_email payload is missing required fields: {sorted(missing)}")
    return build_idempotency_key(
        tenant_id,
        to=str(payload["to"]),
        subject=str(payload["subject"]),
        text=str(payload["text"]),
        html=str(payload["html"]),
    )


def key_for_delivery(tenant_id: str, delivery_id: str) -> str:
    """Production entry point: the key for one logical delivery.

    The worker calls this with the ``delivery_id`` carried in the payload, so a
    reclaimed or retried job reconstructs the identical key without needing any
    state, and content never participates in it.
    """
    return build_delivery_key(tenant_id, delivery_id)


def redact_key(key: str, *, keep: int = 8) -> str:
    """Return a log-safe rendering of a key.

    The key embeds a tenant id, so logs get the namespace prefix and the digest
    tail only - never the tenant segment. Delegates to
    :func:`backend.core.privacy.redact_secret_key` so the mail provider can use
    exactly this redaction without depending on the queue layer.
    """
    if ":" not in key:
        # Malformed key: no namespace segment to preserve, but the caller must
        # still see which kind of key this was.
        return f"{KEY_PREFIX}<redacted>"
    return redact_secret_key(key, keep=keep)


__all__ = [
    "CANONICAL_FIELDS",
    "KEY_PREFIX",
    "RESEND_MAX_IDEMPOTENCY_KEY_LENGTH",
    "build_delivery_key",
    "build_idempotency_key",
    "canonical_message",
    "key_for_delivery",
    "key_for_payload",
    "message_digest",
    "new_attempt_token",
    "new_delivery_id",
    "redact_key",
]
