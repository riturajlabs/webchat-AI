"""Pydantic v2 schemas for the feedback API (Phase 12.4, ADR-005 §5.6).

Two surfaces share these types:
  * the public widget submit (`POST /api/widget/v1/feedback`, authorized by a
    widget-session token) — `WidgetFeedbackRequest`; and
  * the dashboard read views (`GET /api/feedback`, owner/admin) —
    `FeedbackOut`, `FeedbackListResponse`, `FeedbackSummaryOut`.
Request validation happens at the Pydantic boundary (rating range, category
enum, comment length); the service owns dedup and tenant scoping.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from backend.models.feedback import FEEDBACK_MAX_RATING, FEEDBACK_MIN_RATING

MAX_FEEDBACK_COMMENT_LENGTH = 1000
MAX_FEEDBACK_ID_LENGTH = 128
MAX_LIST_PAGE_SIZE = 100

FeedbackCategory = Literal["helpful", "wrong", "incomplete", "offensive", "other"]


class WidgetFeedbackRequest(BaseModel):
    """Body of the public widget feedback submission.

    `session_id` and `message_id` are the non-secret conversation/assistant
    ids returned in the chat `done` event — never PII, and re-validated against
    the token's tenant/website by the service before anything is persisted.
    """

    session_id: str = Field(min_length=1, max_length=MAX_FEEDBACK_ID_LENGTH)
    message_id: str = Field(min_length=1, max_length=MAX_FEEDBACK_ID_LENGTH)
    rating: int = Field(ge=FEEDBACK_MIN_RATING, le=FEEDBACK_MAX_RATING)
    category: FeedbackCategory
    comment: str = Field(default="", max_length=MAX_FEEDBACK_COMMENT_LENGTH)

    @field_validator("comment")
    @classmethod
    def _strip_comment(cls, value: str) -> str:
        return value.strip()


class FeedbackOut(BaseModel):
    """A feedback row as the dashboard renders it."""

    id: str
    website_id: str
    session_id: str
    message_id: str
    rating: int
    category: str
    comment: str
    created_at: datetime


class FeedbackListResponse(BaseModel):
    items: list[FeedbackOut]
    total: int
    page: int
    per_page: int


class FeedbackSummaryOut(BaseModel):
    """User-satisfaction breakdown (UI/UX §12)."""

    total: int
    average_rating: float | None
    distribution: dict[int, int]

    @classmethod
    def from_summary(
        cls,
        *,
        total: int,
        distribution: dict[int, int],
    ) -> "FeedbackSummaryOut":
        if total == 0:
            return cls(total=0, average_rating=None, distribution=distribution)
        weighted = sum(rating * count for rating, count in distribution.items())
        return cls(
            total=total,
            average_rating=round(weighted / total, 2),
            distribution=distribution,
        )


__all__ = [
    "FeedbackCategory",
    "FeedbackListResponse",
    "FeedbackOut",
    "FeedbackSummaryOut",
    "MAX_FEEDBACK_COMMENT_LENGTH",
    "MAX_LIST_PAGE_SIZE",
    "WidgetFeedbackRequest",
]
