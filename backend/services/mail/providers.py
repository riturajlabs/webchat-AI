"""Mail providers: Mailpit (development) and Resend (production), ADR-001."""

import asyncio
import json
import logging
import urllib.request
from collections.abc import Mapping
from email.utils import parseaddr

from backend.core.config import get_settings
from backend.services.mail.base import EmailMessage

logger = logging.getLogger(__name__)


class MailpitProvider:
    """Deliver to the local Mailpit mailbox via its HTTP send API.

    Uses the stdlib HTTP client so the provider works in the slim production
    container (which does not install dev/test dependencies like httpx).
    Mailpit's `/api/v1/send` expects `From`/`To` as `{Name, Email}` objects.
    """

    def __init__(self, api_url: str) -> None:
        self._api_url = api_url

    async def send(self, message: EmailMessage) -> None:
        from_name, from_email = parseaddr(get_settings().email_from)
        payload = {
            "From": {"Name": from_name or "WebChat AI", "Email": from_email},
            "To": [{"Name": "", "Email": message.to}],
            "Subject": message.subject,
            "Text": message.text,
            "HTML": message.html,
        }
        await asyncio.to_thread(self._post, payload)

    def _post(self, payload: Mapping[str, object]) -> None:
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
        except Exception:
            logger.exception("Mailpit email delivery failed (api_url=%s)", self._api_url)
            raise


class ResendProvider:
    """Deliver through the Resend HTTP API using the official SDK (ADR-001)."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def send(self, message: EmailMessage) -> None:
        await asyncio.to_thread(self._send_sync, message)

    def _send_sync(self, message: EmailMessage) -> None:
        import resend  # imported lazily; only required in production

        resend.api_key = self._api_key
        try:
            resend.Emails.send(
                {
                    "from": get_settings().email_from,
                    "to": message.to,
                    "subject": message.subject,
                    "text": message.text,
                    "html": message.html,
                }
            )
        except Exception:
            # Provider errors (invalid key, unverified sending domain, etc.) are
            # logged with the relevant context and re-raised so the worker job
            # records the failure and retries.
            logger.exception(
                "Resend email delivery failed (to=%s, from=%s)",
                message.to,
                get_settings().email_from,
            )
            raise
