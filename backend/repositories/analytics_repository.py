"""Analytics data access (Phase 11.3).

Read-only aggregations over the existing `chat_sessions`, `messages`,
`usage_records` and `websites` collections (ADR-005 §5.5: `usage_records` is
the daily rollup that analytics read; per-message `response_time`/tokens live
on `messages`). Every query is tenant-scoped and, when a website is supplied,
scoped to that website (00-AI-Development-Rules §7). No new collections are
created - the dashboard reads the data the chat pipeline already writes.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING

from backend.models.chat_message import CHAT_ROLE_ASSISTANT
from backend.models.chat_session import CHAT_SESSION_STATUS_DELETED
from backend.models.website import WEBSITE_STATUS_DELETED


@dataclass(frozen=True)
class AnalyticsSummaryRow:
    """Raw aggregates backing the summary endpoint (Phase 11.3)."""

    total_conversations: int
    total_messages: int
    total_ai_responses: int
    total_input_tokens: int
    total_output_tokens: int
    avg_response_time: float | None


@dataclass(frozen=True)
class TimeseriesRow:
    """One day of rolled-up usage for the trend charts."""

    date: str
    conversations: int
    messages: int
    tokens: int
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class TopWebsiteRow:
    """One website's rolled-up activity for the ranking chart."""

    website_id: str
    website_name: str
    conversations: int
    messages: int


@dataclass(frozen=True)
class ResponseMetricsRow:
    """Assistant response-time statistics for a window."""

    avg_response_time: float | None
    fastest_response_time: float | None
    slowest_response_time: float | None


class AnalyticsRepository(Protocol):
    """Read-only analytics queries (all tenant-scoped, ADR-005 §5.5)."""

    async def summary(
        self,
        tenant_id: str,
        *,
        website_id: str | None = None,
        since: datetime,
    ) -> AnalyticsSummaryRow: ...

    async def timeseries(
        self,
        tenant_id: str,
        *,
        website_id: str | None = None,
        since: datetime,
    ) -> list[TimeseriesRow]: ...

    async def top_websites(
        self,
        tenant_id: str,
        *,
        since: datetime,
        limit: int,
    ) -> list[TopWebsiteRow]: ...

    async def response_metrics(
        self,
        tenant_id: str,
        *,
        website_id: str | None = None,
        since: datetime,
    ) -> ResponseMetricsRow: ...


