"""HTTP middleware: request-ID correlation and baseline security headers.

ADR-007 places this module at `backend/api/middleware.py`. Security headers are
the first-pass baseline; the full hardening audit is Phase 11 (ADR-008).
"""

import uuid
from collections.abc import MutableMapping
from typing import Any

from starlette.types import ASGIApp, Receive, Scope, Send

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

        async def send_with_id(message: MutableMapping[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((_HEADER_NAME.lower().encode("latin1"), request_id.encode("latin1")))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_id)


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


def _extract_request_id(headers: list[tuple[bytes, bytes]]) -> str:
    for name, value in headers:
        if name.lower() == _HEADER_NAME.lower().encode("latin1"):
            return value.decode("latin1")
    return str(uuid.uuid4())
