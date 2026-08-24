"""Prometheus metrics exposition (Phase 3)."""

from fastapi import APIRouter
from starlette.responses import PlainTextResponse

from backend.core.metrics import render_prometheus

router = APIRouter(tags=["system"])

_METRICS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


@router.get("/metrics", summary="Prometheus metrics")
async def metrics() -> PlainTextResponse:
    """Expose process-local counters/histograms for scraping.

    Intentionally unauthenticated like the health endpoints: it carries only
    aggregate counts and latency distributions with fixed label schemas —
    never tenant data (Phase 3 tenant-safe labels). Reverse proxies should
    restrict external access to this path.
    """
    return PlainTextResponse(render_prometheus(), media_type=_METRICS_CONTENT_TYPE)
