"""Health and readiness endpoints (Phase 16 monitoring)."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend import __version__
from backend.core.config import get_settings
from backend.core.database import MongoDB
from backend.core.redis import ping_redis

router = APIRouter(tags=["system"])


def _service_info() -> dict[str, str]:
    """Version + environment pair attached to every health payload."""
    settings = get_settings()
    return {
        "version": __version__,
        "environment": settings.environment,
    }


@router.get("/health/live", summary="Liveness probe")
async def live() -> dict[str, str]:
    """Return 200 as long as the process is up and accepting requests.

    Liveness deliberately avoids dependency I/O (Mongo/Redis pings can stall
    on a network partition); orchestrators that distinguish liveness from
    readiness should use this for restarts and `/health/ready` for routing.
    """
    return {"status": "alive", **_service_info()}


@router.get("/health", summary="Liveness probe with dependency status")
async def health() -> dict[str, object]:
    """Return 200 when the API process is alive, with dependency status."""
    database_ok = await MongoDB.ping()
    redis_ok = await ping_redis()
    return {
        "status": "ok",
        "checks": {
            "database": database_ok,
            "redis": redis_ok,
        },
        **_service_info(),
    }


@router.get("/health/ready", summary="Readiness probe")
async def ready() -> JSONResponse:
    """Return 200 only when all dependencies are reachable, else 503.

    Load balancers and orchestrators rely on the HTTP status to route or
    drain traffic, so an unhealthy dependency must fail closed (503) rather
    than report 200 with a "degraded" body.
    """
    database_ok = await MongoDB.ping()
    redis_ok = await ping_redis()
    checks = {
        "database": database_ok,
        "redis": redis_ok,
    }
    if not database_ok or not redis_ok:
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "checks": checks, **_service_info()},
        )
    return JSONResponse(status_code=200, content={"status": "ready", **_service_info()})
