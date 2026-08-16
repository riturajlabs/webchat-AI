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

from backend.models.chat_message import (
    CHAT_ROLE_ASSISTANT,
    CHAT_ROLE_USER,
)
from backend.models.chat_session import CHAT_SESSION_STATUS_DELETED
from backend.models.website import WEBSITE_STATUS_DELETED
from backend.prompts.rag import UNKNOWN_ANSWER_FALLBACK

# Feedback sentiment buckets for the analytics feedback endpoint. Ratings of
# 4-5 stars count as positive, 3 as neutral, and 1-2 as negative (the star
# distribution itself is still surfaced verbatim for the dashboard chart).
FEEDBACK_POSITIVE_RATING = 4
FEEDBACK_NEGATIVE_RATING = 2


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
    """Assistant response statistics for a window (Phase 12.6).

    `avg_embedding_ms` / `avg_retrieval_ms` / `avg_generation_ms` are the
    per-stage latency averages persisted on assistant messages, letting the
    performance dashboard break the response time down into where it went.
    """

    avg_response_time: float | None
    fastest_response_time: float | None
    slowest_response_time: float | None
    avg_embedding_ms: float | None = None
    avg_retrieval_ms: float | None = None
    avg_generation_ms: float | None = None


@dataclass(frozen=True)
class OverviewRow:
    """Raw aggregates behind the /analytics/overview endpoint.

    `total_questions` counts user turns; `total_ai_responses` counts assistant
    messages (fallbacks included); `successful_answers` and
    `fallback_responses` split assistant messages by whether they carry the
    no-context fallback text (Phase 12.5 resolution metrics).
    """

    total_conversations: int
    total_messages: int
    total_questions: int
    total_ai_responses: int
    successful_answers: int
    fallback_responses: int
    avg_response_time: float | None


@dataclass(frozen=True)
class QuestionCountRow:
    """One distinct user question and how often it was asked."""

    question: str
    count: int


@dataclass(frozen=True)
class FeedbackAnalyticsRow:
    """Sentiment + star distribution behind the /analytics/feedback endpoint."""

    total: int
    positive: int
    negative: int
    neutral: int
    average_rating: float | None
    distribution: dict[int, int]


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

    async def overview(
        self,
        tenant_id: str,
        *,
        website_id: str | None = None,
        since: datetime,
    ) -> OverviewRow: ...

    async def top_questions(
        self,
        tenant_id: str,
        *,
        website_id: str | None = None,
        since: datetime,
        limit: int,
    ) -> list[QuestionCountRow]: ...

    async def feedback(
        self,
        tenant_id: str,
        *,
        website_id: str | None = None,
        since: datetime,
    ) -> FeedbackAnalyticsRow: ...


