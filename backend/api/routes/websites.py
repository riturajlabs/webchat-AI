"""Website management endpoints (Phase 3, ADR-008).

All routes require a valid bearer access token with tenant role `owner` or
`admin`. Tenant scoping comes from the authenticated principal - the request
body can never select another tenant's data (00-AI-Development-Rules §7).
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response

from backend.api.deps import (
    client_ip,
    crawl_limiter,
    current_user,
    get_crawl_service,
    get_website_service,
    require_role,
    website_limiter,
)
from backend.schemas.crawl import StartCrawlResponse
from backend.schemas.websites import (
    CreateWebsiteRequest,
    CreateWebsiteResponse,
    UpdateWebsiteRequest,
    WebsiteOut,
    WidgetOut,
    WidgetResponse,
)
from backend.services.auth import Principal
from backend.services.crawl import CrawlService
from backend.services.website import WebsiteService

router = APIRouter(
    prefix="/websites",
    tags=["websites"],
    dependencies=[Depends(require_role("owner", "admin"))],
)


@router.post("", response_model=CreateWebsiteResponse, status_code=201)
async def create_website(
    body: CreateWebsiteRequest,
    request: Request,
    response: Response,
    principal: Annotated[Principal, Depends(current_user)],
    service: Annotated[WebsiteService, Depends(get_website_service)],
    _: Annotated[None, Depends(website_limiter)],
) -> CreateWebsiteResponse:
    result = await service.create_website(
        principal=principal,
        name=body.name,
        url=body.url,
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    response.headers["Location"] = f"/api/websites/{result.website.id}"
    return CreateWebsiteResponse(
        website=WebsiteOut.from_website(result.website, widget_id=result.widget.widget_id),
        widget=WidgetOut.from_widget(result.widget),
        widget_secret=result.widget_secret,
        embed_script=result.embed_script,
    )


@router.get("", response_model=list[WebsiteOut])
async def list_websites(
    principal: Annotated[Principal, Depends(current_user)],
    service: Annotated[WebsiteService, Depends(get_website_service)],
    _: Annotated[None, Depends(website_limiter)],
    response: Response,
    status: Annotated[str | None, Query(description="Filter by status")] = None,
    sort: Annotated[Literal["created_at", "name"], Query()] = "created_at",
    order: Annotated[Literal["asc", "desc"], Query()] = "desc",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[WebsiteOut]:
    items, total = await service.list_websites(
        principal.tenant_id,
        status=status,
        sort=sort,
        order=order,
        limit=limit,
        offset=offset,
    )
    # Total matching count so clients can paginate without re-parsing the body.
    response.headers["X-Total-Count"] = str(total)
    return [WebsiteOut.from_website(item.website, widget_id=item.widget_id) for item in items]


@router.get("/{website_id}", response_model=WebsiteOut)
async def get_website(
    website_id: str,
    principal: Annotated[Principal, Depends(current_user)],
    service: Annotated[WebsiteService, Depends(get_website_service)],
    _: Annotated[None, Depends(website_limiter)],
) -> WebsiteOut:
    widget = await service.get_widget(principal.tenant_id, website_id)
    website = await service.get_website(principal.tenant_id, website_id)
    return WebsiteOut.from_website(website, widget_id=widget.widget_id)


@router.patch("/{website_id}", response_model=WebsiteOut)
async def update_website(
    website_id: str,
    body: UpdateWebsiteRequest,
    request: Request,
    principal: Annotated[Principal, Depends(current_user)],
    service: Annotated[WebsiteService, Depends(get_website_service)],
    _: Annotated[None, Depends(website_limiter)],
) -> WebsiteOut:
    website = await service.update_website(
        principal=principal,
        website_id=website_id,
        name=body.name,
        url=body.url,
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    widget = await service.get_widget(principal.tenant_id, website.id)
    return WebsiteOut.from_website(website, widget_id=widget.widget_id)


@router.delete("/{website_id}", status_code=204)
async def delete_website(
    website_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(current_user)],
    service: Annotated[WebsiteService, Depends(get_website_service)],
    _: Annotated[None, Depends(website_limiter)],
) -> None:
    await service.delete_website(
        principal=principal,
        website_id=website_id,
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )


@router.get("/{website_id}/widget", response_model=WidgetResponse)
async def get_website_widget(
    website_id: str,
    principal: Annotated[Principal, Depends(current_user)],
    service: Annotated[WebsiteService, Depends(get_website_service)],
    _: Annotated[None, Depends(website_limiter)],
) -> WidgetResponse:
    widget = await service.get_widget(principal.tenant_id, website_id)
    return WidgetResponse(
        widget=WidgetOut.from_widget(widget),
        embed_script=service.build_embed_script(widget.widget_id),
    )


@router.post("/{website_id}/crawl", response_model=StartCrawlResponse, status_code=202)
async def start_website_crawl(
    website_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(current_user)],
    crawl_service: Annotated[CrawlService, Depends(get_crawl_service)],
    _: Annotated[None, Depends(crawl_limiter)],
) -> StartCrawlResponse:
    """Kick off an ingestion run for a tenant-owned website (Phase 4)."""
    job = await crawl_service.start_crawl(
        principal=principal,
        website_id=website_id,
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return StartCrawlResponse(
        crawl_job_id=job.id,
        website_id=job.website_id,
        status=job.status,
        created_at=job.created_at,
    )
