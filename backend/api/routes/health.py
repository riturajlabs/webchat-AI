"""Health and readiness endpoints."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.core.database import MongoDB
from backend.core.redis import ping_redis

router = APIRouter(tags=["system"])


@router.get("/health", summary="Liveness probe")
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
            content={"status": "degraded", "checks": checks},
        )
    return JSONResponse(status_code=200, content={"status": "ready"})
