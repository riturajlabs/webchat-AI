"""ARQ email job (ADR-001: email is always sent asynchronously).

`send_email` is the registered worker task; `enqueue_email` is the fast, async
enqueue path used by services so API requests never block on SMTP/HTTP delivery.

Phase 17B.1 - per-delivery identity and durable state
------------------------------------------------------
Phase 17B derived the provider idempotency key from the message *content*, which
had a real defect: two logical deliveries of identical content produced one key,
so the second send was suppressed as a duplicate and the user received nothing.
A provider key also cannot answer the question that matters after a crash - *did
this email already go out?* - so a re-delivery could not tell a completed send
from one that never happened.

The fix is two parts:

* **Identity.** :func:`enqueue_email` mints a ``delivery_id`` once and persists
  it in the job payload; the provider key is derived from it. Every retry, lease
  reclaim and duplicate execution reuses the same key by construction, and two
  enqueues are two deliveries with two keys - so a legitimate repeat send is
  never suppressed. Building it at enqueue time is deliberate: the enqueue site
  is the only place that has the authoritative tenant (an email job context
  carries none, and `forgot_password` is a public endpoint with no ambient
  tenant).
* **Durable state.** Each attempt claims a row keyed by ``delivery_id`` before
  talking to the provider and records exactly one outcome afterwards, so the
  state survives the crash that the queue is about to cause. A delivery already
  recorded as ``accepted`` is never sent again. An attempt whose provider
  response was lost is recorded as ``unknown`` and only retried while the
  provider still honours the same key; past that point the job stops and says
  so rather than risking a second copy in the user's inbox.

The outcome is therefore *knowable* after any crash, which is what this phase
actually needed. It is still not exactly-once delivery: within the provider
window a resend is deduplicated, and beyond it an ``unknown`` delivery is
surfaced for a human rather than resolved automatically. See the Phase 17B.1
report for the residual window.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from arq.connections import ArqRedis
from redis.asyncio import ConnectionPool

from backend.core.config import get_settings
from backend.core.database import MongoDB
from backend.core.privacy import content_hash, mask_email
from backend.queue.mail_idempotency import (
    canonical_message,
    key_for_delivery,
    message_digest,
    new_attempt_token,
    new_delivery_id,
    redact_key,
)
from backend.repositories.email_delivery_repository import (
    EmailDeliveryClaim,
    EmailDeliveryRepository,
    MongoEmailDeliveryRepository,
)
from backend.services.mail import EmailMessage, get_mail_service
from backend.services.mail.base import MailDeliveryIndeterminate
from backend.workers.jobs.log_context import request_context, reset_context

logger = logging.getLogger("webchat_ai")

_pool: ConnectionPool | None = None
_repository: EmailDeliveryRepository | None = None


def _arq_redis() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = ConnectionPool.from_url(get_settings().redis_url, decode_responses=True)
    return ArqRedis(connection_pool=_pool)


def delivery_repository() -> EmailDeliveryRepository:
    """The durable delivery store for this process.

    Built lazily from the worker's shared Mongo handle, the same way
    ``crawl_website`` builds its repositories, so a worker that never sends an
    email never opens the collection.
    """
    global _repository
    if _repository is None:
        _repository = MongoEmailDeliveryRepository(MongoDB.db())
    return _repository


def _reset_repository() -> None:
    """Drop the cached repository (tests, and worker restart in one process)."""
    global _repository
    _repository = None


def _now() -> datetime:
    return datetime.now(UTC)


def _windows() -> tuple[timedelta, timedelta]:
    settings = get_settings()
    return (
        timedelta(seconds=settings.mail_provider_idempotency_window_seconds),
        timedelta(seconds=settings.mail_delivery_attempt_stale_seconds),
    )


async def send_email(ctx: dict[str, Any], payload: dict[str, str]) -> None:
    """Worker task: deliver a rendered email through the configured provider.

    The job returns normally when the delivery is already known to be complete
    or is deliberately being left to a human - retrying either would be the
    bug this phase removes. It re-raises only when the provider gave a *definite*
    rejection, because that is the one case where another attempt is both safe
    and useful.
    """
    request_token, tenant_token = request_context(ctx)
    try:
        message = _message_from_payload(payload)
        delivery_id = message.delivery_id
        if not delivery_id:
            # A payload enqueued before Phase 17B.1 (or with the feature off)
            # carries no delivery identity. There is no durable row to consult
            # and no way to build a key that distinguishes this attempt, so send
            # it the pre-17B way and say so in the log rather than inventing an
            # identity that could collide with a real delivery.
            logger.warning(
                "email_delivery_untracked reason=no_delivery_id to=%s subject_hash=%s",
                mask_email(payload["to"]),
                content_hash(payload["subject"]),
            )
            await _send_untracked(message, payload)
            return

        claim = await _claim(message, payload)
        if not claim.granted:
            _log_refusal(claim, payload)
            return

        await _attempt(message, payload, claim)
    finally:
        reset_context(request_token, tenant_token)


def _message_from_payload(payload: dict[str, str]) -> EmailMessage:
    return EmailMessage(
        to=payload["to"],
        subject=payload["subject"],
        text=payload["text"],
        html=payload["html"],
        delivery_id=payload.get("delivery_id", ""),
        idempotency_key=payload.get("idempotency_key"),
        # Carried so the delivery record is filed under the real tenant. A
        # payload enqueued before this field existed leaves it empty, and
        # `_scope` records that fact explicitly rather than guessing.
        tenant_id=payload.get("tenant_id", ""),
    )


async def _send_untracked(message: EmailMessage, payload: dict[str, str]) -> None:
    try:
        await get_mail_service().send(message)
    except Exception:
        _log_failure(payload, "email delivery failed (untracked)")
        raise


async def _claim(message: EmailMessage, payload: dict[str, str]) -> EmailDeliveryClaim:
    """Take durable ownership of this delivery for one attempt."""
    provider_key = message.idempotency_key or key_for_delivery(_scope(message), message.delivery_id)
    provider_window, stale_after = _windows()
    return await delivery_repository().begin_attempt(
        message.delivery_id,
        tenant_id=_scope(message),
        provider_key=provider_key,
        # A one-way fingerprint, not the content: it lets an operator tell two
        # attempts apart without this collection ever holding customer mail.
        content_hash=_content_fingerprint(message),
        attempt_token=new_attempt_token(),
        now=_now(),
        provider_window=provider_window,
        stale_after=stale_after,
    )


def _scope(message: EmailMessage) -> str:
    """The tenant scope for the delivery, never invented when unknown.

    ``delivery_id`` alone already makes the key unique, so an unknown tenant
    degrades isolation of the *key* only, never correctness of the send.
    """
    return message.tenant_id or "tenant-unknown"


def _content_fingerprint(message: EmailMessage) -> str:
    return message_digest(
        canonical_message(
            to=message.to, subject=message.subject, text=message.text, html=message.html
        )
    )


async def _attempt(
    message: EmailMessage, payload: dict[str, str], claim: EmailDeliveryClaim
) -> None:
    """Call the provider, then record exactly one honest outcome."""
    repository = delivery_repository()
    token = claim.attempt_token
    try:
        result = await get_mail_service().send(message)
    except MailDeliveryIndeterminate:
        await repository.mark_unknown(message.delivery_id, token, now=_now())
        _log_failure(payload, "email delivery outcome unknown; recorded as unknown")
        raise
    except Exception as exc:
        # A definite rejection: nothing was sent, so `failed` is both accurate
        # and safe to retry. Only the error *type* is recorded - a provider
        # exception message can embed the request, including the recipient, so
        # a one-way hash of the type name is the most this record may hold.
        await repository.mark_failed(
            message.delivery_id,
            token,
            content_hash(type(exc).__name__),
            now=_now(),
        )
        _log_failure(payload, "email delivery rejected by provider")
        raise
    await repository.mark_accepted(
        message.delivery_id, token, result.provider_message_id, now=_now()
    )
    logger.info(
        "email_delivery_accepted delivery_id=%s attempts=%s message_id_present=%s",
        message.delivery_id,
        claim.record.attempts,
        result.provider_message_id is not None,
    )


def _log_failure(payload: dict[str, str], reason: str) -> None:
    """Log a send failure without ever leaking recipient, subject or key.

    FIND-03: the recipient is masked, the subject becomes a deterministic hash
    for correlation, and the idempotency key embeds a tenant id so it is
    redacted.
    """
    logger.exception(
        "%s (to=%s subject_hash=%s idempotency_key=%s)",
        reason,
        mask_email(payload["to"]),
        content_hash(payload["subject"]),
        _redacted_key(payload),
    )


def _redacted_key(payload: dict[str, str]) -> str:
    key = payload.get("idempotency_key")
    return redact_key(key) if key else "none"


def _log_refusal(claim: EmailDeliveryClaim, payload: dict[str, str]) -> None:
    """Log *why* no send happened, so dedupe and a stuck delivery are distinguishable."""
    reason = {
        "accepted": "email_delivery_skipped reason=already_accepted",
        "unknown_expired": "email_delivery_escalated reason=unknown_beyond_provider_window",
        "inflight": "email_delivery_skipped reason=attempt_in_flight",
    }[claim.refusal or "inflight"]
    logger.info(
        "%s (delivery_id=%s to=%s subject_hash=%s attempts=%s state=%s)",
        reason,
        claim.record.delivery_id,
        mask_email(payload["to"]),
        content_hash(payload["subject"]),
        claim.record.attempts,
        claim.record.state,
    )


def resolve_delivery_identity(message: EmailMessage) -> tuple[str, str | None]:
    """Mint the delivery identity and provider key for a message.

    ``(delivery_id, None)`` is returned - never a fabricated key - when the
    feature is switched off. A wrong key would be worse than no key: it could
    suppress a *different* message, so the caller sends untracked instead and the
    omission is logged.

    A missing tenant is no longer a reason to skip the key. Phase 17B.1 makes the
    key a function of the delivery identity, which is unique regardless of
    tenant, so tenant-less flows (``forgot_password``) are protected too. The
    scope segment is only isolation, and an unknown scope says so.
    """
    settings = get_settings()
    if not settings.mail_idempotency_enabled:
        return "", None
    delivery_id = new_delivery_id()
    return delivery_id, key_for_delivery(_scope(message), delivery_id)


async def enqueue_email(message: EmailMessage) -> None:
    """Enqueue an email for asynchronous delivery.

    ``message.tenant_id`` should be set by the caller (``message.for_tenant``)
    so the delivery is scoped to the owning tenant.
    """
    delivery_id, key = resolve_delivery_identity(message)
    if key is None:
        logger.warning(
            "email_idempotency_disabled to=%s subject_hash=%s",
            mask_email(message.to),
            content_hash(message.subject),
        )
    outgoing = message.with_delivery_identity(delivery_id=delivery_id, idempotency_key=key)
    await _arq_redis().enqueue_job("send_email", outgoing.to_payload())
