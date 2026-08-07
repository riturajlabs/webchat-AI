"""Health and readiness endpoints."""

from fastapi import APIRouter

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
async def ready() -> dict[str, object]:
    """Return 200 only when all dependencies are reachable."""
    database_ok = await MongoDB.ping()
    redis_ok = await ping_redis()
    if not database_ok or not redis_ok:
        return {
            "status": "degraded",
            "checks": {
                "database": database_ok,
                "redis": redis_ok,
            },
        }
    return {"status": "ready"}
