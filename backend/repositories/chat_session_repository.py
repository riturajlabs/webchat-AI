"""Chat session data access (Phase 6, Protocol + MongoDB implementation).

`session_id` is the unique conversation key (docs/05 §9); `tenant_id` scopes
every query (00-AI-Development-Rules.md §7), so a foreign tenant can never
attach messages to, or resume, another tenant's session. Creates are
idempotent: a duplicate `session_id` converges to a `last_activity` touch
instead of erroring, mirroring the knowledge-chunk upsert pattern.
"""

from typing import Any, Protocol

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import DESCENDING
from pymongo.errors import DuplicateKeyError

from backend.core.security import utcnow
from backend.models.chat_session import CHAT_SESSION_STATUS_DELETED, ChatSession

# Deleted sessions are invisible to every read path (list/get/detail), mirroring
# the website soft-delete pattern. `find_by_session_id` also excludes them, so a
# deleted conversation can never be resumed by the widget chat flow either.
_NOT_DELETED = {"status": {"$ne": CHAT_SESSION_STATUS_DELETED}}


class ChatSessionRepository(Protocol):
    """Data access for the `chat_sessions` collection (tenant-scoped)."""

    async def create(self, session: ChatSession) -> None: ...

    async def find_by_session_id(self, tenant_id: str, session_id: str) -> ChatSession | None: ...

    async def touch(self, session_id: str) -> None: ...

    async def list_by_website(
        self,
        tenant_id: str,
        website_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ChatSession]: ...

    async def count_by_website(self, tenant_id: str, website_id: str) -> int: ...

    async def list_by_tenant(
        self,
        tenant_id: str,
        *,
        website_id: str | None = None,
        session_ids: list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ChatSession]: ...

    async def count_by_tenant(
        self,
        tenant_id: str,
        *,
        website_id: str | None = None,
        session_ids: list[str] | None = None,
    ) -> int: ...

    async def delete(self, tenant_id: str, session_id: str) -> bool: ...


class MongoChatSessionRepository:
    """MongoDB-backed chat session repository."""

    def __init__(self, db: AsyncIOMotorDatabase[Any]) -> None:
        self._collection = db["chat_sessions"]

    async def create(self, session: ChatSession) -> None:
        try:
            await self._collection.insert_one(session.to_doc())
        except DuplicateKeyError:
            # Race: a concurrent request created the same `session_id` first;
            # converging to a touch keeps the existing record authoritative.
            await self._collection.update_one(
                {"_id": session.id},
                {"$set": {"last_activity": session.last_activity}},
            )

    async def find_by_session_id(self, tenant_id: str, session_id: str) -> ChatSession | None:
        doc = await self._collection.find_one(
            {"session_id": session_id, "tenant_id": tenant_id, **_NOT_DELETED}
        )
        return ChatSession.from_doc(doc) if doc else None

    async def touch(self, session_id: str) -> None:
        await self._collection.update_one(
            {"session_id": session_id},
            {"$set": {"last_activity": utcnow()}},
        )

    async def list_by_website(
        self,
        tenant_id: str,
        website_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ChatSession]:
        cursor = (
            self._collection.find(
                {"tenant_id": tenant_id, "website_id": website_id, **_NOT_DELETED}
            )
            .sort("last_activity", DESCENDING)
            .skip(offset)
            .limit(limit)
        )
        return [ChatSession.from_doc(doc) async for doc in cursor]

    async def count_by_website(self, tenant_id: str, website_id: str) -> int:
        return await self._collection.count_documents(
            {"tenant_id": tenant_id, "website_id": website_id, **_NOT_DELETED}
        )

    async def list_by_tenant(
        self,
        tenant_id: str,
        *,
        website_id: str | None = None,
        session_ids: list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ChatSession]:
        query: dict[str, Any] = {"tenant_id": tenant_id, **_NOT_DELETED}
        if website_id is not None:
            query["website_id"] = website_id
        if session_ids is not None:
            # An empty list matches nothing (search with zero hits).
            query["session_id"] = {"$in": session_ids}
        cursor = (
            self._collection.find(query)
            .sort("last_activity", DESCENDING)
            .skip(offset)
            .limit(limit)
        )
        return [ChatSession.from_doc(doc) async for doc in cursor]

    async def count_by_tenant(
        self,
        tenant_id: str,
        *,
        website_id: str | None = None,
        session_ids: list[str] | None = None,
    ) -> int:
        query: dict[str, Any] = {"tenant_id": tenant_id, **_NOT_DELETED}
        if website_id is not None:
            query["website_id"] = website_id
        if session_ids is not None:
            query["session_id"] = {"$in": session_ids}
        return await self._collection.count_documents(query)

    async def delete(self, tenant_id: str, session_id: str) -> bool:
        """Soft-delete a session (Phase 11.2, mirrors `websites.status`).

        The row is preserved as a tombstone (status `deleted`) so it is excluded
        from every read path and cannot be resumed, while `messages` are purged
        by the caller for immediate content removal. Returns whether a live
        session was actually marked deleted.
        """
        result = await self._collection.update_one(
            {"session_id": session_id, "tenant_id": tenant_id, **_NOT_DELETED},
            {"$set": {"status": CHAT_SESSION_STATUS_DELETED}},
        )
        return result.modified_count > 0


__all__ = ["ChatSessionRepository", "MongoChatSessionRepository"]
