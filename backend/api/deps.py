"""Shared FastAPI dependencies: database, auth service, rate limiting, CSRF.

Layering per 00-AI-Development-Rules.md: routes depend on services and the
repository Protocol implementations bound here. ADR-004 (rate limiting) and
ADR-003 (double-submit CSRF) are enforced as dependencies.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import Depends, Header, Path, Request
from motor.motor_asyncio import AsyncIOMotorDatabase
from redis.asyncio import Redis

from backend.ai.gemini import GenerationClient
from backend.ai.registry import (
    build_embedding_fallback,
    build_generation_fallback,
    build_generation_providers,
)
from backend.core.cache import RedisCacheStore
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
from backend.core.rbac import ADMIN_ROLES, meets_any
from backend.core.redis import get_redis
from backend.core.security import (
    API_KEY_PREFIX,
    csrf_tokens_match,
    decode_widget_session_token,
    hash_refresh_token,
)
from backend.repositories import (
    MongoAdminAuditLogRepository,
    MongoAdminRepository,
    MongoAnalyticsRepository,
    MongoApiKeyRepository,
    MongoAuditLogRepository,
    MongoChatMessageRepository,
    MongoChatSessionRepository,
    MongoCrawlJobRepository,
    MongoDocumentRepository,
    MongoFeedbackRepository,
    MongoMemberRepository,
    MongoRefreshTokenRepository,
    MongoSubscriptionRepository,
    MongoTenantPurgeRepository,
    MongoTenantRepository,
    MongoUsageEventRepository,
    MongoUsageRecordRepository,
    MongoUserRepository,
    MongoWebsiteRepository,
    MongoWidgetRepository,
    get_vector_repository,
)
from backend.schemas.widget import CreateWidgetSessionRequest
from backend.services.account import AccountService
from backend.services.admin import AdminService
from backend.services.ai.provider_health import ProviderHealthStore
from backend.services.ai.provider_router import AdaptiveProviderRouter
from backend.services.analytics import AnalyticsService
from backend.services.api_keys import ApiKeyPrincipal, ApiKeyService
from backend.services.auth import AuthService, Principal
from backend.services.billing import (
    PaymentProvider,
    SubscriptionService,
    UsageService,
    build_payment_provider,
)
from backend.services.chat.rag_service import RagService
from backend.services.conversations import ConversationService
from backend.services.crawl import CrawlService
from backend.services.feedback import FeedbackService
from backend.services.knowledge import KnowledgeService
from backend.services.website import WebsiteService
from backend.services.widget import WidgetConfigService, WidgetService
from backend.workers.jobs.crawl import enqueue_crawl_website
from backend.workers.jobs.email import enqueue_email
from backend.workers.jobs.knowledge import enqueue_process_document

if TYPE_CHECKING:
    from backend.core.quota import LLMQuotaService

logger = logging.getLogger("webchat_ai")


def get_db() -> AsyncIOMotorDatabase[Any]:
    """Provide the shared application database handle."""
    return MongoDB.db()


def get_auth_service(
    db: Annotated[AsyncIOMotorDatabase[Any], Depends(get_db)],
) -> AuthService:
    """Build the auth service with MongoDB-backed repositories.

    Emails are enqueued to the ARQ worker (`send_email` job) so API requests
    never block on mail delivery (ADR-001).

    When Redis is available, role resolution is cached per-user (PERF-1, 60 s
    TTL) to avoid a ``members`` lookup on every authenticated request.
    """
    settings = get_settings()
    role_cache: RedisCacheStore | None = None
    if settings.redis_url:
        role_cache = RedisCacheStore(
            redis=get_redis(),
            prefix=f"{settings.redis_prefix}:auth",
        )
    return AuthService(
        users=MongoUserRepository(db),
        tenants=MongoTenantRepository(db),
        members=MongoMemberRepository(db),
        refresh_tokens=MongoRefreshTokenRepository(db),
        audit=MongoAuditLogRepository(db),
        mail_dispatcher=enqueue_email,
        role_cache=role_cache,
    )


def get_account_service(
    db: Annotated[AsyncIOMotorDatabase[Any], Depends(get_db)],
) -> AccountService:
    """Build the account service with MongoDB-backed repositories.

    Self-service account deletion orchestrates an application-level cascade
    purge across every tenant-scoped collection (MongoDB has no FK CASCADE).
    """
    return AccountService(
        users=MongoUserRepository(db),
        audit=MongoAuditLogRepository(db),
        purge=MongoTenantPurgeRepository(db),
    )


def get_usage_service(
    db: Annotated[AsyncIOMotorDatabase[Any], Depends(get_db)],
) -> UsageService:
    """Build the billing usage service with MongoDB-backed repositories.

    Phase 13 gates chat messages, website creation and crawls against the
    tenant's plan, and reports `/api/billing/usage`. Phase 14 resolves the
    plan from the tenant's active subscription (via `subscriptions`) before
    falling back to `tenants.plan`.
    """
    return UsageService(
        events=MongoUsageEventRepository(db),
        tenants=MongoTenantRepository(db),
        websites=MongoWebsiteRepository(db),
        documents=MongoDocumentRepository(db),
        subscriptions=MongoSubscriptionRepository(db),
    )


def get_payment_provider() -> PaymentProvider:
    """Resolve the configured payment gateway implementation (Phase 14)."""
    return build_payment_provider(get_settings())


def get_llm_quota_service() -> "LLMQuotaService":
    """Build the per-tenant AI quota limiter (Phase 14.9.4)."""
    from backend.core.quota import LLMQuotaService

    return LLMQuotaService()


def get_subscription_service(
    db: Annotated[AsyncIOMotorDatabase[Any], Depends(get_db)],
    provider: Annotated[PaymentProvider, Depends(get_payment_provider)],
) -> SubscriptionService:
    """Build the subscription service (checkout, webhook activation, reads).

    Phase 14: `create_checkout` delegates to the payment provider and
    `activate_payment` appends a `subscriptions` document per paid billing
    period (payment history).
    """
    return SubscriptionService(
        subscriptions=MongoSubscriptionRepository(db),
        provider=provider,
        tenants=MongoTenantRepository(db),
        currency=get_settings().payment_currency,
    )


def get_website_service(
    db: Annotated[AsyncIOMotorDatabase[Any], Depends(get_db)],
    usage: Annotated[UsageService, Depends(get_usage_service)],
) -> WebsiteService:
    """Build the website service with MongoDB-backed repositories."""
    return WebsiteService(
        websites=MongoWebsiteRepository(db),
        widgets=MongoWidgetRepository(db),
        audit=MongoAuditLogRepository(db),
        usage=usage,
        documents=MongoDocumentRepository(db),
        vector=get_vector_repository(db),
        chat_sessions=MongoChatSessionRepository(db),
        chat_messages=MongoChatMessageRepository(db),
        feedback=MongoFeedbackRepository(db),
        crawl_jobs=MongoCrawlJobRepository(db),
        usage_records=MongoUsageRecordRepository(db),
    )


def get_crawl_service(
    db: Annotated[AsyncIOMotorDatabase[Any], Depends(get_db)],
    usage: Annotated[UsageService, Depends(get_usage_service)],
) -> CrawlService:
    """Build the crawl service with MongoDB-backed repositories.

    The ARQ `crawl_website` task is enqueued so `start_crawl` never blocks on
    worker execution (ADR-002). Phase 13 limit enforcement (documents +
    crawl_pages) runs before the job is queued.
    """
    return CrawlService(
        crawl_jobs=MongoCrawlJobRepository(db),
        websites=MongoWebsiteRepository(db),
        audit=MongoAuditLogRepository(db),
        enqueue=enqueue_crawl_website,
        usage=usage,
    )


def get_knowledge_service(
    db: Annotated[AsyncIOMotorDatabase[Any], Depends(get_db)],
) -> KnowledgeService:
    """Build the knowledge service with MongoDB-backed repositories.

    `enqueue` submits the per-document embedding job to the ARQ worker, so the
    manual retry action never blocks on worker execution (ADR-002).
    """
    return KnowledgeService(
        websites=MongoWebsiteRepository(db),
        documents=MongoDocumentRepository(db),
        audit=MongoAuditLogRepository(db),
        enqueue=enqueue_process_document,
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

    When ``AI_PROVIDER_ROUTING_MODE=adaptive``, an ``AdaptiveProviderRouter``
    wraps the generation providers and uses Redis-backed health state to
    reorder the fallback chain per-request (Phase 12.6).
    """
    settings = get_settings()
    rag_cache: RedisCacheStore | None = None
    if settings.redis_url:
        rag_cache = RedisCacheStore(
            redis=get_redis(),
            prefix=f"{settings.redis_prefix}:rag",
        )
    if settings.ai_provider_routing_mode == "adaptive" and settings.redis_url:
        health = ProviderHealthStore(
            redis=get_redis(),
            cooldown_seconds=settings.ai_provider_cooldown_seconds,
            health_check_interval=settings.ai_provider_health_check_interval,
        )
        generation: GenerationClient = AdaptiveProviderRouter(
            providers=build_generation_providers(),
            health=health,
            recovery_window_seconds=settings.ai_provider_recovery_window_seconds,
        )
    else:
        generation = build_generation_fallback()
    return RagService(
        websites=MongoWebsiteRepository(db),
        vector=get_vector_repository(db),
        embedder=build_embedding_fallback(max_retries=settings.chat_embedding_max_retries),
        generation=generation,
        sessions=MongoChatSessionRepository(db),
        messages=MongoChatMessageRepository(db),
        usage=MongoUsageRecordRepository(db),
        cache=rag_cache,
    )


