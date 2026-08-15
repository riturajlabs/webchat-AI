"""Analytics endpoints (Phase 11.3 + Phase 12.5).

Read-only reporting over the existing chat/usage data. All routes require a
valid bearer credential with tenant role `owner` or `admin` - a user access
JWT or a `wc_*` API key (which always authenticates as owner). Tenant scoping
comes from the authenticated principal - the request can never select another
tenant's analytics (00-AI-Development-Rules §7).

    GET /api/analytics/summary         totals for the metric cards
    GET /api/analytics/timeseries      daily trend (zero-filled)
    GET /api/analytics/top-websites    website ranking
    GET /api/analytics/performance     response-time statistics
    GET /api/analytics/overview        resolution metrics (Phase 12.5)
    GET /api/analytics/questions       most-asked user questions
    GET /api/analytics/feedback        feedback sentiment + star distribution
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from backend.api.deps import (
    analytics_limiter,
    current_principal,
    enforce_api_key_rate_limit,
    get_analytics_service,
    require_principal_role,
)
from backend.schemas.analytics import (
    DEFAULT_ANALYTICS_DAYS,
    DEFAULT_TOP_QUESTIONS_LIMIT,
    DEFAULT_TOP_WEBSITES_LIMIT,
    MAX_ANALYTICS_DAYS,
    MAX_TOP_QUESTIONS_LIMIT,
    MAX_TOP_WEBSITES_LIMIT,
    AnalyticsOverview,
    AnalyticsSummary,
    FeedbackAnalytics,
    QuestionCount,
    ResponseMetrics,
    TimeseriesPoint,
    TopWebsite,
)
from backend.services.analytics import AnalyticsService
from backend.services.api_keys import ApiKeyPrincipal
from backend.services.auth import Principal

router = APIRouter(
    prefix="/analytics",
    tags=["analytics"],
    dependencies=[Depends(require_principal_role("owner", "admin"))],
)


@router.get("/summary", response_model=AnalyticsSummary)
async def get_analytics_summary(
    principal: Annotated[Principal | ApiKeyPrincipal, Depends(current_principal)],
    service: Annotated[AnalyticsService, Depends(get_analytics_service)],
    _: Annotated[None, Depends(analytics_limiter)],
    __: Annotated[None, Depends(enforce_api_key_rate_limit)],
    days: Annotated[int, Query(ge=1, le=MAX_ANALYTICS_DAYS)] = DEFAULT_ANALYTICS_DAYS,
    website_id: Annotated[str | None, Query(description="Filter by website")] = None,
) -> AnalyticsSummary:
    item = await service.get_summary(principal.tenant_id, days=days, website_id=website_id)
    return AnalyticsSummary(
        total_conversations=item.total_conversations,
        total_messages=item.total_messages,
        total_ai_responses=item.total_ai_responses,
        total_tokens=item.total_tokens,
        total_input_tokens=item.total_input_tokens,
        total_output_tokens=item.total_output_tokens,
        estimated_cost=item.estimated_cost,
        avg_response_time=item.avg_response_time,
    )


@router.get("/timeseries", response_model=list[TimeseriesPoint])
async def get_analytics_timeseries(
    principal: Annotated[Principal | ApiKeyPrincipal, Depends(current_principal)],
    service: Annotated[AnalyticsService, Depends(get_analytics_service)],
    _: Annotated[None, Depends(analytics_limiter)],
    __: Annotated[None, Depends(enforce_api_key_rate_limit)],
    days: Annotated[int, Query(ge=1, le=MAX_ANALYTICS_DAYS)] = DEFAULT_ANALYTICS_DAYS,
    website_id: Annotated[str | None, Query(description="Filter by website")] = None,
) -> list[TimeseriesPoint]:
    rows = await service.get_timeseries(principal.tenant_id, days=days, website_id=website_id)
    return [
        TimeseriesPoint(
            date=row.date,
            conversations=row.conversations,
            messages=row.messages,
            tokens=row.tokens,
            input_tokens=row.input_tokens,
            output_tokens=row.output_tokens,
        )
        for row in rows
    ]


@router.get("/top-websites", response_model=list[TopWebsite])
async def get_top_websites(
    principal: Annotated[Principal | ApiKeyPrincipal, Depends(current_principal)],
    service: Annotated[AnalyticsService, Depends(get_analytics_service)],
    _: Annotated[None, Depends(analytics_limiter)],
    __: Annotated[None, Depends(enforce_api_key_rate_limit)],
    days: Annotated[int, Query(ge=1, le=MAX_ANALYTICS_DAYS)] = DEFAULT_ANALYTICS_DAYS,
    limit: Annotated[int, Query(ge=1, le=MAX_TOP_WEBSITES_LIMIT)] = DEFAULT_TOP_WEBSITES_LIMIT,
) -> list[TopWebsite]:
    rows = await service.get_top_websites(principal.tenant_id, days=days, limit=limit)
    return [
        TopWebsite(
            website_id=row.website_id,
            website_name=row.website_name,
            conversations=row.conversations,
            messages=row.messages,
        )
        for row in rows
    ]


@router.get("/performance", response_model=ResponseMetrics)
async def get_response_metrics(
    principal: Annotated[Principal | ApiKeyPrincipal, Depends(current_principal)],
    service: Annotated[AnalyticsService, Depends(get_analytics_service)],
    _: Annotated[None, Depends(analytics_limiter)],
    __: Annotated[None, Depends(enforce_api_key_rate_limit)],
    days: Annotated[int, Query(ge=1, le=MAX_ANALYTICS_DAYS)] = DEFAULT_ANALYTICS_DAYS,
    website_id: Annotated[str | None, Query(description="Filter by website")] = None,
) -> ResponseMetrics:
    row = await service.get_response_metrics(
        principal.tenant_id, days=days, website_id=website_id
    )
    return ResponseMetrics(
        avg_response_time=row.avg_response_time,
        fastest_response_time=row.fastest_response_time,
        slowest_response_time=row.slowest_response_time,
    )


@router.get("/overview", response_model=AnalyticsOverview)
async def get_analytics_overview(
    principal: Annotated[Principal | ApiKeyPrincipal, Depends(current_principal)],
    service: Annotated[AnalyticsService, Depends(get_analytics_service)],
    _: Annotated[None, Depends(analytics_limiter)],
    __: Annotated[None, Depends(enforce_api_key_rate_limit)],
    days: Annotated[int, Query(ge=1, le=MAX_ANALYTICS_DAYS)] = DEFAULT_ANALYTICS_DAYS,
    website_id: Annotated[str | None, Query(description="Filter by website")] = None,
) -> AnalyticsOverview:
    item = await service.get_overview(
        principal.tenant_id, days=days, website_id=website_id
    )
    return AnalyticsOverview(
        total_conversations=item.total_conversations,
        total_messages=item.total_messages,
        total_questions=item.total_questions,
        total_ai_responses=item.total_ai_responses,
        successful_answers=item.successful_answers,
        fallback_responses=item.fallback_responses,
        resolution_rate=item.resolution_rate,
        fallback_percentage=item.fallback_percentage,
        avg_response_time=item.avg_response_time,
    )


@router.get("/questions", response_model=list[QuestionCount])
async def get_analytics_questions(
    principal: Annotated[Principal | ApiKeyPrincipal, Depends(current_principal)],
    service: Annotated[AnalyticsService, Depends(get_analytics_service)],
    _: Annotated[None, Depends(analytics_limiter)],
    __: Annotated[None, Depends(enforce_api_key_rate_limit)],
    days: Annotated[int, Query(ge=1, le=MAX_ANALYTICS_DAYS)] = DEFAULT_ANALYTICS_DAYS,
    website_id: Annotated[str | None, Query(description="Filter by website")] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_TOP_QUESTIONS_LIMIT)] = DEFAULT_TOP_QUESTIONS_LIMIT,
) -> list[QuestionCount]:
    rows = await service.get_top_questions(
        principal.tenant_id, days=days, website_id=website_id, limit=limit
    )
    return [QuestionCount(question=row.question, count=row.count) for row in rows]


@router.get("/feedback", response_model=FeedbackAnalytics)
async def get_analytics_feedback(
    principal: Annotated[Principal | ApiKeyPrincipal, Depends(current_principal)],
    service: Annotated[AnalyticsService, Depends(get_analytics_service)],
    _: Annotated[None, Depends(analytics_limiter)],
    __: Annotated[None, Depends(enforce_api_key_rate_limit)],
    days: Annotated[int, Query(ge=1, le=MAX_ANALYTICS_DAYS)] = DEFAULT_ANALYTICS_DAYS,
    website_id: Annotated[str | None, Query(description="Filter by website")] = None,
) -> FeedbackAnalytics:
    row = await service.get_feedback_analytics(
        principal.tenant_id, days=days, website_id=website_id
    )
    return FeedbackAnalytics(
        total=row.total,
        positive=row.positive,
        negative=row.negative,
        neutral=row.neutral,
        positive_percentage=_percent(row.positive, row.total),
        negative_percentage=_percent(row.negative, row.total),
        average_rating=row.average_rating,
        distribution=row.distribution,
    )


def _percent(part: int, total: int) -> float:
    """Share of `part` in `total` as a 0-100 percentage (0.0 when empty)."""
    return round(part / total * 100, 1) if total else 0.0


__all__ = ["router"]
