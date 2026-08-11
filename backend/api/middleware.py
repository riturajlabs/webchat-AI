"""HTTP middleware: request-ID correlation, baseline security headers, timing.

ADR-007 places this module at `backend/api/middleware.py`. Security headers are
the first-pass baseline; the full hardening audit is Phase 11 (ADR-008).
"""

import logging
import time
import uuid
from collections.abc import MutableMapping
from typing import Any

from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from backend.core.config import get_settings
from backend.core.logging import request_id_var

logger = logging.getLogger("webchat_ai")

# Baseline security headers applied to every HTTP response. Headers already
# set by an inner handler are preserved.
_SAFE_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    "Content-Security-Policy": "default-src 'none'",
}

_HEADER_NAME = "X-Request-ID"


class RequestIDMiddleware:
    """Correlate every response with a request ID for log tracing.

    Propagates an inbound `X-Request-ID` when present, otherwise generates a
    new one and attaches it to the response.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _extract_request_id(scope.get("headers", []))
        token = request_id_var.set(request_id)

        async def send_with_id(message: MutableMapping[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((_HEADER_NAME.lower().encode("latin1"), request_id.encode("latin1")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            request_id_var.reset(token)


class SecurityHeadersMiddleware:
    """Append baseline security headers to every HTTP response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: MutableMapping[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                existing = {name.decode("latin1").lower() for name, _ in headers}
                headers.extend(
                    (name.lower().encode("latin1"), value.encode("latin1"))
                    for name, value in _SAFE_HEADERS.items()
                    if name.lower() not in existing
                )
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


# Public widget namespace only (Phase 8, ADR-004 §CORS): `Access-Control-Allow-Origin: *`,
# no credentials, restricted methods/headers. Everything under `/api/widget/` gets the
# public policy; the dashboard surface keeps the strict origin + credentials CORS in
# `main.py`. This middleware runs *outside* the app-level `CORSMiddleware` and answers
# widget preflights itself so the dashboard CORS config can never weaken or be weakened.
_WIDGET_PREFIX = "/api/widget/"
_WIDGET_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Authorization, Content-Type",
}


class WidgetCORSHeadersMiddleware:
    """Apply public `ACAO: *` (no credentials) headers to the widget API.

    OPTIONS preflights to `/api/widget/*` are answered directly by this
    middleware (the global `CORSMiddleware` never sees them), and actual
    responses get the public allow-origin appended. No `Access-Control-Allow-
    Credentials` header is ever emitted on the widget surface.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith(_WIDGET_PREFIX):
            await self.app(scope, receive, send)
            return

        if scope["method"] == "OPTIONS":
            response = Response(status_code=204, headers=_WIDGET_CORS_HEADERS)
            await response(scope, receive, send)
            return

        async def send_with_cors(message: MutableMapping[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                existing = {name.decode("latin1").lower() for name, _ in headers}
                # The inner CORSMiddleware may have emitted credentials-scoped
                # headers when the origin happens to be a dashboard origin;
                # the widget surface must never carry them.
                headers = [
                    (name, value)
                    for name, value in headers
                    if name.decode("latin1").lower()
                    not in {"access-control-allow-origin", "access-control-allow-credentials"}
                ]
                headers.extend(
                    (name.lower().encode("latin1"), value.encode("latin1"))
                    for name, value in _WIDGET_CORS_HEADERS.items()
                    if name.lower() not in existing
                )
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_cors)


class RequestTimingMiddleware:
    """Log one structured record per HTTP request with server-side duration.

    Opt-in (`PERF_TIMING_LOG_ENABLED=true`): records method, path, response
    status and total duration (to `http.response.complete`, so streaming SSE
    responses are measured end-to-end) at INFO level. Disabled by default so
    default log volume is unchanged (Phase 12.1 instrumentation).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not get_settings().perf_timing_log_enabled:
            await self.app(scope, receive, send)
            return

        started = time.perf_counter()
        status: int | None = None

        async def send_with_timing(message: MutableMapping[str, Any]) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message.get("status")
            await send(message)

        try:
            await self.app(scope, receive, send_with_timing)
        finally:
            duration_ms = (time.perf_counter() - started) * 1000.0
            logger.info(
                "http_request",
                extra={
                    "method": scope.get("method"),
                    "path": scope.get("path"),
                    "status": status,
                    "duration_ms": round(duration_ms, 2),
                },
            )


def _extract_request_id(headers: list[tuple[bytes, bytes]]) -> str:
    for name, value in headers:
        if name.lower() == _HEADER_NAME.lower().encode("latin1"):
            return value.decode("latin1")
    return str(uuid.uuid4())
