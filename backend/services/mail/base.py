"""Email service abstraction (ADR-001).

`MailService` is a thin, injectable interface; `get_mail_service()` returns the
provider selected by the environment (Mailpit in development, Resend otherwise).
Emails are always sent asynchronously through the ARQ `send_email` job - never
inline from an API request.

Phase 17B delivery metadata
---------------------------
`EmailMessage` carries three optional *delivery* attributes that are deliberately
not part of the message's content:

* ``tenant_id`` - who the send belongs to. Needed because the worker's job
  context carries no tenant: production jobs read their tenant from a domain
  row, and an email has none. The enqueue site is the only place that has both
  the message and the authoritative tenant, so it is where the key is built.
* ``delivery_id`` - the identity of *this send attempt as a logical delivery*,
  minted once at enqueue and carried in the payload forever. Phase 17B.1: this
  is what the provider key is derived from. It is minted per enqueue, so two
  sends of byte-identical content to the same recipient are two distinct
  logical deliveries with two distinct keys - which is the correct behaviour
  for a user who genuinely asks for two password resets.
* ``idempotency_key`` - the provider-side deduplication key (Resend's
  `Idempotency-Key`), derived from ``delivery_id``. It is *derived from* the
  delivery identity, never part of the content, so carrying it on a message
  cannot change what is sent.

None of these fields change what is sent; a message with none of them set
behaves exactly as it did before Phase 17B.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Protocol

EmailDispatcher = Callable[["EmailMessage"], Awaitable[None]]


class MailDeliveryIndeterminate(Exception):
    """The provider gave no usable answer about whether the mail was sent.

    This is the single most important distinction in Phase 17B.1. A *definite*
    failure (a 4xx rejection, a validation error) means nothing was sent, so a
    retry is safe and correct. An *indeterminate* outcome - a timeout, a dropped
    connection, a 5xx, any case where the request may have reached the provider
    and the response was lost - means the mail may already be in the recipient's
    inbox. Retrying that blindly is how a user receives the same email twice.

    Only the provider can tell the two apart, so the provider is what raises
    this, and the worker turns it into a durable ``unknown`` state instead of a
    naive resend.
    """


@dataclass(frozen=True)
class MailSendResult:
    """What the provider knows about a completed send.

    ``provider_message_id`` is the provider's own identifier for the accepted
    message (Resend's email id). It is the only durable evidence that a send
    happened, so it is recorded. ``None`` is honest rather than a placeholder:
    a provider that returns no id (Mailpit) genuinely does not give one, and
    inventing a value would make the durable state claim more than is known.
    """

    provider_message_id: str | None = None
    #: True when the provider confirmed it collapsed this request onto an
    #: earlier send with the same idempotency key, rather than sending anew.
    deduplicated: bool = False


@dataclass(frozen=True)
class EmailMessage:
    """A fully-rendered email ready for delivery."""

    to: str
    subject: str
    text: str
    html: str
    #: Delivery scope. Empty means "no tenant known at enqueue time", in which
    #: case no idempotency key can be built (see ``enqueue_email``).
    tenant_id: str = ""
    #: Stable identity of this logical delivery, minted at enqueue. Empty means
    #: "not yet enqueued through the keyed path".
    delivery_id: str = ""
    #: Provider deduplication key, computed by the enqueue site. ``None`` means
    #: "send without a key", which is the pre-Phase-17B behaviour.
    idempotency_key: str | None = None

    def to_payload(self) -> dict[str, str]:
        """The queue payload for this message.

        Only the content fields are always present, so a message without
        delivery metadata produces a byte-identical payload to the
        pre-Phase-17B shape. The delivery identity is added only when present,
        which keeps payloads enqueued before this change consumable by the new
        worker (it falls back to the untracked path) instead of failing.

        ``tenant_id`` rides along as delivery metadata for the same reason: the
        worker rebuilds the message from this payload, so without it the durable
        delivery record would be filed under ``tenant-unknown`` and the
        tenant-scoped ops queries over that collection would be useless. It is
        an internal routing/ownership field, not customer content.
        """
        payload = {"to": self.to, "subject": self.subject, "text": self.text, "html": self.html}
        if self.delivery_id:
            payload["delivery_id"] = self.delivery_id
        if self.idempotency_key is not None:
            payload["idempotency_key"] = self.idempotency_key
        if self.tenant_id:
            payload["tenant_id"] = self.tenant_id
        return payload

    def for_tenant(self, tenant_id: str) -> EmailMessage:
        """Return a copy scoped to ``tenant_id`` (delivery metadata only)."""
        return replace(self, tenant_id=tenant_id)

    def with_delivery_identity(
        self, *, delivery_id: str, idempotency_key: str | None
    ) -> EmailMessage:
        """Return a copy carrying the delivery identity minted at enqueue."""
        return replace(self, delivery_id=delivery_id, idempotency_key=idempotency_key)

    def with_idempotency_key(self, key: str | None) -> EmailMessage:
        """Return a copy carrying ``key`` (used once the key is computed)."""
        return replace(self, idempotency_key=key)

    @property
    def content_fields(self) -> dict[str, str]:
        """The four fields that define the message's content identity."""
        return {"to": self.to, "subject": self.subject, "text": self.text, "html": self.html}


class MailService(Protocol):
    """Delivers a rendered email message.

    Returns what the provider knows about the send so the caller can record
    durable evidence of acceptance. Raises
    :class:`MailDeliveryIndeterminate` when the outcome is unknown, which the
    caller must not treat as "not sent".
    """

    async def send(self, message: EmailMessage) -> MailSendResult: ...
