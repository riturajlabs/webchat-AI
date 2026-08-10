"""Shared FastAPI dependencies: database, auth service, rate limiting, CSRF.

Layering per 00-AI-Development-Rules.md: routes depend on services and the
repository Protocol implementations bound here. ADR-004 (rate limiting) and
ADR-003 (double-submit CSRF) are enforced as dependencies.
"""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from typing import Annotated, Any

from fastapi import Depends, Header, Request
from motor.motor_asyncio import AsyncIOMotorDatabase
from redis.asyncio import Redis

from backend.ai.registry import build_embedding_fallback, build_generation_fallback
from backend.core.config import get_settings
from backend.core.database import MongoDB
from backend.core.errors import (
    CsrfError,
    ForbiddenError,
    InvalidCredentialsError,
    RateLimitExceededError,
    ServiceUnavailableError,
)
from backend.core.rate_limit import SlidingWindowRateLimiter
from backend.core.redis import get_redis
from backend.core.security import csrf_tokens_match, decode_widget_session_token
from backend.repositories import (
    MongoAuditLogRepository,
    MongoChatMessageRepository,
    MongoChatSessionRepository,
    MongoCrawlJobRepository,
    MongoMemberRepository,
    MongoRefreshTokenRepository,
    MongoTenantRepository,
    MongoUsageRecordRepository,
    MongoUserRepository,
    MongoWebsiteRepository,
    MongoWidgetRepository,
    get_vector_repository,
)
from backend.services.auth import AuthService, Principal
from backend.services.chat.rag_service import RagService
from backend.services.crawl import CrawlService
from backend.services.website import WebsiteService
from backend.services.widget import WidgetService
from backend.workers.jobs.crawl import enqueue_crawl_website
from backend.workers.jobs.email import enqueue_email


def get_db() -> AsyncIOMotorDatabase[Any]:
    """Provide the shared application database handle."""
    return MongoDB.db()


def get_auth_service(
    db: Annotated[AsyncIOMotorDatabase[Any], Depends(get_db)],
) -> AuthService:
    """Build the auth service with MongoDB-backed repositories.

    Emails are enqueued to the ARQ worker (`send_email` job) so API requests
    never block on mail delivery (ADR-001).
    """
    return AuthService(
        users=MongoUserRepository(db),
        tenants=MongoTenantRepository(db),
        members=MongoMemberRepository(db),
        refresh_tokens=MongoRefreshTokenRepository(db),
        audit=MongoAuditLogRepository(db),
        mail_dispatcher=enqueue_email,
    )


def get_website_service(
    db: Annotated[AsyncIOMotorDatabase[Any], Depends(get_db)],
) -> WebsiteService:
    """Build the website service with MongoDB-backed repositories."""
    return WebsiteService(
        websites=MongoWebsiteRepository(db),
        widgets=MongoWidgetRepository(db),
        audit=MongoAuditLogRepository(db),
    )


def get_crawl_service(
    db: Annotated[AsyncIOMotorDatabase[Any], Depends(get_db)],
) -> CrawlService:
    """Build the crawl service with MongoDB-backed repositories.

    The ARQ `crawl_website` task is enqueued so `start_crawl` never blocks on
    worker execution (ADR-002).
    """
    return CrawlService(
        crawl_jobs=MongoCrawlJobRepository(db),
        websites=MongoWebsiteRepository(db),
        audit=MongoAuditLogRepository(db),
        enqueue=enqueue_crawl_website,
    )


def get_rag_service(
    db: Annotated[AsyncIOMotorDatabase[Any], Depends(get_db)],
) -> RagService:
    """Build the RAG service with MongoDB-backed repositories (Phase 6).

    Embedding and generation resolve through the Phase 9 fallback chains
    (ADR-009): providers are tried in `*_PROVIDER_ORDER`, missing-key providers
    are skipped, and the chain fails only when every provider is unavailable.
    Clients are built lazily - building the chain never touches the network,
    and API keys come from settings (env) and are never logged or exposed.
    Retrieval goes through the vector repository, which is always tenant-scoped
    (ADR-008).
    """
    return RagService(
        websites=MongoWebsiteRepository(db),
        vector=get_vector_repository(db),
        embedder=build_embedding_fallback(),
        generation=build_generation_fallback(),
        sessions=MongoChatSessionRepository(db),
        messages=MongoChatMessageRepository(db),
        usage=MongoUsageRecordRepository(db),
    )


