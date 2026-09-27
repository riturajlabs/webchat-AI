"""Mail providers: Mailpit (development) and Resend (production), ADR-001."""

import asyncio
import json
import logging
import urllib.request
from collections.abc import Mapping
from email.utils import parseaddr

from backend.core.config import get_settings
from backend.core.privacy import content_hash, mask_email, redact_secret_key
from backend.services.mail.base import (
    EmailMessage,
    MailDeliveryIndeterminate,
    MailSendResult,
)

logger = logging.getLogger("webchat_ai")

#: Provider responses that prove nothing was sent, so a retry is safe. Resend
#: reports these as typed client-side errors; each one means the request was
#: rejected before any message was queued for delivery.
_RESEND_DEFINITE_ERRORS: tuple[str, ...] = (
    "ValidationError",
    "MissingRequiredFieldsError",
    "MissingApiKeyError",
    "InvalidApiKeyError",
    "RateLimitError",
)


class MailpitProvider:
    """Deliver to the local Mailpit mailbox via its HTTP send API.

    Uses the stdlib HTTP client so the provider works in the slim production
    container (which does not install dev/test dependencies like httpx).
    Mailpit's `/api/v1/send` expects `From`/`To` as `{Name, Email}` objects.

    Mailpit has no idempotency support and is development-only, so an
    `EmailMessage.idempotency_key` is simply not forwarded here. That is safe:
    nothing in production resolves to this provider, and Phase 17B never sends
    through it.
    """

    def __init__(self, api_url: str) -> None:
        self._api_url = api_url

    async def send(self, message: EmailMessage) -> MailSendResult:
        from_name, from_email = parseaddr(get_settings().email_from)
        payload = {
            "From": {"Name": from_name or "WebChat AI", "Email": from_email},
            "To": [{"Name": "", "Email": message.to}],
            "Subject": message.subject,
            "Text": message.text,
            "HTML": message.html,
        }
        await asyncio.to_thread(self._post, payload)
        # Mailpit's response is not parsed for a message id. `None` is reported
        # honestly rather than substituted with a placeholder, so the durable
        # record never claims provider evidence that does not exist.
        return MailSendResult(provider_message_id=None)

    def _post(self, payload: Mapping[str, object]) -> None:
        to_addr = payload.get("To")
        to_str = to_addr[0].get("Email", "?") if isinstance(to_addr, list) and to_addr else "?"
        logger.info(
            "Mailpit dispatching: provider=mailpit, to=%s",
            mask_email(to_str),
        )
        request = urllib.request.Request(
            f"{self._api_url}/api/v1/send",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                if response.status >= 400:
                    raise RuntimeError(f"Mailpit rejected email with status {response.status}")
                logger.info(
                    "Mailpit email sent successfully: provider=mailpit, to=%s, status=%d",
                    mask_email(to_str),
                    response.status,
                )
        except Exception:
            logger.exception(
                "Mailpit email delivery FAILED: provider=mailpit, to=%s",
                mask_email(to_str),
            )
            raise


class ResendProvider:
    """Deliver through the Resend HTTP API using the official SDK (ADR-001).

    Phase 17B: when the message carries an ``idempotency_key`` it is handed to
    the SDK's own ``SendOptions`` (``resend.Emails.send(params, options)``),
    which the installed SDK turns into the documented ``Idempotency-Key``
    request header. The supported SDK option is used deliberately: constructing
    the header by hand would be undocumented behaviour that a future SDK bump
    could silently drop.

    Resend retains an idempotency key for 24 hours, so within that window a
    replayed send - a crash after the provider accepted, a lost response, a
    reclaimed lease - collapses to one delivery. Beyond the window the
    protection is gone; see the Phase 17B report for the residual risk.
    """

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def send(self, message: EmailMessage) -> MailSendResult:
        return await asyncio.to_thread(self._send_sync, message)

    def _send_sync(self, message: EmailMessage) -> MailSendResult:
        import resend  # imported lazily; only required in production

        resend.api_key = self._api_key
        settings = get_settings()
        sender = settings.email_from
        key = message.idempotency_key
        # The key embeds a tenant id, so logs get the redacted form only.
        key_hint = redact_secret_key(key) if key else "none"
        logger.info(
            "Resend dispatching: provider=resend, to=%s, from=%s, subject_hash=%s, "
            "idempotency_key=%s",
            mask_email(message.to),
            sender,
            content_hash(message.subject),
            key_hint,
        )
        try:
            params: dict[str, object] = {
                "from": sender,
                "to": message.to,
                "subject": message.subject,
                "text": message.text,
                "html": message.html,
            }
            options: dict[str, object] = {}
            if key is not None:
                # The SDK's documented option, not a hand-built header.
                options["idempotency_key"] = key
            result = resend.Emails.send(params, options or None)  # type: ignore[arg-type]
        except Exception as exc:
            self._log_failure(exc, message=message, sender=sender, key_hint=key_hint)
            if _is_definite_rejection(exc):
                # The provider rejected the request outright, so nothing was
                # sent and a retry cannot duplicate anything.
                raise
            # Everything else - a timeout, a dropped connection, a 5xx - leaves
            # the outcome genuinely unknown. Saying so is what stops the worker
            # from blindly re-sending a mail the user may already have.
            raise MailDeliveryIndeterminate(
                f"resend send outcome unknown: {type(exc).__name__}"
            ) from exc
        email_id = result.get("id") if isinstance(result, dict) else None
        logger.info(
            "Resend email sent successfully: message_id=%s, to=%s, status=delivered, "
            "idempotency_key=%s",
            email_id,
            mask_email(message.to),
            key_hint,
        )
        return MailSendResult(provider_message_id=email_id)

    @staticmethod
    def _log_failure(
        exc: Exception, *, message: EmailMessage, sender: str, key_hint: str
    ) -> None:
        logger.exception(
            "Resend email delivery FAILED: to=%s, from=%s, subject_hash=%s, "
            "provider=resend, idempotency_key=%s, error_type=%s",
            mask_email(message.to),
            sender,
            content_hash(message.subject),
            key_hint,
            type(exc).__name__,
        )


def _is_definite_rejection(exc: Exception) -> bool:
    """Whether ``exc`` proves the provider did not send the message.

    Conservative by design: anything unrecognised is treated as *indeterminate*,
    because over-claiming a definite failure is what would cause a duplicate
    send, and under-claiming only costs a delivery that is safely deduplicated
    by the same key.
    """
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return False
    name = type(exc).__name__
    if name in _RESEND_DEFINITE_ERRORS:
        return True
    # A bare ResendError with a 4xx code is a client-side rejection; a 5xx is
    # not, because the provider may have accepted the send before failing.
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code.isdigit():
        return 400 <= int(code) < 500
    if isinstance(code, int) and not isinstance(code, bool):
        return 400 <= code < 500
    return False
