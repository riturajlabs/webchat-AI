"""Chat message data access (Phase 6, Protocol + MongoDB implementation).

Every query is tenant-scoped (00-AI-Development-Rules.md §7). `list_recent`
returns the most recent `limit` turns in chronological order - exactly the
shape the conversation-memory prompt wants (oldest first, docs/05 §10). The
query sorts `created_at` DESCENDING, applies the limit, then reverses the
result, so memory always reflects the latest turns of a session.
"""

from typing import Any, Protocol

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import DESCENDING

from backend.models.chat_message import ChatMessage


class ChatMessageRepository(Protocol):
    """Data access for the `messages` collection (tenant-scoped)."""

    async def create(self, message: ChatMessage) -> None: ...

    async def list_recent(
        self,
        tenant_id: str,
        session_id: str,
        *,
        limit: int = 20,
    ) -> list[ChatMessage]: ...

    async def count_by_session(self, tenant_id: str, session_id: str) -> int: ...


class MongoChatMessageRepository:
    """MongoDB-backed chat message repository."""

    def __init__(self, db: AsyncIOMotorDatabase[Any]) -> None:
        self._collection = db["messages"]

    async def create(self, message: ChatMessage) -> None:
        await self._collection.insert_one(message.to_doc())

    async def list_recent(
        self,
        tenant_id: str,
        session_id: str,
        *,
        limit: int = 20,
    ) -> list[ChatMessage]:
        # Newest first, then cut to the last `limit` turns and reverse so the
        # result is chronological (oldest -> newest), ready for the prompt.
        cursor = (
            self._collection.find({"tenant_id": tenant_id, "session_id": session_id})
            .sort("created_at", DESCENDING)
            .limit(limit)
        )
        messages = [ChatMessage.from_doc(doc) async for doc in cursor]
        messages.reverse()
        return messages

    async def count_by_session(self, tenant_id: str, session_id: str) -> int:
        return await self._collection.count_documents(
            {"tenant_id": tenant_id, "session_id": session_id}
        )


__all__ = ["ChatMessageRepository", "MongoChatMessageRepository"]
