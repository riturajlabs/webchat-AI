"""Crawl job status endpoints (Phase 4, ADR-002).

Progress is published by the ARQ worker onto the `crawl_jobs` document; this
route lets the dashboard poll live status. Tenancy comes from the
authenticated principal - a foreign tenant can never read another tenant's
crawl jobs (00-AI-Development-Rules §7).
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from backend.api.deps import (
    current_user,
    get_crawl_service,
    require_role,
    website_limiter,
)
from backend.schemas.crawl import CrawlJobOut
from backend.services.auth import Principal
from backend.services.crawl import CrawlService

router = APIRouter(
    prefix="/crawl-jobs",
    tags=["crawl-jobs"],
    dependencies=[Depends(require_role("owner", "admin"))],
)


@router.get("/{job_id}", response_model=CrawlJobOut)
async def get_crawl_job(
    job_id: str,
    principal: Annotated[Principal, Depends(current_user)],
    service: Annotated[CrawlService, Depends(get_crawl_service)],
    _: Annotated[None, Depends(website_limiter)],
) -> CrawlJobOut:
    job = await service.get_crawl_job(principal.tenant_id, job_id)
    return CrawlJobOut.from_job(job)
