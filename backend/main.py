"""FastAPI application factory for WebChat AI."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.api.middleware import (
    RequestIDMiddleware,
    RequestTimingMiddleware,
    SecurityHeadersMiddleware,
    WidgetCORSHeadersMiddleware,
)
from backend.api.routes.admin import router as admin_router
from backend.api.routes.analytics import router as analytics_router
from backend.api.routes.api_keys import router as api_keys_router
from backend.api.routes.auth import router as auth_router
from backend.api.routes.chat import router as chat_router
from backend.api.routes.conversations import router as conversations_router
from backend.api.routes.crawl_jobs import router as crawl_jobs_router
from backend.api.routes.feedback import router as feedback_router
from backend.api.routes.health import router as health_router
from backend.api.routes.websites import router as websites_router
from backend.api.routes.widget import router as widget_router
from backend.core.config import get_settings
from backend.core.database import MongoDB
from backend.core.errors import AppError
from backend.core.logging import configure_logging, get_request_id
from backend.core.redis import close_redis

logger = logging.getLogger("webchat_ai")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Manage application-level resources on startup/shutdown."""
    try:
        await MongoDB.init_indexes()
    except Exception:
        logger.warning("MongoDB unavailable at startup; skipping index creation.")
    yield
    await MongoDB.close()
    await close_redis()


def create_app() -> FastAPI:
    """Build the application with all routers and middleware registered."""
    settings = get_settings()
    configure_logging()

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
    # WidgetCORS is registered after (thus wraps/runs before) the dashboard
    # CORSMiddleware: `/api/widget/*` gets public `ACAO: *`, and its preflights
    # are answered before the dashboard CORS config is consulted.
    app.add_middleware(WidgetCORSHeadersMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestIDMiddleware)
    # Outermost: measures the full request (incl. the middlewares above). No-op
    # unless PERF_TIMING_LOG_ENABLED=true (Phase 12.1 instrumentation).
    app.add_middleware(RequestTimingMiddleware)

    @app.exception_handler(AppError)
    async def app_error_handler(_: FastAPI, exc: AppError) -> JSONResponse:
        logger.warning(
            "%s (%s): %s",
            exc.code,
            exc.status_code,
            exc.message,
            extra={"error_code": exc.code, "status": exc.status_code},
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message, **exc.extra}},
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(
        _: FastAPI, exc: RequestValidationError
    ) -> JSONResponse:
        """Surface request validation failures in the standard error envelope.

        The frontend parses `error.message`; without this handler FastAPI's
        default `{"detail": [...]}` body would fall back to a generic
        "Request failed (422)" message (e.g. invalid email during signup).
        """
        errors = exc.errors()
        message = str(errors[0]["msg"]) if errors else "Invalid request."
        if message.startswith("Value error, "):
            message = message[len("Value error, ") :]
        logger.warning(
            "Validation error: %s", message, extra={"error_code": "VALIDATION_ERROR", "status": 422}
        )
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "VALIDATION_ERROR", "message": message}},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(_: FastAPI, exc: Exception) -> JSONResponse:
        logger.exception(
            "Unhandled error",
            exc_info=exc,
            extra={"request_id": get_request_id()},
        )
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "INTERNAL_ERROR", "message": "Internal server error."}},
        )

    app.include_router(health_router, prefix="/api")
    app.include_router(auth_router, prefix="/api")
    app.include_router(websites_router, prefix="/api")
    app.include_router(crawl_jobs_router, prefix="/api")
    app.include_router(chat_router, prefix="/api")
    app.include_router(conversations_router, prefix="/api")
    app.include_router(analytics_router, prefix="/api")
    app.include_router(api_keys_router, prefix="/api")
    app.include_router(feedback_router, prefix="/api")
    app.include_router(widget_router, prefix="/api")
    app.include_router(admin_router, prefix="/api")

    return app


app = create_app()