class _RedisWidgetStore:
    """Adapter exposing Redis's minimal surface to `WidgetService`."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def get(self, key: str) -> str | None:
        value = await self._redis.get(key)
        return str(value) if value is not None else None

    async def setex(self, key: str, seconds: int, value: str) -> None:
        await self._redis.setex(key, seconds, value)

    async def incr(self, key: str) -> int:
        return int(await self._redis.incr(key))

    async def expire(self, key: str, seconds: int) -> None:
        await self._redis.expire(key, seconds)


def get_widget_service(
    db: Annotated[AsyncIOMotorDatabase[Any], Depends(get_db)],
) -> WidgetService:
    """Build the public widget service with MongoDB + Redis (Phase 8)."""
    return WidgetService(
        widgets=MongoWidgetRepository(db),
        tenants=MongoTenantRepository(db),
        websites=MongoWebsiteRepository(db),
        store=_RedisWidgetStore(get_redis()),
    )


def get_access_token(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> str:
    """Extract and validate the `Authorization: Bearer <token>` header."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise InvalidCredentialsError("Missing or malformed Authorization header.")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise InvalidCredentialsError("Missing or malformed Authorization header.")
    return token


async def current_user(
    access_token: Annotated[str, Depends(get_access_token)],
    auth: Annotated[AuthService, Depends(get_auth_service)],
) -> Principal:
    """Resolve the authenticated principal for a bearer-token request."""
    return await auth.authenticate(access_token)


def require_role(*roles: str) -> Callable[[Principal], None]:
    """Return a FastAPI dependency guarding a route for one of `roles`.

    Usage: `Depends(require_role("admin"))` or `Depends(require_role("owner", "admin"))`.
    The authenticated principal's resolved tenant role must be in `roles`;
    otherwise a 403 `FORBIDDEN` error is raised (tenant isolation is enforced
    by `current_user`/`authenticate`, which always re-checks the live tenant).
    """

    def _require(principal: Annotated[Principal, Depends(current_user)]) -> None:
        if principal.role not in roles:
            raise ForbiddenError("Insufficient permissions for this action.")

    return _require


def client_ip(request: Request) -> str:
    """Best-effort client IP.

    `X-Forwarded-For` is honored only when `TRUST_PROXY=true` (i.e. behind a
    trusted reverse proxy). Otherwise the direct connection IP is used so the
    header cannot be spoofed to bypass rate limits.
    """
    if get_settings().trust_proxy:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class _RedisRateLimitStore:
    """Adapter exposing Redis's minimal ZSET surface to the rate limiter.

    The adapter pins the loosely-typed `redis.asyncio` overloads to the exact
    `RateLimitStore` protocol surface (ADR-004).
    """

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def zadd(self, name: str, mapping: Mapping[str, float]) -> int:
        return int(await self._redis.zadd(name, mapping))

    async def zremrangebyscore(self, name: str, min: int, max: float) -> int:
        return int(await self._redis.zremrangebyscore(name, min, max))

    async def zcard(self, name: str) -> int:
        return int(await self._redis.zcard(name))

    async def expire(self, name: str, time: int) -> bool:
        return bool(await self._redis.expire(name, time))


