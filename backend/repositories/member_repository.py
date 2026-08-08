"""Membership data access (Protocol + MongoDB implementation)."""

from typing import Any, Protocol

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.models.member import Member


class MemberRepository(Protocol):
    """Data access for the `members` collection."""

    async def create(self, member: Member) -> None: ...

    async def find_by_user_id(self, user_id: str) -> Member | None: ...


class MongoMemberRepository:
    """MongoDB-backed member repository."""

    def __init__(self, db: AsyncIOMotorDatabase[Any]) -> None:
        self._collection = db["members"]

    async def create(self, member: Member) -> None:
        await self._collection.insert_one(member.to_doc())

    async def find_by_user_id(self, user_id: str) -> Member | None:
        doc = await self._collection.find_one({"user_id": user_id})
        return Member.from_doc(doc) if doc else None
