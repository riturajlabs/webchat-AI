"""User data access (Protocol + MongoDB implementation).

Phase 12.5 adds the admin-facing `list_users`/`count_users`/`count_by_tenant`/
`set_status` surface (ADR-006). These queries are platform-wide by design and
are consumed only through the admin service/router (`role=admin`).
"""

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

    # Phase 12.5 admin surface (ADR-006).
    async def list_users(
        self,
        *,
        search: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[User]: ...

    async def count_users(self, *, search: str | None = None, status: str | None = None) -> int: ...

    async def count_by_tenant(self, tenant_id: str) -> int: ...

    async def set_status(self, user_id: str, status: str, at: datetime) -> None: ...

    async def increment_failed_login(self, user_id: str, at: datetime) -> None: ...

    async def reset_failed_login(self, user_id: str, at: datetime) -> None: ...

    async def lock_account(self, user_id: str, until: datetime, at: datetime) -> None: ...


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

    async def list_users(
        self,
        *,
        search: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[User]:
        query = self._query(search=search, status=status)
        cursor = self._collection.find(query).sort("created_at", -1).skip(offset).limit(limit)
        return [User.from_doc(doc) async for doc in cursor]

    async def count_users(self, *, search: str | None = None, status: str | None = None) -> int:
        return await self._collection.count_documents(self._query(search=search, status=status))

    async def count_by_tenant(self, tenant_id: str) -> int:
        return await self._collection.count_documents({"tenant_id": tenant_id})

    async def set_status(self, user_id: str, status: str, at: datetime) -> None:
        await self._collection.update_one(
            {"_id": user_id},
            {"$set": {"status": status, "updated_at": at}},
        )

    async def increment_failed_login(self, user_id: str, at: datetime) -> None:
        await self._collection.update_one(
            {"_id": user_id},
            {"$inc": {"failed_login_attempts": 1}, "$set": {"updated_at": at}},
        )

    async def reset_failed_login(self, user_id: str, at: datetime) -> None:
        await self._collection.update_one(
            {"_id": user_id},
            {"$set": {"failed_login_attempts": 0, "locked_until": None, "updated_at": at}},
        )

    async def lock_account(self, user_id: str, until: datetime, at: datetime) -> None:
        await self._collection.update_one(
            {"_id": user_id},
            {"$set": {"locked_until": until, "updated_at": at}},
        )

    @staticmethod
    def _query(*, search: str | None, status: str | None) -> dict[str, Any]:
        query: dict[str, Any] = {}
        if search:
            query["$or"] = [
                {"name": {"$regex": search, "$options": "i"}},
                {"email": {"$regex": search, "$options": "i"}},
            ]
        if status is not None:
            query["status"] = status
        return query
