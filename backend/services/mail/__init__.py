"""Mail service: Jinja2 template rendering + provider selection (ADR-001)."""

from functools import lru_cache

from jinja2 import Environment, PackageLoader, select_autoescape

from backend.core.config import get_settings
from backend.services.mail.base import EmailMessage, MailService
from backend.services.mail.providers import MailpitProvider, ResendProvider

_html_env = Environment(
    loader=PackageLoader("backend", "templates/emails"),
    autoescape=select_autoescape(["html"]),
)
_text_env = Environment(loader=PackageLoader("backend", "templates/emails"), autoescape=False)


def render_email(template: str, **context: object) -> tuple[str, str]:
    """Render an email template into (text, html)."""
    html = _html_env.get_template(f"{template}.html").render(**context)
    text = _text_env.get_template(f"{template}.txt").render(**context)
    return text, html


def build_email(to: str, subject: str, template: str, **context: object) -> EmailMessage:
    """Render `template` and wrap it in an `EmailMessage`."""
    text, html = render_email(template, **context)
    return EmailMessage(to=to, subject=subject, text=text, html=html)


_RESEND_SANDBOX_SENDERS = frozenset(
    {
        "onboarding@resend.dev",
        "no-reply@resend.dev",
        "notifications@resend.dev",
    }
)


@lru_cache
def get_mail_service() -> MailService:
    """Return the provider for the current environment (ADR-001)."""
    import logging

    _log = logging.getLogger("webchat_ai")
    settings = get_settings()
    if settings.environment == "development":
        _log.info("Mail service: Mailpit (development mode)")
        return MailpitProvider(settings.mailpit_api_url)
    if not settings.resend_api_key:
        raise RuntimeError("RESEND_API_KEY is required in non-development environments.")
    sender_email = settings.email_from.split("<")[-1].strip().rstrip(">").strip().lower()
    if sender_email in _RESEND_SANDBOX_SENDERS:
        _log.warning(
            "Using Resend sandbox sender (%s). Emails will ONLY be delivered to "
            "the Resend account owner. Configure a verified custom domain sender "
            "for production use.",
            sender_email,
        )
    _log.info("Mail service: Resend (sender=%s)", settings.email_from)
    return ResendProvider(settings.resend_api_key)


__all__ = ["EmailMessage", "MailService", "build_email", "get_mail_service", "render_email"]
