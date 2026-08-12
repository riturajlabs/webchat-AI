"""Visitor feedback business logic (Phase 12.4, ADR-005 §5.6).

Two surfaces:
  * `submit` — the widget path. Re-validates the untrusted `message_id` /
    `session_id` against the token's tenant/website (claims are never trusted;
    ADR-004 tenant validation flow) and dedupes so a message can be rated at
    most once.
  * `list_feedback` / `get_summary` — the dashboard read paths (owner/admin),
    tenant-scoped with optional website/category/rating filters and the
    satisfaction breakdown for the UI/UX §12 "User Satisfaction" chart.

The service only depends on repository Protocols (layering rules §6).
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from backend.core.errors import FeedbackMessageNotFoundError
from backend.core.security import utcnow
from backend.models.chat_message import CHAT_ROLE_ASSISTANT
from backend.models.feedback import Feedback
from backend.repositories.chat_message_repository import ChatMessageRepository
from backend.repositories.feedback_repository import FeedbackRepository, FeedbackSummary

logger = logging.getLogger("webchat_ai")

# Default satisfaction window when the dashboard asks without a date filter
# (30 days of ratings feed the chart).
DEFAULT_SUMMARY_WINDOW_DAYS = 30
# Longest satisfaction window a dashboard can request (mirrors analytics).
MAX_SUMMARY_WINDOW_DAYS = 90


@dataclass(frozen=True)
class FeedbackItem:
    id: str
    website_id: str
    session_id: str
    message_id: str
    rating: int
    category: str
    comment: str
    created_at: datetime


class FeedbackService:
    """Owns submit + read workflows for visitor feedback."""

    def __init__(
        self,
        *,
        feedback: FeedbackRepository,
        messages: ChatMessageRepository,
    ) -> None:
        self._feedback = feedback
        self._messages = messages

    # ------------------------------------------------------------- submit

    async def submit(
        self,
        *,
        tenant_id: str,
        website_id: str,
        session_id: str,
        message_id: str,
        rating: int,
        category: str,
        comment: str = "",
    ) -> None:
        """Persist a rating for an assistant answer, validating + deduping.

        The message must exist and belong to the token's tenant, website, and
        the claimed session (otherwise a visitor could attach ratings to
        arbitrary conversations). A message is rated at most once: a repeat
        submission is treated as idempotent success (the widget UI only sends
        once, and this guards concurrent double-clicks).
        """
        message = await self._messages.find_by_id(tenant_id, message_id)
        if message is None:
            raise FeedbackMessageNotFoundError("Message not found.")
        if (
            message.website_id != website_id
            or message.session_id != session_id
            or message.role != CHAT_ROLE_ASSISTANT
        ):
            raise FeedbackMessageNotFoundError("Message not found.")

        existing = await self._feedback.find_by_message(tenant_id, message_id)
        if existing is not None:
            return  # already rated — idempotent

        await self._feedback.create(
            Feedback.new(
                tenant_id=tenant_id,
                website_id=website_id,
                session_id=session_id,
                message_id=message_id,
                rating=rating,
                category=category,
                comment=comment,
            )
        )

    # ---------------------------------------------------------------- read

    async def list_feedback(
        self,
        tenant_id: str,
        *,
        page: int,
        per_page: int,
        website_id: str | None = None,
        category: str | None = None,
        rating: int | None = None,
    ) -> tuple[list[FeedbackItem], int]:
        items = await self._feedback.list_by_tenant(
            tenant_id,
            website_id=website_id,
            category=category,
            rating=rating,
            limit=per_page,
            offset=(page - 1) * per_page,
        )
        total = await self._feedback.count_by_tenant(
            tenant_id,
            website_id=website_id,
            category=category,
            rating=rating,
        )
        return [
            FeedbackItem(
                id=item.id,
                website_id=item.website_id,
                session_id=item.session_id,
                message_id=item.message_id,
                rating=item.rating,
                category=item.category,
                comment=item.comment,
                created_at=item.created_at,
            )
            for item in items
        ], total

    async def get_summary(
        self,
        tenant_id: str,
        *,
        website_id: str | None = None,
        since: datetime | None = None,
        days: int | None = None,
    ) -> FeedbackSummary:
        """Return the satisfaction summary for a window.

        `days` mirrors the analytics dashboard's date-range model (start of the
        UTC day `days - 1` back); an explicit `since` takes precedence. When
        neither is given the summary falls back to
        `DEFAULT_SUMMARY_WINDOW_DAYS` (30 days).
        """
        if since is not None:
            window = since
        elif days is not None:
            window = start_of_day_window(days)
        else:
            window = utcnow() - timedelta(days=DEFAULT_SUMMARY_WINDOW_DAYS)
        return await self._feedback.summary_by_tenant(
            tenant_id,
            website_id=website_id,
            since=window,
        )


def start_of_day_window(days: int) -> datetime:
    """Start of the UTC day `days - 1` days ago (inclusive of today)."""
    now = utcnow()
    start = now - timedelta(days=days - 1)
    return start.replace(hour=0, minute=0, second=0, microsecond=0)


__all__ = [
    "DEFAULT_SUMMARY_WINDOW_DAYS",
    "FeedbackItem",
    "FeedbackService",
    "MAX_SUMMARY_WINDOW_DAYS",
]
