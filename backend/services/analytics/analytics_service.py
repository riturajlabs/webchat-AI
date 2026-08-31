"""Analytics business logic (Phase 11.3).

Read-only reporting over the data the chat pipeline already writes. The
service owns the window math (how far back `days` reaches, plus explicit
custom `start`/`end` calendar dates), the estimated cost model (per-token
list prices from settings), the previous-period comparisons behind the
period-over-period deltas, and zero-filling the daily timeseries so charts
render a continuous line. All database access stays in the repository
(layering rules §6): `AnalyticsService` only depends on the
`AnalyticsRepository` Protocol.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

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
    """The summary contract returned to routes (est. cost is derived).

    `previous_conversations` / `previous_messages` / `previous_tokens` /
    `previous_avg_response_time` cover the immediately preceding window of
    equal length (see the API schema for absent-window semantics).
    """

    total_conversations: int
    total_messages: int
    total_ai_responses: int
    total_tokens: int
    total_input_tokens: int
    total_output_tokens: int
    estimated_cost: float
    avg_response_time: float | None
    previous_conversations: int = 0
    previous_messages: int = 0
    previous_tokens: int = 0
    previous_avg_response_time: float | None = None


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


@dataclass(frozen=True)
class _Window:
    """Inclusive `since` / exclusive `until` UTC boundaries of a report window.

    Default N-day windows end "now" (`until=None`, the repository treats that
    as unbounded and the summary's previous-period math uses the calendar
    span); explicit custom ranges always carry an exclusive `until`.
    """

    since: datetime
    until: datetime | None


class AnalyticsService:
    """Read-only analytics workflows for the dashboard."""

    def __init__(self, *, analytics: AnalyticsRepository) -> None:
        self._analytics = analytics

    # ------------------------------------------------------------------ flows

    async def get_summary(
        self,
        tenant_id: str,
        *,
        days: int | None,
        website_id: str | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> AnalyticsSummaryItem:
        window = _window(days=days, start=start, end=end)
        row = await self._analytics.summary(
            tenant_id,
            website_id=website_id,
            since=window.since,
            until=window.until,
        )
        previous = await self._analytics.summary(
            tenant_id,
            website_id=website_id,
            since=_previous_since(window),
            until=window.since,
        )
        return AnalyticsSummaryItem(
            total_conversations=row.total_conversations,
            total_messages=row.total_messages,
            total_ai_responses=row.total_ai_responses,
            total_tokens=row.total_input_tokens + row.total_output_tokens,
            total_input_tokens=row.total_input_tokens,
            total_output_tokens=row.total_output_tokens,
            estimated_cost=self._estimated_cost(row.total_input_tokens, row.total_output_tokens),
            avg_response_time=_round_optional(row.avg_response_time),
            previous_conversations=previous.total_conversations,
            previous_messages=previous.total_messages,
            previous_tokens=previous.total_input_tokens + previous.total_output_tokens,
            previous_avg_response_time=_round_optional(previous.avg_response_time),
        )

    async def get_timeseries(
        self,
        tenant_id: str,
        *,
        days: int | None,
        website_id: str | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> list[TimeseriesRow]:
        window = _window(days=days, start=start, end=end)
        rows = await self._analytics.timeseries(
            tenant_id,
            website_id=website_id,
            since=window.since,
            until=window.until,
        )
        return _fill_timeseries(rows, _range_dates(window))

    async def get_top_websites(
        self,
        tenant_id: str,
        *,
        days: int | None,
        limit: int,
        start: date | None = None,
        end: date | None = None,
    ) -> list[TopWebsiteRow]:
        window = _window(days=days, start=start, end=end)
        return await self._analytics.top_websites(
            tenant_id, since=window.since, until=window.until, limit=limit
        )

    async def get_response_metrics(
        self,
        tenant_id: str,
        *,
        days: int | None,
        website_id: str | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> ResponseMetricsRow:
        window = _window(days=days, start=start, end=end)
        row = await self._analytics.response_metrics(
            tenant_id,
            website_id=website_id,
            since=window.since,
            until=window.until,
        )
        return ResponseMetricsRow(
            avg_response_time=_round_optional(row.avg_response_time),
            fastest_response_time=_round_optional(row.fastest_response_time),
            slowest_response_time=_round_optional(row.slowest_response_time),
            median_response_time=_round_optional(row.median_response_time),
            p95_response_time=_round_optional(row.p95_response_time),
            distribution=dict(row.distribution or {}),
            avg_embedding_ms=_round_optional(row.avg_embedding_ms),
            avg_retrieval_ms=_round_optional(row.avg_retrieval_ms),
            avg_generation_ms=_round_optional(row.avg_generation_ms),
        )

    async def get_overview(
        self,
        tenant_id: str,
        *,
        days: int | None,
        website_id: str | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> OverviewItem:
        """Resolution metrics: chats, questions, successful/fallback answers.

        `resolution_rate` = successful answers / all answers; when the window
        has no assistant responses both rates are 0.0 (there is nothing to
        divide by, and an empty window should read as 0% resolved, not null).
        """
        window = _window(days=days, start=start, end=end)
        row = await self._analytics.overview(
            tenant_id,
            website_id=website_id,
            since=window.since,
            until=window.until,
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
        days: int | None,
        website_id: str | None = None,
        limit: int,
        start: date | None = None,
        end: date | None = None,
    ) -> list[QuestionCountRow]:
        """Rank the most frequently asked user questions in the window."""
        window = _window(days=days, start=start, end=end)
        return await self._analytics.top_questions(
            tenant_id,
            website_id=website_id,
            since=window.since,
            until=window.until,
            limit=limit,
        )

    async def get_feedback_analytics(
        self,
        tenant_id: str,
        *,
        days: int | None,
        website_id: str | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> FeedbackAnalyticsRow:
        """Sentiment + star distribution over the feedback collection."""
        window = _window(days=days, start=start, end=end)
        return await self._analytics.feedback(
            tenant_id,
            website_id=website_id,
            since=window.since,
            until=window.until,
        )

    # ------------------------------------------------------------- internals

    def _estimated_cost(self, input_tokens: int, output_tokens: int) -> float:
        settings = get_settings()
        cost = (
            input_tokens / _MILLION * settings.cost_per_million_input_tokens
            + output_tokens / _MILLION * settings.cost_per_million_output_tokens
        )
        return round(cost, 6)


def _window(
    *,
    days: int | None,
    start: date | None = None,
    end: date | None = None,
) -> _Window:
    """Resolve a report window from either `days` or an explicit range.

    `start`/`end` win over `days` when supplied (the route already validates
    they come as a pair and span <= 90 days). `end` is inclusive; the
    repository's exclusive `until` therefore is the following day.
    """
    if start is not None or end is not None:
        first = start if start is not None else end
        last = end if end is not None else start
        assert first is not None and last is not None
        since = _start_of_day(first)
        until = _start_of_day(last + timedelta(days=1))
        return _Window(since=since, until=until)
    return _Window(since=_start_of_window(days or 1), until=None)


def _start_of_window(days: int) -> datetime:
    """Start of the UTC day `days` days ago (inclusive of today)."""
    now = utcnow()
    start = now - timedelta(days=days - 1)
    return start.replace(hour=0, minute=0, second=0, microsecond=0)


def _start_of_day(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC)


def _range_dates(window: _Window) -> list[date]:
    """Every calendar date covered by a window, oldest first, incl. today."""
    first = window.since.date()
    if window.until is None:
        last = utcnow().date()
    else:
        last = (window.until - timedelta(days=1)).date()
    dates: list[date] = []
    cursor = first
    while cursor <= last:
        dates.append(cursor)
        cursor += timedelta(days=1)
    return dates


def _previous_since(window: _Window) -> datetime:
    """Start of the equal-length window immediately before `window`."""
    span = len(_range_dates(window))
    return window.since - timedelta(days=span)


def _fill_timeseries(rows: list[TimeseriesRow], dates: list[date]) -> list[TimeseriesRow]:
    """Return one row per calendar date, zero-filling gaps.

    `usage_records` only contains days with activity, so charts would otherwise
    show a sparse, jumpy line (docs/04: continuous daily trend). Zero-filling
    is safe here because a rolled-up day with no record genuinely had no
    traffic — the values are real, not invented.
    """
    by_date = {row.date: row for row in rows}
    return [
        by_date.get(d.isoformat())
        or TimeseriesRow(
            date=d.isoformat(),
            conversations=0,
            messages=0,
            tokens=0,
            input_tokens=0,
            output_tokens=0,
        )
        for d in dates
    ]


def _round_optional(value: float | None) -> float | None:
    return round(value, 3) if value is not None else None


__all__ = [
    "AnalyticsService",
    "AnalyticsSummaryItem",
    "OverviewItem",
]
