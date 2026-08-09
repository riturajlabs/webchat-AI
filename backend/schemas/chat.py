"""Pydantic v2 request schemas for the chat API (Phase 6)."""

from pydantic import BaseModel, Field, field_validator

MAX_QUESTION_LENGTH = 2000


class ChatRequest(BaseModel):
    """Body of a chat streaming request.

    The tenant is taken from the authenticated principal - `website_id` and
    `session_id` only ever select data inside that tenant
    (00-AI-Development-Rules.md §7).
    """

    website_id: str = Field(min_length=1, max_length=128)
    question: str = Field(min_length=1, max_length=MAX_QUESTION_LENGTH)
    session_id: str | None = Field(default=None, min_length=1, max_length=128)
    visitor_id: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("question")
    @classmethod
    def _normalize_question(cls, value: str) -> str:
        # Defense in depth alongside backend/prompts/rag.sanitize_question:
        # control characters are stripped and blank questions rejected here so
        # they never reach the model (prompt-injection defense, TRD §8).
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("question must not be blank")
        return cleaned


__all__ = ["ChatRequest", "MAX_QUESTION_LENGTH"]
