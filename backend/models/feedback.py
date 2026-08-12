"""Visitor feedback model (Phase 12.4, ADR-005 §5.6).

One `feedback` document per rating a visitor gives to an assistant answer.
Carries the tenant/website/session/message keys needed to trace a rating back
to the exact answer and conversation, a 1-5 star `rating`, a coarse `category`
(helpful | wrong | incomplete | offensive | other), and an optional free-text
`comment`. `created_at` backs the 2-year TTL (ADR-005 §5.7). Every document
carries `tenant_id`; every repository query is tenant-scoped
(00-AI-Development-Rules.md §7).
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.core.security import new_id, utcnow

FEEDBACK_SCHEMA_VERSION = 1

FEEDBACK_MIN_RATING = 1
FEEDBACK_MAX_RATING = 5

FEEDBACK_CATEGORY_HELPFUL = "helpful"
FEEDBACK_CATEGORY_WRONG = "wrong"
FEEDBACK_CATEGORY_INCOMPLETE = "incomplete"
FEEDBACK_CATEGORY_OFFENSIVE = "offensive"
FEEDBACK_CATEGORY_OTHER = "other"

FEEDBACK_CATEGORIES = frozenset(
    {
        FEEDBACK_CATEGORY_HELPFUL,
        FEEDBACK_CATEGORY_WRONG,
        FEEDBACK_CATEGORY_INCOMPLETE,
        FEEDBACK_CATEGORY_OFFENSIVE,
        FEEDBACK_CATEGORY_OTHER,
    }
)


class Feedback(BaseModel):
    """A single visitor rating on an assistant answer (ADR-005 §5.6)."""

    model_config = ConfigDict(extra="allow")

    id: str
    tenant_id: str
    website_id: str
    session_id: str
    message_id: str
    rating: int = Field(ge=FEEDBACK_MIN_RATING, le=FEEDBACK_MAX_RATING)
    category: str
    comment: str = ""
    created_at: datetime
    schema_version: int = FEEDBACK_SCHEMA_VERSION

    @classmethod
    def new(
        cls,
        *,
        tenant_id: str,
        website_id: str,
        session_id: str,
        message_id: str,
        rating: int,
        category: str,
        comment: str = "",
    ) -> "Feedback":
        return cls(
            id=new_id(),
            tenant_id=tenant_id,
            website_id=website_id,
            session_id=session_id,
            message_id=message_id,
            rating=rating,
            category=category,
            comment=comment.strip(),
            created_at=utcnow(),
        )

    @classmethod
    def from_doc(cls, doc: dict[str, Any]) -> "Feedback":
        doc = dict(doc)
        doc["id"] = str(doc.pop("_id"))
        return cls(**doc)

    def to_doc(self) -> dict[str, Any]:
        doc = self.model_dump(exclude={"id"})
        doc["_id"] = self.id
        return doc


__all__ = [
    "FEEDBACK_CATEGORIES",
    "FEEDBACK_CATEGORY_HELPFUL",
    "FEEDBACK_CATEGORY_INCOMPLETE",
    "FEEDBACK_CATEGORY_OFFENSIVE",
    "FEEDBACK_CATEGORY_OTHER",
    "FEEDBACK_CATEGORY_WRONG",
    "FEEDBACK_MAX_RATING",
    "FEEDBACK_MIN_RATING",
    "FEEDBACK_SCHEMA_VERSION",
    "Feedback",
]
