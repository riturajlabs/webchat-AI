"""Chat message data access (Phase 6, Protocol + MongoDB implementation).

Every query is tenant-scoped (00-AI-Development-Rules.md §7). `list_recent`
returns the most recent `limit` turns in chronological order - exactly the
shape the conversation-memory prompt wants (oldest first, docs/05 §10). The
query sorts `created_at` DESCENDING, applies the limit, then reverses the
result, so memory always reflects the latest turns of a session.

Phase 11.2 conversation management adds the read/delete surfaces: a full
chronological dump (`list_by_session`), a per-session rollup for list views
(`summarize_sessions`), content search (`search_session_ids`), and cascade
deletion (`delete_by_session`). All remain tenant-scoped.
"""

import re
from datetime import datetime
from typing import Any, Protocol

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING

from backend.models.chat_message import ChatMessage


class MessageSummary:
    """Per-session rollup used by the conversation list (Phase 11.2)."""

    def __init__(
        self,
        *,
        message_count: int,
        first_content: str,
        last_content: str,
        last_role: str,
        last_created_at: datetime | None = None,
        total_input_tokens: int = 0,
        total_output_tokens: int = 0,
        max_response_time: float | None = None,
    ) -> None:
        self.message_count = message_count
        self.first_content = first_content
        self.last_content = last_content
        self.last_role = last_role
        self.last_created_at = last_created_at
        self.total_input_tokens = total_input_tokens
        self.total_output_tokens = total_output_tokens
        self.max_response_time = max_response_time


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

    async def list_by_session(self, tenant_id: str, session_id: str) -> list[ChatMessage]: ...

    async def summarize_sessions(
        self, tenant_id: str, session_ids: list[str]
    ) -> dict[str, MessageSummary]: ...

    async def search_session_ids(
        self,
        tenant_id: str,
        *,
        query: str,
        website_id: str | None = None,
        limit: int = 500,
    ) -> list[str]: ...

    async def delete_by_session(self, tenant_id: str, session_id: str) -> int: ...


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

    async def list_by_session(self, tenant_id: str, session_id: str) -> list[ChatMessage]:
        cursor = (
            self._collection.find({"tenant_id": tenant_id, "session_id": session_id})
            .sort("created_at", ASCENDING)
        )
        return [ChatMessage.from_doc(doc) async for doc in cursor]

    async def summarize_sessions(
        self, tenant_id: str, session_ids: list[str]
    ) -> dict[str, MessageSummary]:
        """Roll up message counts, first/last turns, and usage per session.

        The documents are sorted chronologically before grouping so `$first` /
        `$last` reliably capture the oldest and newest turns of each session.
        """
        if not session_ids:
            return {}
        pipeline: list[dict[str, Any]] = [
            {"$match": {"tenant_id": tenant_id, "session_id": {"$in": session_ids}}},
            {"$sort": {"created_at": ASCENDING}},
            {
                "$group": {
                    "_id": "$session_id",
                    "message_count": {"$sum": 1},
                    "first_content": {"$first": "$content"},
                    "last_content": {"$last": "$content"},
                    "last_role": {"$last": "$role"},
                    "last_created_at": {"$last": "$created_at"},
                    "total_input_tokens": {"$sum": "$input_tokens"},
                    "total_output_tokens": {"$sum": "$output_tokens"},
                    "max_response_time": {"$max": "$response_time"},
                }
            },
        ]
        cursor = self._collection.aggregate(pipeline)
        summaries: dict[str, MessageSummary] = {}
        async for doc in cursor:
            summaries[str(doc["_id"])] = MessageSummary(
                message_count=int(doc.get("message_count", 0)),
                first_content=str(doc.get("first_content") or ""),
                last_content=str(doc.get("last_content") or ""),
                last_role=str(doc.get("last_role") or ""),
                last_created_at=doc.get("last_created_at"),
                total_input_tokens=int(doc.get("total_input_tokens", 0)),
                total_output_tokens=int(doc.get("total_output_tokens", 0)),
                max_response_time=doc.get("max_response_time"),
            )
        return summaries

    async def search_session_ids(
        self,
        tenant_id: str,
        *,
        query: str,
        website_id: str | None = None,
        limit: int = 500,
    ) -> list[str]:
        """Return session ids whose message content contains `query`.

        The query is regex-escaped so user input cannot inject match operators
        (defense-in-depth alongside Pydantic validation).
        """
        match: dict[str, Any] = {
            "tenant_id": tenant_id,
            "content": {"$regex": re.escape(query), "$options": "i"},
        }
        if website_id is not None:
            match["website_id"] = website_id
        cursor = self._collection.find(match, {"session_id": 1}).limit(limit)
        return list({str(doc["session_id"]) async for doc in cursor})

    async def delete_by_session(self, tenant_id: str, session_id: str) -> int:
        result = await self._collection.delete_many(
            {"tenant_id": tenant_id, "session_id": session_id}
        )
        return result.deleted_count


__all__ = ["ChatMessageRepository", "MessageSummary", "MongoChatMessageRepository"]
