"""Conversation management business logic (Phase 11.2).

Routes validate and translate; this service owns every workflow: paginated
listing (with optional content search and website filter), detail retrieval
with the full chronological history, and safe deletion (soft-delete the
session, purge its messages, and record an audit entry). All database access
is tenant-scoped by the caller-provided `tenant_id`, never by request input
(00-AI-Development-Rules §7).

`ConversationService` only depends on repository Protocols, keeping the
service layer free of FastAPI imports (layering rules §6).
"""

from dataclasses import dataclass
from datetime import datetime

from backend.core.errors import SessionNotFoundError
from backend.models.audit_log import AUDIT_CONVERSATION_DELETED, AuditLog
from backend.models.chat_message import CHAT_ROLE_ASSISTANT, ChatMessage
from backend.models.chat_session import ChatSession
from backend.repositories.audit_log_repository import AuditLogRepository
from backend.repositories.chat_message_repository import ChatMessageRepository, MessageSummary
from backend.repositories.chat_session_repository import ChatSessionRepository

# Derived conversation state (docs/04, Phase 11.2 UI status column):
# the last turn decides whether the conversation is awaiting an answer.
CONVERSATION_STATUS_ANSWERED = "answered"
CONVERSATION_STATUS_AWAITING = "awaiting"

_MAX_TITLE_CHARS = 80
_MAX_PREVIEW_CHARS = 140
_NEW_CONVERSATION_TITLE = "New conversation"


@dataclass(frozen=True)
class ConversationSummaryItem:
    id: str
    website_id: str
    visitor_id: str | None
    title: str
    message_count: int
    last_message: str
    status: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ConversationDetailItem:
    id: str
    website_id: str
    visitor_id: str | None
    title: str
    status: str
    created_at: datetime
    updated_at: datetime
    messages: list[ChatMessage]


class ConversationService:
    """Encapsulates every conversation-management workflow (read/delete)."""

    def __init__(
        self,
        *,
        sessions: ChatSessionRepository,
        messages: ChatMessageRepository,
        audit: AuditLogRepository,
    ) -> None:
        self._sessions = sessions
        self._messages = messages
        self._audit = audit

    # ------------------------------------------------------------------ flows

    async def list_conversations(
        self,
        tenant_id: str,
        *,
        page: int,
        per_page: int,
        search: str | None = None,
        website_id: str | None = None,
    ) -> tuple[list[ConversationSummaryItem], int]:
        """Return (page items, total matching count) for the tenant.

        `search` matches message content (case-insensitive); `website_id`
        narrows to one website. Conversations are ordered by most recent
        activity, newest first.
        """
        query = search.strip() if search else None
        session_ids: list[str] | None = None
        if query:
            session_ids = await self._messages.search_session_ids(
                tenant_id, query=query, website_id=website_id
            )
            if not session_ids:
                return [], 0

        sessions = await self._sessions.list_by_tenant(
            tenant_id,
            website_id=website_id,
            session_ids=session_ids,
            limit=per_page,
            offset=(page - 1) * per_page,
        )
        total = await self._sessions.count_by_tenant(
            tenant_id, website_id=website_id, session_ids=session_ids
        )
        if not sessions:
            return [], total

        summaries = await self._messages.summarize_sessions(
            tenant_id, [session.session_id for session in sessions]
        )
        items = [
            self._summary_item(session, summaries.get(session.session_id)) for session in sessions
        ]
        return items, total

    async def get_conversation(self, tenant_id: str, session_id: str) -> ConversationDetailItem:
        session = await self._sessions.find_by_session_id(tenant_id, session_id)
        if session is None:
            raise SessionNotFoundError("Conversation not found.")
        messages = await self._messages.list_by_session(tenant_id, session_id)
        return ConversationDetailItem(
            id=session.session_id,
            website_id=session.website_id,
            visitor_id=session.visitor_id,
            title=self._title(messages),
            status=_status_from_last_role(messages[-1].role if messages else None),
            created_at=session.started_at,
            updated_at=session.last_activity,
            messages=messages,
        )

    async def delete_conversation(
        self,
        tenant_id: str,
        session_id: str,
        *,
        user_id: str | None,
        ip_address: str | None,
        user_agent: str | None,
    ) -> None:
        """Soft-delete a conversation and purge its messages.

        The session row is marked `deleted` (excluded from every read path, see
        `MongoChatSessionRepository`); its messages are hard-removed so the chat
        content is gone immediately. The action is recorded in the tenant's
        audit log, mirroring `WebsiteService.delete_website`.
        """
        deleted = await self._sessions.delete(tenant_id, session_id)
        if not deleted:
            raise SessionNotFoundError("Conversation not found.")
        # Cascade: never leave orphaned messages behind after the session goes.
        await self._messages.delete_by_session(tenant_id, session_id)
        await self._audit.create(
            AuditLog.new(
                action=AUDIT_CONVERSATION_DELETED,
                tenant_id=tenant_id,
                user_id=user_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

    # ------------------------------------------------------------- internals

    def _summary_item(
        self, session: ChatSession, summary: MessageSummary | None
    ) -> ConversationSummaryItem:
        if summary is None:
            return ConversationSummaryItem(
                id=session.session_id,
                website_id=session.website_id,
                visitor_id=session.visitor_id,
                title=_NEW_CONVERSATION_TITLE,
                message_count=0,
                last_message="",
                status=CONVERSATION_STATUS_AWAITING,
                created_at=session.started_at,
                updated_at=session.last_activity,
            )
        return ConversationSummaryItem(
            id=session.session_id,
            website_id=session.website_id,
            visitor_id=session.visitor_id,
            title=_truncate(summary.first_content or _NEW_CONVERSATION_TITLE, _MAX_TITLE_CHARS),
            message_count=summary.message_count,
            last_message=_truncate(summary.last_content, _MAX_PREVIEW_CHARS),
            status=_status_from_last_role(summary.last_role),
            created_at=session.started_at,
            updated_at=session.last_activity,
        )

    @staticmethod
    def _title(messages: list[ChatMessage]) -> str:
        first = next((m for m in messages if m.role == "user"), messages[0] if messages else None)
        return _truncate(first.content if first else _NEW_CONVERSATION_TITLE, _MAX_TITLE_CHARS)


def _status_from_last_role(last_role: str | None) -> str:
    if last_role == CHAT_ROLE_ASSISTANT:
        return CONVERSATION_STATUS_ANSWERED
    return CONVERSATION_STATUS_AWAITING


def _truncate(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1].rstrip()}…"


__all__ = [
    "CONVERSATION_STATUS_ANSWERED",
    "CONVERSATION_STATUS_AWAITING",
    "ConversationDetailItem",
    "ConversationService",
    "ConversationSummaryItem",
]
