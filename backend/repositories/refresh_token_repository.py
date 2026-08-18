"""Refresh token data access (Protocol + MongoDB implementation)."""

from datetime import datetime
from typing import Any, Protocol

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.models.refresh_token import RefreshToken


class TokenConsumeResult:
    """Result of an atomic token consumption operation."""

    __slots__ = ("found", "already_revoked", "token")

    def __init__(
        self,
        *,
        found: bool,
        already_revoked: bool = False,
        token: RefreshToken | None = None,
    ) -> None:
        self.found = found
        self.already_revoked = already_revoked
        self.token = token


class RefreshTokenRepository(Protocol):
    """Data access for the `refresh_tokens` collection."""

    async def create(self, token: RefreshToken) -> None: ...

    async def find_by_hash(self, token_hash: str) -> RefreshToken | None: ...

    async def find_and_consume(
        self, token_hash: str, *, replaced_by: str, at: datetime
    ) -> TokenConsumeResult: ...

    async def revoke_token(self, token_hash: str, at: datetime) -> bool: ...

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

    async def find_and_consume(
        self, token_hash: str, *, replaced_by: str, at: datetime
    ) -> TokenConsumeResult:
        """Atomically find a non-revoked token by hash and mark it revoked.

        Uses ``findOneAndUpdate`` with an ``is_revoked`` guard so that two
        concurrent refresh requests for the same token will never both succeed
        — exactly one wins the race; the other receives ``already_revoked=True``.
        """
        doc = await self._collection.find_one_and_update(
            {"token_hash": token_hash, "revoked_at": None},
            {"$set": {"revoked_at": at, "replaced_by": replaced_by}},
            return_document=True,
        )
        if doc is not None:
            token = RefreshToken.from_doc(doc)
            return TokenConsumeResult(found=True, already_revoked=False, token=token)
        # Token not found or already revoked — determine which.
        raw = await self._collection.find_one({"token_hash": token_hash})
        if raw is None:
            return TokenConsumeResult(found=False)
        token = RefreshToken.from_doc(raw)
        return TokenConsumeResult(found=True, already_revoked=True, token=token)

    async def revoke_token(self, token_hash: str, at: datetime) -> bool:
        """Revoke a single token by its hash. Returns True if the token was
        found and revoked (was not already revoked)."""
        result = await self._collection.update_one(
            {"token_hash": token_hash, "revoked_at": None},
            {"$set": {"revoked_at": at}},
        )
        return result.modified_count > 0

    async def revoke_all_for_user(self, user_id: str, at: datetime) -> None:
        await self._collection.update_many(
            {"user_id": user_id, "revoked_at": None},
            {"$set": {"revoked_at": at}},
        )
