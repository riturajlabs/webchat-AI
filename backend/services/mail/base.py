"""Email service abstraction (ADR-001).

`MailService` is a thin, injectable interface; `get_mail_service()` returns the
provider selected by the environment (Mailpit in development, Resend otherwise).
Emails are always sent asynchronously through the ARQ `send_email` job - never
inline from an API request.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

EmailDispatcher = Callable[["EmailMessage"], Awaitable[None]]


@dataclass(frozen=True)
class EmailMessage:
    """A fully-rendered email ready for delivery."""

    to: str
    subject: str
    text: str
    html: str

    def to_payload(self) -> dict[str, str]:
        return {"to": self.to, "subject": self.subject, "text": self.text, "html": self.html}


class MailService(Protocol):
    """Delivers a rendered email message."""

    async def send(self, message: EmailMessage) -> None: ...
