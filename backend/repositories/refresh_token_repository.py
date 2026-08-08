"""Refresh token data access (Protocol + MongoDB implementation)."""

from datetime import datetime
from typing import Any, Protocol

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.models.refresh_token import RefreshToken


class RefreshTokenRepository(Protocol):
    """Data access for the `refresh_tokens` collection."""

    async def create(self, token: RefreshToken) -> None: ...

    async def find_by_hash(self, token_hash: str) -> RefreshToken | None: ...

    async def mark_revoked(self, token_id: str, replaced_by: str | None, at: datetime) -> None: ...

    async def revoke_all_for_user(self, user_id: str, at: datetime) -> None: ...


class MongoRefreshTokenRepository:
    """MongoDB-backed refresh token repository."""

    def __init__(self, db: AsyncIOMotorDatabase[Any]) -> None:
        self._collection = db["refresh_tokens"]

    async def create(self, token: RefreshToken) -> None:
        await self._collection.insert_one(token.to_doc())

    async def find_by_hash(self, token_hash: str) -> RefreshToken | None:
        doc = await self._collection.find_one({"token_hash": token_hash})
        return RefreshToken.from_doc(doc) if doc else None

    async def mark_revoked(self, token_id: str, replaced_by: str | None, at: datetime) -> None:
        await self._collection.update_one(
            {"_id": token_id},
            {"$set": {"revoked_at": at, "replaced_by": replaced_by}},
        )

    async def revoke_all_for_user(self, user_id: str, at: datetime) -> None:
        await self._collection.update_many(
            {"user_id": user_id, "revoked_at": None},
            {"$set": {"revoked_at": at}},
        )