def get_conversation_service(
    db: Annotated[AsyncIOMotorDatabase[Any], Depends(get_db)],
) -> ConversationService:
    """Build the conversation service with MongoDB-backed repositories (Phase 11.2)."""
    return ConversationService(
        sessions=MongoChatSessionRepository(db),
        messages=MongoChatMessageRepository(db),
        audit=MongoAuditLogRepository(db),
    )


def get_analytics_service(
    db: Annotated[AsyncIOMotorDatabase[Any], Depends(get_db)],
) -> AnalyticsService:
    """Build the read-only analytics service (Phase 11.3, docs/02-TRD.md §11).

    Reports over the daily `usage_records` rollup, `chat_sessions`,
    `messages` and `websites` that the chat pipeline already maintains
    (ADR-005 §5.5) - no new write path.
    """
    return AnalyticsService(analytics=MongoAnalyticsRepository(db))


def get_api_key_service(
    db: Annotated[AsyncIOMotorDatabase[Any], Depends(get_db)],
) -> ApiKeyService:
    """Build the API key service with MongoDB-backed repositories (docs/05 §12).

    `tenants` is needed so `authenticate_api_key` can re-check that the owning
    tenant is still active before resolving a `wc_*` key to a principal.
    """
    return ApiKeyService(
        keys=MongoApiKeyRepository(db),
        audit=MongoAuditLogRepository(db),
        tenants=MongoTenantRepository(db),
    )


