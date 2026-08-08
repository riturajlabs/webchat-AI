"""User data access (Protocol + MongoDB implementation)."""

from datetime import datetime
from typing import Any, Protocol

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError

from backend.core.errors import DuplicateEmailError
from backend.models.user import User


class UserRepository(Protocol):
    """Data access for the `users` collection."""

    async def create(self, user: User) -> None: ...

    async def find_by_email(self, email: str) -> User | None: ...

    async def find_by_id(self, user_id: str) -> User | None: ...

    async def set_email_verified(self, user_id: str, at: datetime) -> None: ...

    async def update_last_login(self, user_id: str, at: datetime) -> None: ...

    async def update_password(
        self, user_id: str, password_hash: str, pwd_token_version: int, at: datetime
    ) -> None: ...


class MongoUserRepository:
    """MongoDB-backed user repository. Every query is tenant-scoped where relevant."""

    def __init__(self, db: AsyncIOMotorDatabase[Any]) -> None:
        self._collection = db["users"]

    async def create(self, user: User) -> None:
        try:
            await self._collection.insert_one(user.to_doc())
        except DuplicateKeyError as exc:
            # Two concurrent registrations can both pass the pre-check in the
            # service; the unique `users.email` index is the source of truth.
            raise DuplicateEmailError("An account with this email already exists.") from exc

    async def find_by_email(self, email: str) -> User | None:
        doc = await self._collection.find_one({"email": email})
        return User.from_doc(doc) if doc else None

    async def find_by_id(self, user_id: str) -> User | None:
        doc = await self._collection.find_one({"_id": user_id})
        return User.from_doc(doc) if doc else None

    async def set_email_verified(self, user_id: str, at: datetime) -> None:
        await self._collection.update_one(
            {"_id": user_id},
            {"$set": {"email_verified": True, "updated_at": at}},
        )

    async def update_last_login(self, user_id: str, at: datetime) -> None:
        await self._collection.update_one(
            {"_id": user_id},
            {"$set": {"last_login": at, "updated_at": at}},
        )

    async def update_password(
        self, user_id: str, password_hash: str, pwd_token_version: int, at: datetime
    ) -> None:
        await self._collection.update_one(
            {"_id": user_id},
            {
                "$set": {
                    "password_hash": password_hash,
                    "pwd_token_version": pwd_token_version,
                    "updated_at": at,
                }
            },
        )
