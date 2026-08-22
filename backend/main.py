"""FastAPI application factory for WebChat AI."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from backend import __version__
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
from backend.api.routes.billing import router as billing_router
from backend.api.routes.chat import router as chat_router
from backend.api.routes.conversations import router as conversations_router
from backend.api.routes.crawl_jobs import router as crawl_jobs_router
from backend.api.routes.feedback import router as feedback_router
from backend.api.routes.health import router as health_router
from backend.api.routes.knowledge import router as knowledge_router
from backend.api.routes.webhooks import router as webhooks_router
from backend.api.routes.websites import router as websites_router
from backend.api.routes.widget import router as widget_router
from backend.core.config import get_settings
from backend.core.database import MongoDB
from backend.core.errors import AppError
from backend.core.logging import configure_logging
from backend.core.redis import close_redis

logger = logging.getLogger("webchat_ai")


class VectorConfigurationError(RuntimeError):
    """Raised when stored vectors cannot satisfy the Atlas index contract."""


async def _validate_vector_dimensions() -> None:
    """Check existing vector dimensions in knowledge_chunks match configured EMBEDDING_DIMENSIONS.

    If existing vectors have a different dimension than configured, log a clear
    warning so operators know they must re-index before the system can work correctly.
    """
    settings = get_settings()
    expected_dim = settings.embedding_dimensions
    db = MongoDB.db()
    collection = db["knowledge_chunks"]

    # Sample a few chunks to detect existing dimensions
    sample = (
        await collection.find(
            {"embedding": {"$exists": True, "$ne": None}},
            {"embedding": 1},
        )
        .limit(5)
        .to_list(length=5)
    )

    if not sample:
        return

    detected_dims: dict[int, int] = {}
    for doc in sample:
        emb = doc.get("embedding")
        if emb and isinstance(emb, list):
            dim = len(emb)
            detected_dims[dim] = detected_dims.get(dim, 0) + 1

    for dim, count in detected_dims.items():
        if dim != expected_dim:
            logger.critical(
                "VECTOR DIMENSION MISMATCH: existing knowledge_chunks have dimension %d "
                "(detected from %d sample(s)), but EMBEDDING_DIMENSIONS is configured as %d. "
                "The existing knowledge base MUST be re-indexed before vector search will work "
                "correctly. Delete the knowledge_chunks collection and re-crawl all websites.",
                dim,
                count,
                expected_dim,
            )
            raise VectorConfigurationError(
                f"Stored vector dimension {dim} does not match configured dimension "
                f"{expected_dim}; re-index knowledge_chunks before serving chat."
            )


def _cors_headers_for(request: Request) -> dict[str, str]:
    """Mirror the dashboard CORS policy for a response built outside CORSMiddleware.

    Starlette routes a generic `@app.exception_handler(Exception)` to the
    outermost `ServerErrorMiddleware`, which sends its response with the raw
    server `send` - it never passes back through `CORSMiddleware`. Without
    explicit headers here, an unhandled 500 is invisible to browsers, which
    report a confusing "blocked by CORS policy" instead of the real error.
    """
    settings = get_settings()
    origin = request.headers.get("origin")
    if not origin or origin not in settings.cors_origins:
        return {}
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Credentials": "true",
        "Vary": "Origin",
    }


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Manage application-level resources on startup/shutdown."""
    try:
        await MongoDB.init_indexes()
    except Exception:
        logger.warning("MongoDB unavailable at startup; skipping index creation.")
    # Validate existing vector dimensions against configured embedding_dimensions
    # to prevent silent corruption of $vectorSearch results.
    try:
        await _validate_vector_dimensions()
    except VectorConfigurationError:
        logger.exception("Vector configuration is incompatible with the Atlas index.")
        raise
    except Exception:
        logger.warning("Vector dimension validation skipped (MongoDB unavailable).")
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
        version=__version__,
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
    # Outermost: rejects requests with an unknown Host header before any app
    # middleware or handler runs (Phase 16, `ALLOWED_HOSTS`).
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.effective_allowed_hosts())

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
    async def request_validation_handler(_: FastAPI, exc: RequestValidationError) -> JSONResponse:
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
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "Unhandled error",
            exc_info=exc,
            extra={
                # The request-ID context is already reset by the time this
                # handler runs (it is invoked outside RequestIDMiddleware), so
                # recover the value from the propagated header for correlation.
                "request_id": request.headers.get("x-request-id", "-"),
            },
        )
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "INTERNAL_ERROR", "message": "Internal server error."}},
            headers=_cors_headers_for(request),
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
    app.include_router(knowledge_router, prefix="/api")
    app.include_router(widget_router, prefix="/api")
    app.include_router(billing_router, prefix="/api")
    app.include_router(webhooks_router, prefix="/api")
    app.include_router(admin_router, prefix="/api")

    return app


app = create_app()
