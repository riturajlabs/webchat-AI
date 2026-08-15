"""Analytics business logic (Phase 11.3).

Read-only reporting over the data the chat pipeline already writes. The
service owns the window math (how far back `days` reaches), the estimated
cost model (per-token list prices from settings), and zero-filling the daily
timeseries so charts render a continuous line. All database access stays in
the repository (layering rules §6): `AnalyticsService` only depends on the
`AnalyticsRepository` Protocol.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from backend.core.config import get_settings
from backend.core.security import utcnow
from backend.repositories.analytics_repository import (
    AnalyticsRepository,
    FeedbackAnalyticsRow,
    QuestionCountRow,
    ResponseMetricsRow,
    TimeseriesRow,
    TopWebsiteRow,
)

_MILLION = 1_000_000


@dataclass(frozen=True)
class AnalyticsSummaryItem:
    """The summary contract returned to routes (est. cost is derived)."""

    total_conversations: int
    total_messages: int
    total_ai_responses: int
    total_tokens: int
    total_input_tokens: int
    total_output_tokens: int
    estimated_cost: float
    avg_response_time: float | None


@dataclass(frozen=True)
class OverviewItem:
    """Resolution-metrics contract for the /overview endpoint (Phase 12.5).

    Percentages are derived here: resolution rate is the share of assistant
    responses that were not the no-context fallback; the fallback percentage
    is the complement. Both round to one decimal and collapse to 0.0 when
    there are no responses at all.
    """

    total_conversations: int
    total_messages: int
    total_questions: int
    total_ai_responses: int
    successful_answers: int
    fallback_responses: int
    resolution_rate: float
    fallback_percentage: float
    avg_response_time: float | None


class AnalyticsService:
    """Read-only analytics workflows for the dashboard."""

    def __init__(self, *, analytics: AnalyticsRepository) -> None:
        self._analytics = analytics

    # ------------------------------------------------------------------ flows

    async def get_summary(
        self,
        tenant_id: str,
        *,
        days: int,
        website_id: str | None = None,
    ) -> AnalyticsSummaryItem:
        row = await self._analytics.summary(
            tenant_id, website_id=website_id, since=_start_of_window(days)
        )
        return AnalyticsSummaryItem(
            total_conversations=row.total_conversations,
            total_messages=row.total_messages,
            total_ai_responses=row.total_ai_responses,
            total_tokens=row.total_input_tokens + row.total_output_tokens,
            total_input_tokens=row.total_input_tokens,
            total_output_tokens=row.total_output_tokens,
            estimated_cost=self._estimated_cost(
                row.total_input_tokens, row.total_output_tokens
            ),
            avg_response_time=_round_optional(row.avg_response_time),
        )

    async def get_timeseries(
        self,
        tenant_id: str,
        *,
        days: int,
        website_id: str | None = None,
    ) -> list[TimeseriesRow]:
        rows = await self._analytics.timeseries(
            tenant_id, website_id=website_id, since=_start_of_window(days)
        )
        return _fill_timeseries(rows, days)

    async def get_top_websites(
        self,
        tenant_id: str,
        *,
        days: int,
        limit: int,
    ) -> list[TopWebsiteRow]:
        return await self._analytics.top_websites(
            tenant_id, since=_start_of_window(days), limit=limit
        )

    async def get_response_metrics(
        self,
        tenant_id: str,
        *,
        days: int,
        website_id: str | None = None,
    ) -> ResponseMetricsRow:
        row = await self._analytics.response_metrics(
            tenant_id, website_id=website_id, since=_start_of_window(days)
        )
        return ResponseMetricsRow(
            avg_response_time=_round_optional(row.avg_response_time),
            fastest_response_time=_round_optional(row.fastest_response_time),
            slowest_response_time=_round_optional(row.slowest_response_time),
        )

    async def get_overview(
        self,
        tenant_id: str,
        *,
        days: int,
        website_id: str | None = None,
    ) -> OverviewItem:
        """Resolution metrics: chats, questions, successful/fallback answers.

        `resolution_rate` = successful answers / all answers; when the window
        has no assistant responses both rates are 0.0 (there is nothing to
        divide by, and an empty window should read as 0% resolved, not null).
        """
        row = await self._analytics.overview(
            tenant_id, website_id=website_id, since=_start_of_window(days)
        )
        total = row.total_ai_responses
        resolution_rate = round(row.successful_answers / total * 100, 1) if total else 0.0
        fallback_percentage = round(row.fallback_responses / total * 100, 1) if total else 0.0
        return OverviewItem(
            total_conversations=row.total_conversations,
            total_messages=row.total_messages,
            total_questions=row.total_questions,
            total_ai_responses=row.total_ai_responses,
            successful_answers=row.successful_answers,
            fallback_responses=row.fallback_responses,
            resolution_rate=resolution_rate,
            fallback_percentage=fallback_percentage,
            avg_response_time=_round_optional(row.avg_response_time),
        )

    async def get_top_questions(
        self,
        tenant_id: str,
        *,
        days: int,
        website_id: str | None = None,
        limit: int,
    ) -> list[QuestionCountRow]:
        """Rank the most frequently asked user questions in the window."""
        return await self._analytics.top_questions(
            tenant_id, website_id=website_id, since=_start_of_window(days), limit=limit
        )

    async def get_feedback_analytics(
        self,
        tenant_id: str,
        *,
        days: int,
        website_id: str | None = None,
    ) -> FeedbackAnalyticsRow:
        """Sentiment + star distribution over the feedback collection."""
        return await self._analytics.feedback(
            tenant_id, website_id=website_id, since=_start_of_window(days)
        )

    # ------------------------------------------------------------- internals

    def _estimated_cost(self, input_tokens: int, output_tokens: int) -> float:
        settings = get_settings()
        cost = (
            input_tokens / _MILLION * settings.cost_per_million_input_tokens
            + output_tokens / _MILLION * settings.cost_per_million_output_tokens
        )
        return round(cost, 6)


def _start_of_window(days: int) -> datetime:
    """Start of the UTC day `days` days ago (inclusive of today)."""
    now = utcnow()
    start = now - timedelta(days=days - 1)
    return start.replace(hour=0, minute=0, second=0, microsecond=0)


def _fill_timeseries(rows: list[TimeseriesRow], days: int) -> list[TimeseriesRow]:
    """Return one row per day in the window, zero-filling gaps.

    `usage_records` only contains days with activity, so charts would otherwise
    show a sparse, jumpy line (docs/04: continuous daily trend).
    """
    by_date = {row.date: row for row in rows}
    today = utcnow().date()
    filled: list[TimeseriesRow] = []
    for offset in range(days - 1, -1, -1):
        date = (today - timedelta(days=offset)).isoformat()
        row = by_date.get(date)
        filled.append(
            row
            if row is not None
            else TimeseriesRow(
                date=date,
                conversations=0,
                messages=0,
                tokens=0,
                input_tokens=0,
                output_tokens=0,
            )
        )
    return filled


def _round_optional(value: float | None) -> float | None:
    return round(value, 3) if value is not None else None


__all__ = [
    "AnalyticsService",
    "AnalyticsSummaryItem",
    "OverviewItem",
]