class MongoAnalyticsRepository:
    """MongoDB-backed analytics repository.

    Conversations are counted from `chat_sessions.started_at` (soft-deleted
    sessions excluded); AI responses and response times come from
    `messages` (role `assistant`); message/token totals come from the
    `usage_records` daily rollup, which `RagService` already maintains
    (ADR-005 §5.5). Website names resolve from the tenant's `websites`.
    Fallback responses are recognised by their fixed no-context text
    (`backend.prompts.rag.UNKNOWN_ANSWER_FALLBACK`) so the analytics layer
    needs no changes to the chat pipeline. Feedback reads the `feedback`
    collection the widget already writes.
    """

    def __init__(self, db: AsyncIOMotorDatabase[Any]) -> None:
        self._sessions = db["chat_sessions"]
        self._messages = db["messages"]
        self._usage = db["usage_records"]
        self._websites = db["websites"]
        self._feedback = db["feedback"]

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
        avg_response_time = float(response_doc["avg_response_time"]) if response_doc else None

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
                            "avg_embedding_ms": {"$avg": "$latency_embedding_ms"},
                            "avg_retrieval_ms": {"$avg": "$latency_retrieval_ms"},
                            "avg_generation_ms": {"$avg": "$latency_generation_ms"},
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
            avg_embedding_ms=_optional_float(doc.get("avg_embedding_ms")),
            avg_retrieval_ms=_optional_float(doc.get("avg_retrieval_ms")),
            avg_generation_ms=_optional_float(doc.get("avg_generation_ms")),
        )

    async def overview(
        self,
        tenant_id: str,
        *,
        website_id: str | None = None,
        since: datetime,
    ) -> OverviewRow:
        """Conversation / question / response resolution aggregates.

        A single `$facet` pass over `messages` yields user-turn counts,
        assistant counts, the fallback split (by fixed no-context text) and
        the average response time; conversations and total messages reuse the
        same sources as `summary`.
        """
        total_conversations = await self._count_conversations(
            tenant_id, website_id=website_id, since=since
        )
        messages_match: dict[str, Any] = {
            "tenant_id": tenant_id,
            "role": {"$in": [CHAT_ROLE_USER, CHAT_ROLE_ASSISTANT]},
            "created_at": {"$gte": since},
        }
        if website_id is not None:
            messages_match["website_id"] = website_id
        facet_doc = await self._first(
            self._messages.aggregate(
                [
                    {"$match": messages_match},
                    {
                        "$facet": {
                            "users": [{"$match": {"role": CHAT_ROLE_USER}}, {"$count": "count"}],
                            "assistants": [
                                {"$match": {"role": CHAT_ROLE_ASSISTANT}},
                                {"$count": "count"},
                            ],
                            "fallbacks": [
                                {
                                    "$match": {
                                        "role": CHAT_ROLE_ASSISTANT,
                                        "content": UNKNOWN_ANSWER_FALLBACK,
                                    }
                                },
                                {"$count": "count"},
                            ],
                            "response": [
                                {
                                    "$match": {
                                        "role": CHAT_ROLE_ASSISTANT,
                                        "response_time": {"$ne": None},
                                    }
                                },
                                {"$group": {"_id": None, "avg": {"$avg": "$response_time"}}},
                            ],
                        }
                    },
                ]
            )
        )
        facet = facet_doc or {}
        total_ai_responses = self._facet_count(facet, "assistants")
        fallback_responses = self._facet_count(facet, "fallbacks")
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
                    {"$group": {"_id": None, "total_messages": {"$sum": "$counters.messages"}}},
                ]
            )
        )
        response = facet.get("response")
        return OverviewRow(
            total_conversations=total_conversations,
            total_messages=int(usage_doc.get("total_messages", 0)) if usage_doc else 0,
            total_questions=self._facet_count(facet, "users"),
            total_ai_responses=total_ai_responses,
            successful_answers=total_ai_responses - fallback_responses,
            fallback_responses=fallback_responses,
            avg_response_time=(
                float(response[0]["avg"])
                if response and response[0].get("avg") is not None
                else None
            ),
        )

    async def top_questions(
        self,
        tenant_id: str,
        *,
        website_id: str | None = None,
        since: datetime,
        limit: int,
    ) -> list[QuestionCountRow]:
        """Rank the most frequently asked user questions in the window.

        Grouping is by the sanitized message text (`sanitize_question` already
        collapses whitespace before persistence), trimmed here so stored or
        legacy values with stray edges still group together.
        """
        match: dict[str, Any] = {
            "tenant_id": tenant_id,
            "role": CHAT_ROLE_USER,
            "created_at": {"$gte": since},
        }
        if website_id is not None:
            match["website_id"] = website_id
        cursor = self._messages.aggregate(
            [
                {"$match": match},
                {"$group": {"_id": {"$trim": {"input": "$content"}}, "count": {"$sum": 1}}},
                {"$sort": {"count": DESCENDING}},
                {"$limit": limit},
            ]
        )
        return [
            QuestionCountRow(question=str(doc["_id"]), count=int(doc.get("count", 0)))
            async for doc in cursor
        ]

    async def feedback(
        self,
        tenant_id: str,
        *,
        website_id: str | None = None,
        since: datetime,
    ) -> FeedbackAnalyticsRow:
        """Sentiment + star distribution over the `feedback` collection.

        One `$group` pass buckets by rating; positive/neutral/negative buckets
        and the average are derived here (ratings 4-5 positive, 3 neutral,
        1-2 negative — see `FEEDBACK_POSITIVE_RATING`).
        """
        match: dict[str, Any] = {"tenant_id": tenant_id}
        if website_id is not None:
            match["website_id"] = website_id
        if since is not None:
            match["created_at"] = {"$gte": since}
        cursor = self._feedback.aggregate(
            [
                {"$match": match},
                {"$group": {"_id": "$rating", "count": {"$sum": 1}}},
            ]
        )
        distribution: dict[int, int] = {}
        total = 0
        weighted = 0
        async for doc in cursor:
            rating = int(doc["_id"])
            if not 1 <= rating <= 5:
                continue
            count = int(doc.get("count", 0))
            distribution[rating] = count
            total += count
            weighted += rating * count
        positive = sum(
            count for rating, count in distribution.items() if rating >= FEEDBACK_POSITIVE_RATING
        )
        negative = sum(
            count for rating, count in distribution.items() if rating <= FEEDBACK_NEGATIVE_RATING
        )
        neutral = sum(
            count
            for rating, count in distribution.items()
            if FEEDBACK_NEGATIVE_RATING < rating < FEEDBACK_POSITIVE_RATING
        )
        return FeedbackAnalyticsRow(
            total=total,
            positive=positive,
            negative=negative,
            neutral=neutral,
            average_rating=round(weighted / total, 2) if total else None,
            distribution=distribution,
        )

    # ------------------------------------------------------------- internals

    @staticmethod
    def _facet_count(facet: dict[str, Any], key: str) -> int:
        rows = facet.get(key) or []
        return int(rows[0]["count"]) if rows else 0

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


def _optional_float(value: float | None) -> float | None:
    """Coerce an aggregate result to float, mapping None (no docs) to None.

    `$avg` over an absent field on an existing group still returns a value
    (null) - and on a group with no matching documents the key is missing -
    so both cases must collapse to `None` for the API contract.
    """
    if value is None:
        return None
    return float(value)


__all__ = [
    "AnalyticsRepository",
    "AnalyticsSummaryRow",
    "FeedbackAnalyticsRow",
    "MongoAnalyticsRepository",
    "OverviewRow",
    "QuestionCountRow",
    "ResponseMetricsRow",
    "TimeseriesRow",
    "TopWebsiteRow",
]
