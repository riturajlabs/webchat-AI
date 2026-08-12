"""Shared helpers for building a fake-backed FeedbackService test environment.

Mirrors the analytics helper pattern: `FeedbackService` runs over the same
fake repositories the widget submit path and dashboard read path use, so API
tests exercise the service + routing + RBAC without a database.
"""

from dataclasses import dataclass

from backend.models.chat_message import ChatMessage
from backend.services.feedback.feedback_service import FeedbackService

from tests.fakes import FakeChatMessageRepository, FakeFeedbackRepository


@dataclass
class FeedbackEnv:
    messages: FakeChatMessageRepository
    feedback: FakeFeedbackRepository
    service: FeedbackService


def build_feedback_env() -> FeedbackEnv:
    messages = FakeChatMessageRepository()
    feedback = FakeFeedbackRepository()
    service = FeedbackService(feedback=feedback, messages=messages)
    return FeedbackEnv(messages=messages, feedback=feedback, service=service)


async def seed_assistant_message(
    env: FeedbackEnv,
    *,
    tenant_id: str,
    message_id: str,
    website_id: str = "web-1",
    session_id: str = "session-1",
    content: str = "Hello world!",
) -> ChatMessage:
    message = ChatMessage.new(
        tenant_id=tenant_id,
        website_id=website_id,
        session_id=session_id,
        role="assistant",
        content=content,
    )
    message.id = message_id
    await env.messages.create(message)
    return message
