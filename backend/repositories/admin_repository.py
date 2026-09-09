"""Platform-wide admin read repository (Phase 12.5, ADR-006).

Read-only aggregations for the admin `GET /api/admin/stats` endpoint. Like the
analytics repository it reports over existing collections only - no new write
path - but deliberately *unscoped*: these are platform KPIs and are reachable
only through the admin router (`role=admin`). No tenant filter is applied here
by design (00-AI-Development-Rules §7 is enforced at the router boundary for
tenant-facing data; this surface has no tenant).
"""

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol, cast

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


@dataclass(frozen=True)
class PlatformUsage:
    """All-time usage rollups across the platform (Phase 15 `GET /api/admin/usage`).

    `counters` is the full daily-rollup counter set (ADR-005 §5.5), so the
    SaaS operations panel can show more than the overview's headline numbers.
    """

    conversations: int
    messages: int
    input_tokens: int
    output_tokens: int
    embeddings_created: int
    vector_queries: int
    crawl_pages: int

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class CollectionCounts:
    """Row counts per collection for the system page (Phase 15)."""

    users: int
    tenants: int
    websites: int
    widgets: int
    documents: int
    chat_sessions: int
    messages: int
    usage_records: int
    api_keys: int
    subscriptions: int
    audit_logs: int
    admin_audit_logs: int


class AdminRepository(Protocol):
    """Platform-wide read-only stats (admin only)."""

    async def platform_stats(self) -> PlatformStats: ...

    async def usage_totals(self) -> PlatformUsage: ...

    async def collection_counts(self) -> CollectionCounts: ...


class MongoAdminRepository:
    """MongoDB-backed admin stats over `tenants`, `users`, `usage_records`,
    `chat_sessions` and `crawl_jobs`."""

    def __init__(self, db: AsyncIOMotorDatabase[Any]) -> None:
        self._tenants = db["tenants"]
        self._users = db["users"]
        self._usage = db["usage_records"]
        self._sessions = db["chat_sessions"]
        self._crawl_jobs = db["crawl_jobs"]
        self._websites = db["websites"]
        self._widgets = db["widgets"]
        self._documents = db["documents"]
        self._messages = db["messages"]
        self._api_keys = db["api_keys"]
        self._subscriptions = db["subscriptions"]
        self._audit_logs = db["audit_logs"]
        self._admin_audit_logs = db["admin_audit_logs"]

    async def platform_stats(self) -> PlatformStats:
        # PERF-K02: the 10 counts were issued sequentially (10 round trips).
        # Firing them together collapses the admin overview to a single network
        # wait; `asyncio.gather` propagates the first failure exactly like the
        # sequential awaits did (no fail-open behavior change).
        (
            total_tenants,
            active_tenants,
            suspended_tenants,
            total_users,
            active_users,
            suspended_users,
            total_crawl_jobs,
            active_crawl_jobs,
            failed_crawl_jobs,
            usage_doc,
        ) = cast(
            tuple[
                int,
                int,
                int,
                int,
                int,
                int,
                int,
                int,
                int,
                dict[str, Any] | None,
            ],
            await asyncio.gather(
                self._tenants.count_documents({}),
                self._tenants.count_documents({"status": "active"}),
                self._tenants.count_documents({"status": "suspended"}),
                self._users.count_documents({}),
                self._users.count_documents({"status": "active"}),
                self._users.count_documents({"status": "suspended"}),
                self._crawl_jobs.count_documents({}),
                self._crawl_jobs.count_documents(
                    {"status": {"$in": sorted(CRAWL_ACTIVE_STATUSES)}}
                ),
                self._crawl_jobs.count_documents({"status": CRAWL_STATUS_FAILED}),
                self._first(
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
                ),
            ),
        )

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

    async def usage_totals(self) -> PlatformUsage:
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
                            "embeddings_created": {"$sum": "$counters.embeddings_created"},
                            "vector_queries": {"$sum": "$counters.vector_queries"},
                            "crawl_pages": {"$sum": "$counters.crawl_pages"},
                        }
                    },
                ]
            )
        )
        return PlatformUsage(
            conversations=int(usage_doc.get("conversations", 0)) if usage_doc else 0,
            messages=int(usage_doc.get("messages", 0)) if usage_doc else 0,
            input_tokens=int(usage_doc.get("input_tokens", 0)) if usage_doc else 0,
            output_tokens=int(usage_doc.get("output_tokens", 0)) if usage_doc else 0,
            embeddings_created=int(usage_doc.get("embeddings_created", 0)) if usage_doc else 0,
            vector_queries=int(usage_doc.get("vector_queries", 0)) if usage_doc else 0,
            crawl_pages=int(usage_doc.get("crawl_pages", 0)) if usage_doc else 0,
        )

    async def collection_counts(self) -> CollectionCounts:
        # PERF-K04: the 12 per-collection counts were previously issued
        # sequentially (one round-trip each). Gather them concurrently so the
        # admin overview never pays ~12x the single-count latency.
        (
            users,
            tenants,
            websites,
            widgets,
            documents,
            chat_sessions,
            messages,
            usage_records,
            api_keys,
            subscriptions,
            audit_logs,
            admin_audit_logs,
        ) = await asyncio.gather(
            self._users.count_documents({}),
            self._tenants.count_documents({}),
            self._websites.count_documents({}),
            self._widgets.count_documents({}),
            self._documents.count_documents({}),
            self._sessions.count_documents({}),
            self._messages.count_documents({}),
            self._usage.count_documents({}),
            self._api_keys.count_documents({}),
            self._subscriptions.count_documents({}),
            self._audit_logs.count_documents({}),
            self._admin_audit_logs.count_documents({}),
        )
        return CollectionCounts(
            users=users,
            tenants=tenants,
            websites=websites,
            widgets=widgets,
            documents=documents,
            chat_sessions=chat_sessions,
            messages=messages,
            usage_records=usage_records,
            api_keys=api_keys,
            subscriptions=subscriptions,
            audit_logs=audit_logs,
            admin_audit_logs=admin_audit_logs,
        )

    @staticmethod
    async def _first(cursor: Any) -> dict[str, Any] | None:
        async for doc in cursor:
            return dict(doc)
        return None


__all__ = [
    "AdminRepository",
    "CollectionCounts",
    "MongoAdminRepository",
    "PlatformStats",
    "PlatformUsage",
]
