"""Analytics endpoints (Phase 11.3).

Read-only reporting over the existing chat/usage data. All routes require a
valid bearer access token with tenant role `owner` or `admin`. Tenant scoping
comes from the authenticated principal - the request can never select another
tenant's analytics (00-AI-Development-Rules §7).

    GET /api/analytics/summary         totals for the metric cards
    GET /api/analytics/timeseries      daily trend (zero-filled)
    GET /api/analytics/top-websites    website ranking
    GET /api/analytics/performance     response-time statistics
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from backend.api.deps import (
    analytics_limiter,
    current_user,
    get_analytics_service,
    require_role,
)
from backend.schemas.analytics import (
    DEFAULT_ANALYTICS_DAYS,
    DEFAULT_TOP_WEBSITES_LIMIT,
    MAX_ANALYTICS_DAYS,
    MAX_TOP_WEBSITES_LIMIT,
    AnalyticsSummary,
    ResponseMetrics,
    TimeseriesPoint,
    TopWebsite,
)
from backend.services.analytics import AnalyticsService
from backend.services.auth import Principal

router = APIRouter(
    prefix="/analytics",
    tags=["analytics"],
    dependencies=[Depends(require_role("owner", "admin"))],
)


@router.get("/summary", response_model=AnalyticsSummary)
async def get_analytics_summary(
    principal: Annotated[Principal, Depends(current_user)],
    service: Annotated[AnalyticsService, Depends(get_analytics_service)],
    _: Annotated[None, Depends(analytics_limiter)],
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
    principal: Annotated[Principal, Depends(current_user)],
    service: Annotated[AnalyticsService, Depends(get_analytics_service)],
    _: Annotated[None, Depends(analytics_limiter)],
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
    principal: Annotated[Principal, Depends(current_user)],
    service: Annotated[AnalyticsService, Depends(get_analytics_service)],
    _: Annotated[None, Depends(analytics_limiter)],
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
    principal: Annotated[Principal, Depends(current_user)],
    service: Annotated[AnalyticsService, Depends(get_analytics_service)],
    _: Annotated[None, Depends(analytics_limiter)],
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


__all__ = ["router"]
