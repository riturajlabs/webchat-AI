"""Deterministic email idempotency keys + crash-scenario provider mocks (Phase 16).

Answers Q1/Q2 for the investigation:

- The production provider (Resend) natively supports an ``Idempotency-Key``
  request header. Official HTTP API docs: "Add an idempotency key to prevent
  duplicated emails" — keys are unique per request, expire after 24 hours, and
  are capped at 256 characters. The installed SDK (``resend`` 2.35.0) exposes
  this as ``Emails.SendOptions.idempotency_key``; its ``request.py`` maps it to
  the ``Idempotency-Key`` header for POSTs. So OPTION A is available on the
  existing free-path provider without any new paid service.
- A retry of the same logical email MUST send the SAME key, so the key is a
  hash of durable logical identity (tenant + rendered message), never a random
  UUID. Identical rendered content across attempts => identical key.
- Providers that do NOT honor idempotency still duplicate; the durable Mongo
  marker (OPTION B/D) remains the only total protection in that case.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from backend.prototypes.mongo_queue.ids import utcnow
from backend.prototypes.mongo_queue.sim_jobs import SendResult, SentEmail, send_email_handler
from backend.prototypes.mongo_queue.worker import JobContext

EMAIL_KEY_PREFIX = "email"


def email_logical_id(message: dict[str, Any]) -> str:
    """Deterministic content-level identity of a rendered email.

    Hashes (from, to, subject, text, html) so two retries of the *same* logical
    message collide, while a different message (different recipient/body/template
    render) yields a different id. No time/random component: determinism across
    retries is the entire point.
    """
    canonical = json.dumps(
        {
            "to": message.get("to", ""),
            "subject": message.get("subject", ""),
            "body": message.get("body", ""),
            "html": message.get("html", ""),
            "from": message.get("from", ""),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def email_idempotency_key(tenant_id: str, message: dict[str, Any]) -> str:
    """Deterministic idempotency key: ``email:<tenant_id>:<logical_id>``.

    Same tenant + same rendered message => same key on every attempt. Well
    under Resend's 256-character cap.
    """
    return f"{EMAIL_KEY_PREFIX}:{tenant_id}:{email_logical_id(message)}"


@dataclass
class LostResponseMailProvider:
    """Provider that ACCEPTS a delivery but LOSTS the response once.

    Simulates crash matrix CASE 4/5: provider accepted, response never reaches
    the worker (timeout). The first attempt raises after committing; the retry
    with the same idempotency key returns the original message id. With
    ``honors_idempotency=False`` the retry delivers a second physical email.
    """

    _sent: dict[str, SentEmail] = field(default_factory=dict)
    _by_key: dict[str, str] = field(default_factory=dict)
    honors_idempotency: bool = True
    lost_first_response: bool = True

    @property
    def sent_count(self) -> int:
        return len(self._sent)

    async def send(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        idempotency_key: str | None = None,
    ) -> SendResult:
        if (
            self.honors_idempotency
            and idempotency_key is not None
            and idempotency_key in self._by_key
        ):
            existing = self._by_key[idempotency_key]
            return SendResult(existing, duplicated=True)
        message_id = f"msgr-{len(self._sent) + 1:06d}"
        self._sent[message_id] = SentEmail(
            to=to,
            subject=subject,
            message_id=message_id,
            idempotency_key=idempotency_key,
            created_at=utcnow(),
        )
        if idempotency_key is not None:
            self._by_key[idempotency_key] = message_id
        if self.lost_first_response and len(self._sent) == 1:
            # Provider accepted + response lost on the worker side.
            raise TimeoutError("response lost; provider accepted the send")
        return SendResult(message_id, duplicated=False)


async def execute_email_job(
    payload: dict[str, Any],
    ctx: JobContext,
    *,
    provider: Any,
    require_idempotency: bool = True,
) -> dict[str, Any]:
    """Execute one email job end-to-end: derive the deterministic idempotency
    key, attach it to the provider call and pass through.

    This is OPTION A in miniature: the job payload never needs to carry a key -
    every retry recomputes ``email:<tenant_id>:<logical_id>`` from the tenant +
    rendered content, so crash-after-send, response-loss and dual-execution all
    collide on the SAME key and the provider returns the original message id.
    """
    work = dict(payload)
    key = work.get("idempotency_key")
    if key is None:
        key = email_idempotency_key(ctx.tenant_id, work)
        work["idempotency_key"] = key
    if require_idempotency and key is None:
        raise RuntimeError("idempotency_key required but absent")
    return await send_email_handler(work, ctx, provider=provider)


__all__ = [
    "EMAIL_KEY_PREFIX",
    "LostResponseMailProvider",
    "email_idempotency_key",
    "email_logical_id",
    "execute_email_job",
]