def get_feedback_service(
    db: Annotated[AsyncIOMotorDatabase[Any], Depends(get_db)],
) -> FeedbackService:
    """Build the feedback service with MongoDB-backed repositories (Phase 12.4).

    The submit path re-validates the untrusted message/session ids against the
    authenticated widget's tenant/website via `MongoChatMessageRepository`
    (ADR-004 never-trust-claims rule).
    """
    return FeedbackService(
        feedback=MongoFeedbackRepository(db),
        messages=MongoChatMessageRepository(db),
    )


def get_admin_service(
    db: Annotated[AsyncIOMotorDatabase[Any], Depends(get_db)],
) -> AdminService:
    """Build the platform admin service (Phase 12.5 + Phase 15).

    Reuses the same collections the tenant surfaces read/write (ADR-006: no
    new collections) plus the Phase 14 `subscriptions` append-log for revenue.
    Tenant mutations keep the shared audit write AND append the dedicated
    `admin_audit_logs` trail (ADR-006 §Security).
    """
    settings = get_settings()
    return AdminService(
        tenants=MongoTenantRepository(db),
        users=MongoUserRepository(db),
        websites=MongoWebsiteRepository(db),
        usage=MongoUsageRecordRepository(db),
        crawl_jobs=MongoCrawlJobRepository(db),
        audit=MongoAuditLogRepository(db),
        refresh_tokens=MongoRefreshTokenRepository(db),
        stats=MongoAdminRepository(db),
        subscriptions=MongoSubscriptionRepository(db),
        admin_audit=MongoAdminAuditLogRepository(db),
        currency=settings.payment_currency,
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

    async def delete(self, key: str) -> None:
        await self._redis.delete(key)


def get_widget_service(
    db: Annotated[AsyncIOMotorDatabase[Any], Depends(get_db)],
) -> WidgetService:
    """Build the public widget service with MongoDB + Redis (Phase 8)."""
    return WidgetService(
        widgets=MongoWidgetRepository(db),
        tenants=MongoTenantRepository(db),
        websites=MongoWebsiteRepository(db),
        store=_RedisWidgetStore(get_redis()),
        # Chat-session lookup powers the P0-2 visitor-binding check.
        sessions=MongoChatSessionRepository(db),
    )


def get_widget_config_service(
    db: Annotated[AsyncIOMotorDatabase[Any], Depends(get_db)],
    widget_service: Annotated[WidgetService, Depends(get_widget_service)],
) -> WidgetConfigService:
    """Build the dashboard widget-customization service (Phase 11.5).

    Cache invalidation is delegated to the public `WidgetService` so the live
    embed stops serving the stale 5-minute cached config the moment a tenant
    saves changes from the widget builder.
    """
    return WidgetConfigService(
        widgets=MongoWidgetRepository(db),
        audit=MongoAuditLogRepository(db),
        invalidate_public_config=widget_service.invalidate_public_config,
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


def get_sse_access_token(
    request: Request,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> str:
    """Extract access token for SSE endpoints (header or cookie fallback).

    ``EventSource`` cannot send custom headers, so SSE endpoints that require
    authentication need a cookie fallback.  The dashboard mirrors the access
    token into a non-httpOnly cookie (``sse_access_token``) on login / refresh;
    this dependency checks the ``Authorization`` header first (normal API
    requests) and falls back to the cookie (SSE connections).
    """

    def _from_header() -> str | None:
        if authorization and authorization.lower().startswith("bearer "):
            token = authorization.split(" ", 1)[1].strip()
            if token:
                return token
        return None

    def _from_cookie() -> str | None:
        cookie = request.cookies.get("sse_access_token")
        return cookie if cookie else None

    token = _from_header() or _from_cookie()
    if not token:
        raise InvalidCredentialsError("Missing or malformed Authorization header.")
    return token


async def current_user(
    access_token: Annotated[str, Depends(get_access_token)],
    auth: Annotated[AuthService, Depends(get_auth_service)],
) -> Principal:
    """Resolve the authenticated principal for a bearer-token request."""
    return await auth.authenticate(access_token)


async def sse_current_user(
    access_token: Annotated[str, Depends(get_sse_access_token)],
    auth: Annotated[AuthService, Depends(get_auth_service)],
) -> Principal:
    """Resolve the authenticated principal for SSE endpoints (header or cookie)."""
    return await auth.authenticate(access_token)


def require_sse_role(*roles: str) -> Callable[[Principal], None]:
    """Return an SSE-compatible role guard (header **or** cookie auth).

    Identical contract to ``require_role`` but resolves the principal through
    ``sse_current_user``, so the role check works for ``EventSource`` clients
    that authenticate via the ``sse_access_token`` cookie (which cannot send
    custom headers). Used only for routes that accept cookie-authenticated
    SSE connections.
    """

    def _require(principal: Annotated[Principal, Depends(sse_current_user)]) -> None:
        if not meets_any(principal.role, roles):
            raise ForbiddenError("Insufficient permissions for this action.")

    return _require


def require_role(*roles: str) -> Callable[[Principal], None]:
    """Return a FastAPI dependency guarding a route for one of `roles`.

    Usage: `Depends(require_role("admin"))` or `Depends(require_role("owner", "admin"))`.
    Role checks use the Phase 15 hierarchy (`backend/core/rbac.py`): a
    principal whose role ranks at or above a required role passes, so
    `super_admin` satisfies every tenant-level requirement while remaining the
    only role that satisfies `require_role("super_admin")`. Otherwise a 403
    `FORBIDDEN` error is raised (tenant isolation is enforced by
    `current_user`/`authenticate`, which always re-checks the live tenant).
    """

    def _require(principal: Annotated[Principal, Depends(current_user)]) -> None:
        if not meets_any(principal.role, roles):
            raise ForbiddenError("Insufficient permissions for this action.")

    return _require


def require_admin() -> Callable[[Principal], None]:
    """Guard the `/api/admin/*` surface for platform super admins (Phase 15).

    `super_admin` is granted only through `SUPER_ADMIN_EMAILS` configuration
    (`AuthService._resolve_role`), so an empty configuration disables the
    admin API entirely (every call raises 403 FORBIDDEN).
    """
    return require_role(*ADMIN_ROLES)


async def current_principal(
    request: Request,
    access_token: Annotated[str, Depends(get_access_token)],
    auth: Annotated[AuthService, Depends(get_auth_service)],
    api_keys: Annotated[ApiKeyService, Depends(get_api_key_service)],
) -> Principal | ApiKeyPrincipal:
    """Resolve a request identity: a user access JWT or a `wc_*` API key.

    API keys always authenticate as `owner` for their owning tenant (Sprint 2);
    the key is never a user session, so `user_id` is `None` and the principal
    is duck-typed for the read/mutation routes that accept it. User access
    tokens are resolved exactly like `current_user`.
    """
    if access_token.startswith(API_KEY_PREFIX):
        return await api_keys.authenticate_api_key(
            raw_secret=access_token,
            ip_address=client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    return await auth.authenticate(access_token)


def require_principal_role(*roles: str) -> Callable[[Principal | ApiKeyPrincipal], None]:
    """Return a dependency guarding a route for one of `roles`, API-key aware.

    Same contract as `require_role` (hierarchy-aware, Phase 15), but the
    principal may come from either a user access token or a `wc_*` API key
    (which authenticates as `owner`). Routes that must never accept API keys
    (user management, website CRUD, widget configuration, admin) keep
    `require_role`/`current_user`.
    """

    def _require(
        principal: Annotated[Principal | ApiKeyPrincipal, Depends(current_principal)],
    ) -> None:
        if not meets_any(principal.role, roles):
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


_SLIDING_WINDOW_LUA = """
-- Atomic sliding-window rate limiter (Redis Lua script).
-- KEYS[1] = rate-limit key (ZSET)
-- ARGV[1] = window_start_ms   (now_ms - window_seconds * 1000)
-- ARGV[2] = now_ms            (current wall-clock ms)
-- ARGV[3] = limit             (max events allowed)
-- ARGV[4] = window_seconds    (TTL for the key)
-- ARGV[5] = unique member     (now_ms:uuid)
--
-- Returns 1 if the request is allowed, 0 if rejected.
-- The entire prune -> count -> add -> expire runs in one atomic evaluation;
-- no concurrent caller can interleave between steps.

-- 1. Prune members that fell outside the sliding window.
redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, ARGV[1])

-- 2. Count the surviving members.
local count = redis.call('ZCARD', KEYS[1])

-- 3. Reject if already at or above the limit (no member added on reject).
if count >= tonumber(ARGV[3]) then
    return 0
end

-- 4. Add the new request's timestamped member.
redis.call('ZADD', KEYS[1], ARGV[2], ARGV[5])

-- 5. Keep the key alive so stale keys are eventually reclaimed.
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[4]))

return 1
"""


class _RedisRateLimitStore:
    """Adapter exposing Redis's minimal ZSET surface to the rate limiter.

    The adapter pins the loosely-typed `redis.asyncio` overloads to the exact
    `RateLimitStore` protocol surface (ADR-004).

    When ``eval_sliding_window`` is available the ``SlidingWindowRateLimiter``
    executes the entire prune -> count -> add -> expire sequence as one atomic
    Lua script, eliminating the race window that existed in the four-command
    fallback path.
    """

    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._sliding_window_script: Any = None

    async def zadd(self, name: str, mapping: Mapping[str, float]) -> int:
        return int(await self._redis.zadd(name, mapping))

    async def zremrangebyscore(self, name: str, min: int, max: float) -> int:
        return int(await self._redis.zremrangebyscore(name, min, max))

    async def zcard(self, name: str) -> int:
        return int(await self._redis.zcard(name))

    async def expire(self, name: str, time: int) -> bool:
        return bool(await self._redis.expire(name, time))

    async def eval_sliding_window(
        self, key: str, window_start_ms: float, now_ms: float, limit: int, window_seconds: int
    ) -> bool:
        """Execute the atomic sliding-window Lua script.

        Prunes expired members, checks the count, adds the new member, and
        refreshes the TTL -- all in one Redis EVAL call.  The script is
        registered lazily on first use so the adapter can be constructed in
        test environments where the underlying Redis client is a fake.
        """
        import uuid as _uuid

        if self._sliding_window_script is None:
            self._sliding_window_script = self._redis.register_script(_SLIDING_WINDOW_LUA)
        member = f"{now_ms}:{_uuid.uuid4()}"
        result = await self._sliding_window_script(
            keys=[key],
            args=[window_start_ms, now_ms, limit, window_seconds, member],
        )
        return bool(result)


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


class RefreshRateLimitDependency:
    """Per-session-token sliding-window limiter for the /refresh endpoint (SEC-7).

    Keyed by the SHA-256 prefix of the refresh token cookie, so:
    - Each rotated token gets a fresh window (normal browser refreshes are unaffected).
    - A stolen token pair is throttled to ``refresh_rate_limit_per_minute`` attempts.
    - Different users / sessions are fully isolated.

    Runs *before* the CSRF check so abuse is blocked at minimal cost.
    Fails closed on Redis outage (503), consistent with ``RateLimitDependency``.
    """

    def __init__(self) -> None:
        pass  # limit/window read from settings at call time

    async def __call__(self, request: Request) -> None:
        settings = get_settings()
        if not settings.rate_limit_enabled:
            return
        raw_token = request.cookies.get(settings.refresh_cookie_name, "")
        if not raw_token:
            return  # endpoint rejects with 401 anyway
        token_hash = hash_refresh_token(raw_token)
        limiter = SlidingWindowRateLimiter(
            _RedisRateLimitStore(get_redis()),
            limit=settings.refresh_rate_limit_per_minute,
            window_seconds=60,
        )
        try:
            allowed = await limiter.consume(f"rl:refresh:{token_hash[:16]}")
        except Exception as exc:
            raise ServiceUnavailableError("Rate limiter is temporarily unavailable.") from exc
        if not allowed:
            raise RateLimitExceededError("Too many refresh attempts. Please try again later.")


# Per-endpoint limits (Phase 2 auth abuse protection, ADR-004).
register_limiter = RateLimitDependency(limit=10, window_seconds=3600)
login_limiter = RateLimitDependency(limit=20, window_seconds=900)
verify_email_limiter = RateLimitDependency(limit=10, window_seconds=3600)
resend_verification_limiter = RateLimitDependency(limit=5, window_seconds=3600)
forgot_password_limiter = RateLimitDependency(limit=5, window_seconds=3600)
reset_password_limiter = RateLimitDependency(limit=5, window_seconds=3600)
# Phase 3 website-management abuse protection (create/update/delete/list/get).
website_limiter = RateLimitDependency(limit=120, window_seconds=3600)
# Phase 4 ingestion abuse protection (crawl kick-off + job status polling).
crawl_limiter = RateLimitDependency(limit=30, window_seconds=3600)
# Phase 11.2 conversation-management abuse protection (list/get/delete).
conversations_limiter = RateLimitDependency(limit=120, window_seconds=3600)
# Phase 11.3 analytics read abuse protection (summary/timeseries/top-websites/performance).
analytics_limiter = RateLimitDependency(limit=600, window_seconds=3600)
# API key management abuse protection (create/list/revoke, docs/05 §12).
api_keys_limiter = RateLimitDependency(limit=60, window_seconds=3600)
# Phase 11.5 widget builder abuse protection (customization read + PATCH).
widget_config_limiter = RateLimitDependency(limit=240, window_seconds=3600)
# Phase 12.5 admin panel abuse protection (ADR-006: "Stricter rate limits and
# a dedicated audit trail for admin actions"): bounded budget on admin reads
# and mutations alike.
admin_limiter = RateLimitDependency(limit=600, window_seconds=3600)
# Phase 13 billing reads abuse protection (usage + plans).
billing_limiter = RateLimitDependency(limit=240, window_seconds=3600)
# Phase 14 payment abuse protection (checkout + subscription report reads).
billing_checkout_limiter = RateLimitDependency(limit=30, window_seconds=3600)
# Phase 14 provider webhooks: authenticated by signature, but still per-IP
# budgeted so a hostile client cannot flood the activation path (they will be
# rejected on signature anyway; the budget bounds the DB work).
webhook_limiter = RateLimitDependency(limit=600, window_seconds=3600)
# Phase 6 chat abuse protection (ADR-004 per-widget message limit; dashboard
# chat uses the same budget until the widget API lands in Phase 8).
chat_limiter = RateLimitDependency(limit=60, window_seconds=60)
# SEC-7 per-session-token refresh abuse protection: keyed by the refresh
# token's SHA-256 prefix so each rotated token gets a fresh window while a
# stolen token pair is throttled (ADR-004).
refresh_limiter = RefreshRateLimitDependency()


async def enforce_api_key_rate_limit(
    request: Request,
    principal: Annotated[Principal | ApiKeyPrincipal, Depends(current_principal)],
) -> None:
    """Dedicated sliding-window budget for requests authenticated by `wc_*` keys.

    Programmatic keys get their own `rl:apikey:{key_id}` window
    (`api_key_rate_limit_per_minute`) so a bursty integration cannot exhaust a
    shared per-IP budget, and a shared egress IP cannot rotate budgets by key.
    No-op for user (access-token) requests, which keep the route's per-IP
    limiter. Fails closed on Redis outage (ADR-004), like `RateLimitDependency`.
    """
    if not isinstance(principal, ApiKeyPrincipal):
        return
    settings = get_settings()
    if not settings.rate_limit_enabled:
        return
    limiter = SlidingWindowRateLimiter(
        _RedisRateLimitStore(get_redis()),
        limit=settings.api_key_rate_limit_per_minute,
        window_seconds=60,
    )
    try:
        allowed = await limiter.consume(f"rl:apikey:{principal.key_id}")
    except Exception as exc:
        raise ServiceUnavailableError("Rate limiter is temporarily unavailable.") from exc
    if not allowed:
        raise RateLimitExceededError("Too many requests. Please try again later.")


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
            try:
                limit = int(getattr(settings, self.limit_setting))
            except (AttributeError, TypeError, ValueError) as exc:
                logger.error(
                    "widget_rate_limit misconfigured setting=%s error=%s",
                    self.limit_setting,
                    exc,
                )
                raise ServiceUnavailableError("Rate limiter is temporarily unavailable.") from exc
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
    """Visitor id from widget session claims, with IP-scoped fallback.

    When claims are missing or lack a ``visitor_id``, the fallback includes
    the client IP so that different visitors do not share a single rate-limit
    bucket (one abusive client cannot exhaust the budget for everyone).
    """
    claims = getattr(request.state, "widget_claims", None) or {}
    vid = claims.get("visitor_id")
    if vid:
        return str(vid)
    return f"anon:{client_ip(request)}"


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
# P0-4 dedicated per-IP burst budgets:
#  * session issue / IP: WIDGET_SESSION_ISSUE_IP_LIMIT / min (30)
#  * chat / IP: WIDGET_CHAT_IP_LIMIT / min (60)
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
# Phase 12.4 visitor-feedback abuse protection: a per-visitor sliding window
# for the write-once feedback endpoint (ADR-005 §5.6). Keyed on the widget
# session's anonymous visitor id, not the IP.
widget_feedback_limiter = WidgetRateLimitDependency(
    key_factory=_visitor_rate_limit_key,
    window_seconds=60,
    limit_setting="widget_feedback_limit",
)


# Per-IP backup budget per widget endpoint (production hardening). The
# entity-keyed limits above derive from a client-supplied visitor_id / body
# widget_id, so a hostile client can rotate them; an IP-shaped budget cannot
# be trivially rotated and also bounds the previously-unlimited `/config`.
def _widget_ip_rate_limit_key(request: Request) -> str:
    return f"rl:ip:{request.method}:{request.url.path}:{client_ip(request)}"


widget_ip_limiter = WidgetRateLimitDependency(
    key_factory=_widget_ip_rate_limit_key,
    window_seconds=60,
    limit_setting="widget_ip_limit",
)


# Dedicated per-IP burst budgets (P0-4): anonymous token minting and SSE
# generation are the two most expensive public surfaces, and both of their
# entity keys (`visitor_id`, target `widget_id`) are attacker-chosen. These
# tighter IP-shaped windows survive that rotation instead of blending into
# the generic per-endpoint `widget_ip_limiter` bucket above.
def _widget_chat_ip_rate_limit_key(request: Request) -> str:
    return f"rl:ip:chat:{client_ip(request)}"


def _widget_session_ip_rate_limit_key(request: Request) -> str:
    return f"rl:ip:sessions:{client_ip(request)}"


widget_chat_ip_limiter = WidgetRateLimitDependency(
    key_factory=_widget_chat_ip_rate_limit_key,
    window_seconds=60,
    limit_setting="widget_chat_ip_limit",
)
widget_session_ip_limiter = WidgetRateLimitDependency(
    key_factory=_widget_session_ip_rate_limit_key,
    window_seconds=60,
    limit_setting="widget_session_issue_ip_limit",
)


async def _widget_origin_guard(
    request: Request,
    widget_id: str,
    service: Annotated[WidgetService, Depends(get_widget_service)],
    *,
    require_origin: bool = False,
) -> None:
    """Reject browser embeds from origins outside the widget allowlist.

    The `User-Agent` rides along so the service can distinguish a browser
    that dropped its `Origin` header (rejected - P0-1) from a genuine
    non-browser client such as curl or a server-to-server caller.
    """
    await service.validate_origin(
        widget_id,
        request.headers.get("origin"),
        user_agent=request.headers.get("user-agent"),
        require_origin=require_origin,
    )


async def widget_config_origin_guard(
    request: Request,
    widget_id: Annotated[str, Path()],
    service: Annotated[WidgetService, Depends(get_widget_service)],
) -> None:
    """Origin guard for `GET /api/widget/v1/config/{widget_id}`."""
    await _widget_origin_guard(request, widget_id, service)


async def widget_session_origin_guard(
    request: Request,
    body: CreateWidgetSessionRequest,
    service: Annotated[WidgetService, Depends(get_widget_service)],
) -> None:
    """Origin guard for `POST /api/widget/v1/sessions` (widget_id in body).

    Session minting unconditionally requires an `Origin` header (P0-1): a
    browser cross-origin POST always carries one, so headerless requests
    cannot mint widget-session tokens at all.
    """
    await _widget_origin_guard(request, body.widget_id, service, require_origin=True)


async def widget_claims_origin_guard(
    request: Request,
    service: Annotated[WidgetService, Depends(get_widget_service)],
) -> None:
    """Origin guard for token-authenticated widget routes (widget_id in claims).

    Must be declared after `widget_session_claims` so `request.state.widget_claims`
    is populated; the session token is bound to a widget, so the origin must
    match that widget's allowlist on every chat/feedback request.
    """
    claims = getattr(request.state, "widget_claims", None) or {}
    await _widget_origin_guard(request, str(claims.get("widget_id") or "unknown"), service)


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