class RateLimitDependency:
    """Sliding-window rate limiter bound to a route via FastAPI dependency.

    Fails closed: if Redis is unreachable the request is rejected with 503
    rather than served without protection (ADR-004).
    """

    def __init__(self, *, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window_seconds = window_seconds

    async def __call__(self, request: Request) -> None:
        settings = get_settings()
        if not settings.rate_limit_enabled:
            return
        limiter = SlidingWindowRateLimiter(
            _RedisRateLimitStore(get_redis()), limit=self.limit, window_seconds=self.window_seconds
        )
        key = f"rl:{request.url.path}:{client_ip(request)}"
        try:
            allowed = await limiter.consume(key)
        except Exception as exc:
            raise ServiceUnavailableError("Rate limiter is temporarily unavailable.") from exc
        if not allowed:
            raise RateLimitExceededError("Too many requests. Please try again later.")


# Per-endpoint limits (Phase 2 auth abuse protection, ADR-004).
register_limiter = RateLimitDependency(limit=10, window_seconds=3600)
login_limiter = RateLimitDependency(limit=20, window_seconds=900)
verify_email_limiter = RateLimitDependency(limit=10, window_seconds=3600)
forgot_password_limiter = RateLimitDependency(limit=5, window_seconds=3600)
reset_password_limiter = RateLimitDependency(limit=5, window_seconds=3600)
# Phase 3 website-management abuse protection (create/update/delete/list/get).
website_limiter = RateLimitDependency(limit=120, window_seconds=3600)
# Phase 4 ingestion abuse protection (crawl kick-off + job status polling).
crawl_limiter = RateLimitDependency(limit=30, window_seconds=3600)
# Phase 6 chat abuse protection (ADR-004 per-widget message limit; dashboard
# chat uses the same budget until the widget API lands in Phase 8).
chat_limiter = RateLimitDependency(limit=60, window_seconds=60)


class WidgetRateLimitDependency:
    """Sliding-window limiter keyed by an entity (widget/visitor) instead of IP.

    Phase 8 (ADR-004 §widget abuse table): per-widget and per-visitor budgets
    are independent sliding windows. The key factory derives the Redis key from
    the request (e.g. `rl:widget:{widget_id}`, `rl:visitor:{visitor_id}`) so the
    budget tracks the entity, not the connection. Fails closed like
    `RateLimitDependency` (503 on Redis outage). Limits resolve from settings
    at call time (`limit_setting` names the `Settings` field) so test
    environments can override them without reimporting.
    """

    def __init__(
        self,
        *,
        key_factory: Callable[[Request], Awaitable[str] | str],
        limit: int | None = None,
        window_seconds: int | None = None,
        limit_setting: str | None = None,
    ) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self.limit_setting = limit_setting
        self._key_factory = key_factory

    async def __call__(self, request: Request) -> None:
        settings = get_settings()
        if not settings.widget_rate_limit_enabled:
            return
        limit = self.limit
        if limit is None and self.limit_setting is not None:
            limit = int(getattr(settings, self.limit_setting))
        if limit is None or self.window_seconds is None:
            return
        limiter = SlidingWindowRateLimiter(
            _RedisRateLimitStore(get_redis()), limit=limit, window_seconds=self.window_seconds
        )
        result = self._key_factory(request)
        key = (await result) if asyncio.iscoroutine(result) else result
        try:
            allowed = await limiter.consume(str(key))
        except Exception as exc:
            raise ServiceUnavailableError("Rate limiter is temporarily unavailable.") from exc
        if not allowed:
            raise RateLimitExceededError("Too many requests. Please try again later.")


def widget_visitor_id(request: Request) -> str:
    """Anonymous visitor id from the widget session claims (`"anon"` fallback)."""
    claims = getattr(request.state, "widget_claims", None) or {}
    return str(claims.get("visitor_id") or "anon")


def _widget_rate_limit_key(request: Request) -> str:
    claims = getattr(request.state, "widget_claims", None) or {}
    return f"rl:widget:{claims.get('widget_id', 'unknown')}"


def _visitor_rate_limit_key(request: Request) -> str:
    return f"rl:visitor:{widget_visitor_id(request)}"


async def _session_issue_rate_limit_key(request: Request) -> str:
    """Key the session-issue limit by the requested widget_id.

    `POST /sessions` is anonymous, so the widget_id comes from the body
    (matching the same budget as the chat per-widget limit).
    """
    widget_id = "unknown"
    try:
        body = await request.json()
        widget_id = str(body.get("widget_id") or widget_id)
    except Exception:
        pass
    return f"rl:widget:{widget_id}"


# Phase 8 widget abuse protection (ADR-004 §widget):
#  * per-widget: WIDGET_PER_WIDGET_LIMIT / min (60)
#  * per-visitor: WIDGET_PER_VISITOR_LIMIT / min (20)
#  * session issue: WIDGET_SESSION_ISSUE_LIMIT / min (30)
widget_chat_limiter = WidgetRateLimitDependency(
    key_factory=_widget_rate_limit_key,
    window_seconds=60,
    limit_setting="widget_per_widget_limit",
)
widget_visitor_limiter = WidgetRateLimitDependency(
    key_factory=_visitor_rate_limit_key,
    window_seconds=60,
    limit_setting="widget_per_visitor_limit",
)
widget_session_issue_limiter = WidgetRateLimitDependency(
    key_factory=_session_issue_rate_limit_key,
    window_seconds=60,
    limit_setting="widget_session_issue_limit",
)


async def widget_session_claims(
    request: Request,
    access_token: Annotated[str, Depends(get_access_token)],
) -> dict[str, Any]:
    """Decode the `Authorization: Bearer` widget-session token (Phase 8).

    Stashes the claims on `request.state.widget_claims` so the widget/visitor
    rate-limit key factories (above) can derive their keys from the same
    decoded identity without re-parsing the token.
    """
    claims = decode_widget_session_token(access_token)
    request.state.widget_claims = claims
    return claims


async def verify_csrf(request: Request) -> None:
    """Double-submit CSRF check for cookie-authenticated routes (ADR-003).

    The non-httpOnly `csrf_token` cookie must match the `X-CSRF-Token` header.
    """
    settings = get_settings()
    cookie = request.cookies.get(settings.csrf_cookie_name, "")
    header = request.headers.get("X-CSRF-Token", "")
    if not cookie or not header or not csrf_tokens_match(cookie, header):
        raise CsrfError("CSRF token missing or invalid.")
