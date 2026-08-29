"""Mail providers: Mailpit (development) and Resend (production), ADR-001."""

import asyncio
import json
import logging
import urllib.request
from collections.abc import Mapping
from email.utils import parseaddr

from backend.core.config import get_settings
from backend.services.mail.base import EmailMessage

logger = logging.getLogger("webchat_ai")


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
        to_addr = payload.get("To")
        to_str = to_addr[0].get("Email", "?") if isinstance(to_addr, list) and to_addr else "?"
        logger.info(
            "Mailpit dispatching: provider=mailpit, to=%s, api_url=%s",
            to_str,
            self._api_url,
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
                    "Mailpit email sent successfully: to=%s, status=%d",
                    to_str,
                    response.status,
                )
        except Exception:
            logger.exception(
                "Mailpit email delivery FAILED: to=%s, api_url=%s",
                to_str,
                self._api_url,
            )
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
        settings = get_settings()
        sender = settings.email_from
        logger.info(
            "Resend dispatching: provider=resend, to=%s, from=%s, subject=%s",
            message.to,
            sender,
            message.subject[:80],
        )
        try:
            result = resend.Emails.send(
                {
                    "from": sender,
                    "to": message.to,
                    "subject": message.subject,
                    "text": message.text,
                    "html": message.html,
                }
            )
            email_id = result.get("id") if isinstance(result, dict) else None
            logger.info(
                "Resend email sent successfully: message_id=%s, to=%s, status=delivered",
                email_id,
                message.to,
            )
        except Exception:
            logger.exception(
                "Resend email delivery FAILED: to=%s, from=%s, subject=%s, provider=resend",
                message.to,
                sender,
                message.subject[:80],
            )
            raise
