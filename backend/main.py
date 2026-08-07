"""FastAPI application factory for WebChat AI."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.middleware import RequestIDMiddleware, SecurityHeadersMiddleware
from backend.api.routes.health import router as health_router
from backend.core.config import get_settings
from backend.core.database import MongoDB
from backend.core.redis import close_redis


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Manage application-level resources on startup/shutdown."""
    yield
    await MongoDB.close()
    await close_redis()


def create_app() -> FastAPI:
    """Build the application with all routers and middleware registered."""
    settings = get_settings()

    app = FastAPI(
        title="WebChat AI API",
        description="Multi-tenant RAG SaaS backend.",
        version="0.1.0",
        docs_url="/api/docs" if settings.debug else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.debug else None,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestIDMiddleware)

    app.include_router(health_router, prefix="/api")

    return app


app = create_app()
