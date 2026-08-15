"""Shared helpers for building a fake-backed AnalyticsService test environment.

The analytics layer is read-only, so its fake repository aggregates the other
fakes exactly like `MongoAnalyticsRepository` aggregates the real collections:
conversations from `chat_sessions`, response times and AI-response counts from
`messages`, message/token totals from the `usage_records` daily rollup, and
website names from `websites` (Phase 11.3, docs/02-TRD.md §11).
"""

from dataclasses import dataclass
from datetime import datetime

from backend.core.security import new_id
from backend.models.chat_message import ChatMessage
from backend.models.chat_session import ChatSession
from backend.models.feedback import Feedback
from backend.models.website import Website
from backend.prompts.rag import UNKNOWN_ANSWER_FALLBACK
from backend.services.analytics import AnalyticsService

from tests.fakes import (
    FakeAnalyticsRepository,
    FakeChatMessageRepository,
    FakeChatSessionRepository,
    FakeFeedbackRepository,
    FakeUsageRecordRepository,
    FakeWebsiteRepository,
)


@dataclass
class AnalyticsEnv:
    websites: FakeWebsiteRepository
    sessions: FakeChatSessionRepository
    messages: FakeChatMessageRepository
    usage: FakeUsageRecordRepository
    feedback: FakeFeedbackRepository
    analytics: FakeAnalyticsRepository
    service: AnalyticsService


def build_analytics_env() -> AnalyticsEnv:
    websites = FakeWebsiteRepository()
    sessions = FakeChatSessionRepository()
    messages = FakeChatMessageRepository()
    usage = FakeUsageRecordRepository()
    feedback = FakeFeedbackRepository()
    analytics = FakeAnalyticsRepository(
        sessions=sessions, messages=messages, usage=usage, websites=websites, feedback=feedback
    )
    service = AnalyticsService(analytics=analytics)
    return AnalyticsEnv(
        websites=websites,
        sessions=sessions,
        messages=messages,
        usage=usage,
        feedback=feedback,
        analytics=analytics,
        service=service,
    )


async def seed_website(
    env: AnalyticsEnv,
    *,
    tenant_id: str,
    website_id: str = "web-1",
    name: str = "Example",
) -> Website:
    website = Website.new(tenant_id=tenant_id, name=name, url=f"https://{website_id}.test")
    website.id = website_id
    await env.websites.create(website)
    return website


async def seed_day(
    env: AnalyticsEnv,
    *,
    tenant_id: str,
    website_id: str,
    date: datetime,
    chats: int = 1,
    messages: int = 1,
    input_tokens: int = 0,
    output_tokens: int = 0,
    response_times: list[float] | None = None,
) -> None:
    """Seed one day of activity: a usage rollup, sessions, and AI messages.

    `date` is rounded to noon UTC so it never falls across a daily boundary.
    One `ChatSession` is created per `chats` and one assistant message per
    entry in `response_times`.
    """
    day = date.date().isoformat()
    await env.usage.increment(
        tenant_id=tenant_id,
        website_id=website_id,
        date=day,
        counters={
            "chats": chats,
            "messages": messages,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        },
    )
    for index in range(chats):
        session = ChatSession.new(
            tenant_id=tenant_id,
            website_id=website_id,
            session_id=f"{website_id}-{day}-{index}",
            visitor_id=f"visitor-{index}",
        )
        session.started_at = _noon(date)
        session.last_activity = _noon(date)
        await env.sessions.create(session)
    for index, response_time in enumerate(response_times or []):
        message = ChatMessage.new(
            tenant_id=tenant_id,
            website_id=website_id,
            session_id=f"{website_id}-{day}-0",
            role="assistant",
            content=f"Response {index}",
        )
        message.response_time = response_time
        message.created_at = _noon(date)
        message.input_tokens = input_tokens
        message.output_tokens = output_tokens
        await env.messages.create(message)


def _noon(date: datetime) -> datetime:
    """UTC noon of `date`, preserving the day but ignoring its time part."""
    return date.replace(hour=12, minute=0, second=0, microsecond=0)


async def seed_question(
    env: AnalyticsEnv,
    *,
    tenant_id: str,
    website_id: str,
    question: str,
    date: datetime,
    session_id: str | None = None,
) -> None:
    """Persist one user message (a "question") at UTC noon of `date`."""
    message = ChatMessage.new(
        tenant_id=tenant_id,
        website_id=website_id,
        session_id=session_id or "question-session",
        role="user",
        content=question,
    )
    message.created_at = _noon(date)
    await env.messages.create(message)


async def seed_answer(
    env: AnalyticsEnv,
    *,
    tenant_id: str,
    website_id: str,
    date: datetime,
    content: str | None = None,
    response_time: float | None = None,
    session_id: str | None = None,
) -> None:
    """Persist one assistant message (optionally the no-context fallback).

    Pass `content=UNKNOWN_ANSWER_FALLBACK` (import from backend.prompts.rag)
    to seed a fallback response for resolution metrics.
    """
    message = ChatMessage.new(
        tenant_id=tenant_id,
        website_id=website_id,
        session_id=session_id or "answer-session",
        role="assistant",
        content=content or "A helpful answer.",
    )
    message.created_at = _noon(date)
    message.response_time = response_time
    await env.messages.create(message)


async def seed_fallback(
    env: AnalyticsEnv,
    *,
    tenant_id: str,
    website_id: str,
    date: datetime,
    response_time: float | None = None,
) -> None:
    """Persist a no-context fallback assistant message."""
    await seed_answer(
        env,
        tenant_id=tenant_id,
        website_id=website_id,
        date=date,
        content=UNKNOWN_ANSWER_FALLBACK,
        response_time=response_time,
    )


async def seed_feedback(
    env: AnalyticsEnv,
    *,
    tenant_id: str,
    website_id: str,
    rating: int,
    date: datetime,
    category: str = "other",
) -> None:
    """Persist one visitor rating at UTC noon of `date`."""
    feedback = Feedback.new(
        tenant_id=tenant_id,
        website_id=website_id,
        session_id=f"feedback-session-{rating}",
        message_id=f"feedback-message-{rating}-{new_id()}",
        rating=rating,
        category=category,
    )
    feedback.created_at = _noon(date)
    await env.feedback.create(feedback)
