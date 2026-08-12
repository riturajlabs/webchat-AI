"""Feedback read endpoints for the dashboard (Phase 12.4, ADR-005 §5.6).

    GET /api/feedback            paginated list (website / category / rating filters)
    GET /api/feedback/summary    user-satisfaction breakdown (avg + 1-5 distribution)

All routes require a bearer access token with tenant role `owner` or `admin`.
Tenant scoping comes from the authenticated principal — the query can never
select another tenant's feedback (00-AI-Development-Rules §7). Feedback is
write-once from the widget; there is deliberately no delete here.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from backend.api.deps import (
    conversations_limiter,
    current_user,
    get_feedback_service,
    require_role,
)
from backend.schemas.feedback import (
    MAX_LIST_PAGE_SIZE,
    FeedbackCategory,
    FeedbackListResponse,
    FeedbackOut,
    FeedbackSummaryOut,
)
from backend.services.auth import Principal
from backend.services.feedback.feedback_service import (
    DEFAULT_SUMMARY_WINDOW_DAYS,
    MAX_SUMMARY_WINDOW_DAYS,
    FeedbackService,
)

router = APIRouter(
    prefix="/feedback",
    tags=["feedback"],
    dependencies=[Depends(require_role("owner", "admin"))],
)


@router.get("", response_model=FeedbackListResponse)
async def list_feedback(
    principal: Annotated[Principal, Depends(current_user)],
    service: Annotated[FeedbackService, Depends(get_feedback_service)],
    _: Annotated[None, Depends(conversations_limiter)],
    response: Response,
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=MAX_LIST_PAGE_SIZE)] = 20,
    website_id: Annotated[str | None, Query(description="Filter by website")] = None,
    category: Annotated[FeedbackCategory | None, Query(description="Filter by category")] = None,
    rating: Annotated[int | None, Query(ge=1, le=5, description="Filter by star rating")] = None,
) -> FeedbackListResponse:
    items, total = await service.list_feedback(
        principal.tenant_id,
        page=page,
        per_page=per_page,
        website_id=website_id,
        category=category,
        rating=rating,
    )
    response.headers["X-Total-Count"] = str(total)
    return FeedbackListResponse(
        items=[
            FeedbackOut(
                id=item.id,
                website_id=item.website_id,
                session_id=item.session_id,
                message_id=item.message_id,
                rating=item.rating,
                category=item.category,
                comment=item.comment,
                created_at=item.created_at,
            )
            for item in items
        ],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/summary", response_model=FeedbackSummaryOut)
async def feedback_summary(
    principal: Annotated[Principal, Depends(current_user)],
    service: Annotated[FeedbackService, Depends(get_feedback_service)],
    _: Annotated[None, Depends(conversations_limiter)],
    website_id: Annotated[str | None, Query(description="Filter by website")] = None,
    days: Annotated[
        int, Query(ge=1, le=MAX_SUMMARY_WINDOW_DAYS, description="Window length (days)")
    ] = DEFAULT_SUMMARY_WINDOW_DAYS,
) -> FeedbackSummaryOut:
    summary = await service.get_summary(
        principal.tenant_id,
        website_id=website_id,
        days=days,
    )
    return FeedbackSummaryOut.from_summary(
        total=summary.total,
        distribution=summary.distribution,
    )


__all__ = ["router"]
