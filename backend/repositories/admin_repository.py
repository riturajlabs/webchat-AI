"""Platform-wide admin read repository (Phase 12.5, ADR-006).

Read-only aggregations for the admin `GET /api/admin/stats` endpoint. Like the
analytics repository it reports over existing collections only - no new write
path - but deliberately *unscoped*: these are platform KPIs and are reachable
only through the admin router (`role=admin`). No tenant filter is applied here
by design (00-AI-Development-Rules §7 is enforced at the router boundary for
tenant-facing data; this surface has no tenant).
"""

from dataclasses import dataclass
from typing import Any, Protocol

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.models.crawl_job import CRAWL_ACTIVE_STATUSES, CRAWL_STATUS_FAILED


@dataclass(frozen=True)
class PlatformStats:
    """Aggregated platform KPIs backing the admin overview."""

    total_tenants: int
    active_tenants: int
    suspended_tenants: int
    total_users: int
    active_users: int
    suspended_users: int
    total_conversations: int
    total_messages: int
    total_input_tokens: int
    total_output_tokens: int
    total_crawl_jobs: int
    active_crawl_jobs: int
    failed_crawl_jobs: int


class AdminRepository(Protocol):
    """Platform-wide read-only stats (admin only)."""

    async def platform_stats(self) -> PlatformStats: ...


class MongoAdminRepository:
    """MongoDB-backed admin stats over `tenants`, `users`, `usage_records`,
    `chat_sessions` and `crawl_jobs`."""

    def __init__(self, db: AsyncIOMotorDatabase[Any]) -> None:
        self._tenants = db["tenants"]
        self._users = db["users"]
        self._usage = db["usage_records"]
        self._sessions = db["chat_sessions"]
        self._crawl_jobs = db["crawl_jobs"]

    async def platform_stats(self) -> PlatformStats:
        total_tenants = await self._tenants.count_documents({})
        active_tenants = await self._tenants.count_documents({"status": "active"})
        suspended_tenants = await self._tenants.count_documents({"status": "suspended"})
        total_users = await self._users.count_documents({})
        active_users = await self._users.count_documents({"status": "active"})
        suspended_users = await self._users.count_documents({"status": "suspended"})

        usage_doc = await self._first(
            self._usage.aggregate(
                [
                    {
                        "$group": {
                            "_id": None,
                            "conversations": {"$sum": "$counters.chats"},
                            "messages": {"$sum": "$counters.messages"},
                            "input_tokens": {"$sum": "$counters.input_tokens"},
                            "output_tokens": {"$sum": "$counters.output_tokens"},
                        }
                    },
                ]
            )
        )

        total_crawl_jobs = await self._crawl_jobs.count_documents({})
        active_crawl_jobs = await self._crawl_jobs.count_documents(
            {"status": {"$in": sorted(CRAWL_ACTIVE_STATUSES)}}
        )
        failed_crawl_jobs = await self._crawl_jobs.count_documents({"status": CRAWL_STATUS_FAILED})

        return PlatformStats(
            total_tenants=total_tenants,
            active_tenants=active_tenants,
            suspended_tenants=suspended_tenants,
            total_users=total_users,
            active_users=active_users,
            suspended_users=suspended_users,
            total_conversations=int(usage_doc.get("conversations", 0)) if usage_doc else 0,
            total_messages=int(usage_doc.get("messages", 0)) if usage_doc else 0,
            total_input_tokens=int(usage_doc.get("input_tokens", 0)) if usage_doc else 0,
            total_output_tokens=int(usage_doc.get("output_tokens", 0)) if usage_doc else 0,
            total_crawl_jobs=total_crawl_jobs,
            active_crawl_jobs=active_crawl_jobs,
            failed_crawl_jobs=failed_crawl_jobs,
        )

    @staticmethod
    async def _first(cursor: Any) -> dict[str, Any] | None:
        async for doc in cursor:
            return dict(doc)
        return None


__all__ = ["AdminRepository", "MongoAdminRepository", "PlatformStats"]