class MongoAnalyticsRepository:
    """MongoDB-backed analytics repository.

    Conversations are counted from `chat_sessions.started_at` (soft-deleted
    sessions excluded); AI responses and response times come from
    `messages` (role `assistant`); message/token totals come from the
    `usage_records` daily rollup, which `RagService` already maintains
    (ADR-005 §5.5). Website names resolve from the tenant's `websites`.
    """

    def __init__(self, db: AsyncIOMotorDatabase[Any]) -> None:
        self._sessions = db["chat_sessions"]
        self._messages = db["messages"]
        self._usage = db["usage_records"]
        self._websites = db["websites"]

    async def summary(
        self,
        tenant_id: str,
        *,
        website_id: str | None = None,
        since: datetime,
    ) -> AnalyticsSummaryRow:
        total_conversations = await self._count_conversations(
            tenant_id, website_id=website_id, since=since
        )

        messages_match: dict[str, Any] = {
            "tenant_id": tenant_id,
            "role": CHAT_ROLE_ASSISTANT,
            "created_at": {"$gte": since},
        }
        if website_id is not None:
            messages_match["website_id"] = website_id
        response_doc = await self._first(
            self._messages.aggregate(
                [
                    {"$match": messages_match},
                    {
                        "$group": {
                            "_id": None,
                            "total_ai_responses": {"$sum": 1},
                            "avg_response_time": {"$avg": "$response_time"},
                        }
                    },
                ]
            )
        )
        total_ai_responses = int(response_doc.get("total_ai_responses", 0)) if response_doc else 0
        avg_response_time = (
            float(response_doc["avg_response_time"]) if response_doc else None
        )

        usage_match: dict[str, Any] = {
            "tenant_id": tenant_id,
            "date": {"$gte": since.date().isoformat()},
        }
        if website_id is not None:
            usage_match["website_id"] = website_id
        usage_doc = await self._first(
            self._usage.aggregate(
                [
                    {"$match": usage_match},
                    {
                        "$group": {
                            "_id": None,
                            "total_messages": {"$sum": "$counters.messages"},
                            "total_input_tokens": {"$sum": "$counters.input_tokens"},
                            "total_output_tokens": {"$sum": "$counters.output_tokens"},
                        }
                    },
                ]
            )
        )
        return AnalyticsSummaryRow(
            total_conversations=total_conversations,
            total_messages=int(usage_doc.get("total_messages", 0)) if usage_doc else 0,
            total_ai_responses=total_ai_responses,
            total_input_tokens=int(usage_doc.get("total_input_tokens", 0)) if usage_doc else 0,
            total_output_tokens=int(usage_doc.get("total_output_tokens", 0)) if usage_doc else 0,
            avg_response_time=avg_response_time,
        )

    async def timeseries(
        self,
        tenant_id: str,
        *,
        website_id: str | None = None,
        since: datetime,
    ) -> list[TimeseriesRow]:
        match: dict[str, Any] = {
            "tenant_id": tenant_id,
            "date": {"$gte": since.date().isoformat()},
        }
        if website_id is not None:
            match["website_id"] = website_id
        cursor = self._usage.aggregate(
            [
                {"$match": match},
                {
                    "$group": {
                        "_id": "$date",
                        "conversations": {"$sum": "$counters.chats"},
                        "messages": {"$sum": "$counters.messages"},
                        "input_tokens": {"$sum": "$counters.input_tokens"},
                        "output_tokens": {"$sum": "$counters.output_tokens"},
                    }
                },
                {"$sort": {"_id": ASCENDING}},
            ]
        )
        rows: list[TimeseriesRow] = []
        async for doc in cursor:
            date = str(doc["_id"])
            input_tokens = int(doc.get("input_tokens", 0))
            output_tokens = int(doc.get("output_tokens", 0))
            rows.append(
                TimeseriesRow(
                    date=date,
                    conversations=int(doc.get("conversations", 0)),
                    messages=int(doc.get("messages", 0)),
                    tokens=input_tokens + output_tokens,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )
            )
        return rows

    async def top_websites(
        self,
        tenant_id: str,
        *,
        since: datetime,
        limit: int,
    ) -> list[TopWebsiteRow]:
        cursor = self._usage.aggregate(
            [
                {"$match": {"tenant_id": tenant_id, "date": {"$gte": since.date().isoformat()}}},
                {
                    "$group": {
                        "_id": "$website_id",
                        "conversations": {"$sum": "$counters.chats"},
                        "messages": {"$sum": "$counters.messages"},
                    }
                },
                {"$sort": {"conversations": DESCENDING, "messages": DESCENDING}},
                {"$limit": limit},
            ]
        )
        website_ids: list[str] = []
        ranked: list[tuple[str, int, int]] = []
        async for doc in cursor:
            website_id = str(doc["_id"])
            website_ids.append(website_id)
            ranked.append(
                (
                    website_id,
                    int(doc.get("conversations", 0)),
                    int(doc.get("messages", 0)),
                )
            )
        names = await self._website_names(tenant_id, website_ids)
        return [
            TopWebsiteRow(
                website_id=website_id,
                website_name=names.get(website_id, "Unknown website"),
                conversations=conversations,
                messages=messages,
            )
            for website_id, conversations, messages in ranked
        ]

    async def response_metrics(
        self,
        tenant_id: str,
        *,
        website_id: str | None = None,
        since: datetime,
    ) -> ResponseMetricsRow:
        match: dict[str, Any] = {
            "tenant_id": tenant_id,
            "role": CHAT_ROLE_ASSISTANT,
            "response_time": {"$ne": None},
            "created_at": {"$gte": since},
        }
        if website_id is not None:
            match["website_id"] = website_id
        doc = await self._first(
            self._messages.aggregate(
                [
                    {"$match": match},
                    {
                        "$group": {
                            "_id": None,
                            "avg_response_time": {"$avg": "$response_time"},
                            "fastest_response_time": {"$min": "$response_time"},
                            "slowest_response_time": {"$max": "$response_time"},
                        }
                    },
                ]
            )
        )
        if doc is None:
            return ResponseMetricsRow(None, None, None)
        return ResponseMetricsRow(
            avg_response_time=float(doc["avg_response_time"]),
            fastest_response_time=float(doc["fastest_response_time"]),
            slowest_response_time=float(doc["slowest_response_time"]),
        )

    # ------------------------------------------------------------- internals

    async def _count_conversations(
        self, tenant_id: str, *, website_id: str | None, since: datetime
    ) -> int:
        match: dict[str, Any] = {
            "tenant_id": tenant_id,
            "started_at": {"$gte": since},
            "status": {"$ne": CHAT_SESSION_STATUS_DELETED},
        }
        if website_id is not None:
            match["website_id"] = website_id
        return await self._sessions.count_documents(match)

    async def _website_names(self, tenant_id: str, website_ids: list[str]) -> dict[str, str]:
        if not website_ids:
            return {}
        cursor = self._websites.find(
            {
                "_id": {"$in": website_ids},
                "tenant_id": tenant_id,
                "status": {"$ne": WEBSITE_STATUS_DELETED},
            },
            {"name": 1},
        )
        return {str(doc["_id"]): str(doc.get("name") or "") async for doc in cursor}

    @staticmethod
    async def _first(cursor: Any) -> dict[str, Any] | None:
        async for doc in cursor:
            return dict(doc)
        return None


__all__ = [
    "AnalyticsRepository",
    "AnalyticsSummaryRow",
    "MongoAnalyticsRepository",
    "ResponseMetricsRow",
    "TimeseriesRow",
    "TopWebsiteRow",
]
