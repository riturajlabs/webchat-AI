"""ARQ email job (ADR-001: email is always sent asynchronously).

`send_email` is the registered worker task; `enqueue_email` is the fast, async
enqueue path used by services so API requests never block on SMTP/HTTP delivery.
"""

import logging
from typing import Any

from arq.connections import ArqRedis
from redis.asyncio import ConnectionPool

from backend.core.config import get_settings
from backend.core.privacy import content_hash, mask_email
from backend.services.mail import EmailMessage, get_mail_service
from backend.workers.jobs.log_context import request_context, reset_context

logger = logging.getLogger("webchat_ai")

_pool: ConnectionPool | None = None


def _arq_redis() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = ConnectionPool.from_url(get_settings().redis_url, decode_responses=True)
    return ArqRedis(connection_pool=_pool)


async def send_email(ctx: dict[str, Any], payload: dict[str, str]) -> None:
    """Worker task: deliver a rendered email through the configured provider."""
    request_token, tenant_token = request_context(ctx)
    try:
        message = EmailMessage(
            to=payload["to"],
            subject=payload["subject"],
            text=payload["text"],
            html=payload["html"],
        )
        try:
            await get_mail_service().send(message)
        except Exception:
            # FIND-03: never log the recipient address or the plaintext subject.
            # `mask_email` keeps a non-identifying prefix + domain; the subject
            # is emitted as a deterministic hash for correlation only.
            logger.exception(
                "Email delivery failed (to=%s subject_hash=%s)",
                mask_email(payload["to"]),
                content_hash(payload["subject"]),
            )
            raise
    finally:
        reset_context(request_token, tenant_token)


async def enqueue_email(message: EmailMessage) -> None:
    """Enqueue an email for asynchronous delivery."""
    await _arq_redis().enqueue_job("send_email", message.to_payload())
