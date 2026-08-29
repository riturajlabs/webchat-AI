"""ARQ email job (ADR-001: email is always sent asynchronously).

`send_email` is the registered worker task; `enqueue_email` is the fast, async
enqueue path used by services so API requests never block on SMTP/HTTP delivery.
"""

import logging
from typing import Any

from arq.connections import ArqRedis
from redis.asyncio import ConnectionPool

from backend.core.config import get_settings
from backend.services.mail import EmailMessage, get_mail_service

logger = logging.getLogger("webchat_ai")

_pool: ConnectionPool | None = None


def _arq_redis() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = ConnectionPool.from_url(get_settings().redis_url, decode_responses=True)
    return ArqRedis(connection_pool=_pool)


async def send_email(ctx: dict[str, Any], payload: dict[str, str]) -> None:
    """Worker task: deliver a rendered email through the configured provider."""
    _ = ctx
    message = EmailMessage(
        to=payload["to"],
        subject=payload["subject"],
        text=payload["text"],
        html=payload["html"],
    )
    try:
        await get_mail_service().send(message)
    except Exception:
        logger.exception(
            "Email delivery failed (to=%s, subject=%s)", payload["to"], payload["subject"]
        )
        raise


async def enqueue_email(message: EmailMessage) -> None:
    """Enqueue an email for asynchronous delivery."""
    await _arq_redis().enqueue_job("send_email", message.to_payload())
