"""Shared helpers for building a fake-backed ConversationService test environment."""

from dataclasses import dataclass
from datetime import datetime

from backend.models.chat_message import ChatMessage
from backend.models.chat_session import ChatSession
from backend.services.conversations import ConversationService

from tests.fakes import (
    FakeAuditLogRepository,
    FakeChatMessageRepository,
    FakeChatSessionRepository,
)

_ASSISTANT_SOURCE = {
    "url": "https://example.com/page",
    "title": "Page",
    "score": 0.9,
    "citation": 1,
}


@dataclass
class ConversationEnv:
    sessions: FakeChatSessionRepository
    messages: FakeChatMessageRepository
    audit: FakeAuditLogRepository
    service: ConversationService


def build_conversation_env() -> ConversationEnv:
    sessions = FakeChatSessionRepository()
    messages = FakeChatMessageRepository()
    audit = FakeAuditLogRepository()
    service = ConversationService(sessions=sessions, messages=messages, audit=audit)
    return ConversationEnv(sessions=sessions, messages=messages, audit=audit, service=service)


async def seed_conversation(
    env: ConversationEnv,
    *,
    tenant_id: str,
    session_id: str,
    website_id: str = "web-1",
    visitor_id: str = "visitor-1",
    turns: list[tuple[str, str]] | None = None,
    last_activity: datetime | None = None,
) -> str:
    """Seed one conversation with a session and (optionally) message turns.

    Turns are `(role, content)` pairs in chronological order. Assistant turns
    get deterministic sources/token/latency so detail tests can assert them.
    """
    session = ChatSession.new(
        tenant_id=tenant_id,
        website_id=website_id,
        session_id=session_id,
        visitor_id=visitor_id,
    )
    if last_activity is not None:
        session.last_activity = last_activity
    await env.sessions.create(session)

    for role, content in turns or []:
        message = ChatMessage.new(
            tenant_id=tenant_id,
            website_id=website_id,
            session_id=session_id,
            role=role,
            content=content,
        )
        if role == "assistant":
            message.sources = [_ASSISTANT_SOURCE]
            message.response_time = 1.25
            message.input_tokens = 100
            message.output_tokens = 50
        await env.messages.create(message)
    return session_id
