"""MongoDB connection management via the async Motor driver."""

from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from backend.core.config import get_settings

# ADR-005 §5.4: drop refresh-token documents 10 days after their expiry (40d).
_REFRESH_TOKEN_TTL_SECONDS = 40 * 24 * 60 * 60
# ADR-005 §5.7: audit log retention is 1 year.
_AUDIT_LOG_TTL_SECONDS = 365 * 24 * 60 * 60
# ADR-005 §5.7: crawl job records are retained 30 days.
_CRAWL_JOB_TTL_SECONDS = 30 * 24 * 60 * 60


class MongoDB:
    """Lazy singleton around the async Mongo client.

    The client connects on first use, so importing this module has no side
    effects (safe for tests). Close it explicitly on application shutdown.
    """

    _client: AsyncIOMotorClient[Any] | None = None

    @classmethod
    def client(cls) -> AsyncIOMotorClient[Any]:
        if cls._client is None:
            settings = get_settings()
            cls._client = AsyncIOMotorClient[Any](
                settings.mongodb_uri,
                minPoolSize=settings.mongodb_min_pool_size,
                maxPoolSize=settings.mongodb_max_pool_size,
                serverSelectionTimeoutMS=settings.mongodb_server_selection_timeout_ms,
                # Return BSON datetimes as aware UTC so they compare cleanly
                # against `core.security.utcnow()` (Mongo defaults to naive).
                tz_aware=True,
            )
        return cls._client

    @classmethod
    def db(cls) -> AsyncIOMotorDatabase[Any]:
        return cls.client()[get_settings().mongodb_db]

    @classmethod
    async def ping(cls) -> bool:
        """Return True if MongoDB is reachable, False otherwise."""
        try:
            await cls.client().admin.command("ping")
            return True
        except Exception:
            return False

    @classmethod
    async def init_indexes(cls) -> None:
        """Create required indexes (idempotent) per docs/05 + ADR-005.

        Unique: users.email, refresh_tokens.token_hash, members(tenant,user),
        websites(tenant,url), widgets.widget_id, widgets(tenant,website).
        TTL: refresh_tokens.expires_at (40 days, ADR-005 §5.4),
        audit_logs.created_at (1 year, ADR-005 §5.7),
        crawl_jobs.created_at (30 days, ADR-005 §5.7).
        """
        db = cls.db()
        await db["users"].create_index("email", unique=True)
        await db["users"].create_index("tenant_id")
        await db["users"].create_index("status")
        await db["refresh_tokens"].create_index("token_hash", unique=True)
        await db["refresh_tokens"].create_index("tenant_id")
        await db["refresh_tokens"].create_index("user_id")
        await db["refresh_tokens"].create_index(
            "expires_at", expireAfterSeconds=_REFRESH_TOKEN_TTL_SECONDS
        )
        await db["members"].create_index(
            [("tenant_id", 1), ("user_id", 1)], unique=True
        )
        await db["audit_logs"].create_index(
            [("tenant_id", 1), ("created_at", -1)]
        )
        await db["audit_logs"].create_index(
            "created_at", expireAfterSeconds=_AUDIT_LOG_TTL_SECONDS
        )
        # Phase 3 website management (docs/05 §5-6, ADR-005 §5.3).
        # (tenant_id, url) is unique: the race-free duplicate gatekeeper.
        await db["websites"].create_index([("tenant_id", 1), ("url", 1)], unique=True)
        await db["websites"].create_index("tenant_id")
        await db["websites"].create_index("url")
        await db["widgets"].create_index("widget_id", unique=True)
        await db["widgets"].create_index("tenant_id")
        await db["widgets"].create_index([("tenant_id", 1), ("website_id", 1)], unique=True)
        # Phase 4 ingestion engine (docs/05 §8, documents; ADR-002).
        # (tenant_id, website_id, url) is unique: a re-crawl replaces a page.
        await db["crawl_jobs"].create_index("tenant_id")
        await db["crawl_jobs"].create_index("website_id")
        await db["crawl_jobs"].create_index([("tenant_id", 1), ("status", 1)])
        await db["crawl_jobs"].create_index(
            "created_at", expireAfterSeconds=_CRAWL_JOB_TTL_SECONDS
        )
        await db["documents"].create_index(
            [("tenant_id", 1), ("website_id", 1), ("url", 1)], unique=True
        )
        await db["documents"].create_index("tenant_id")
        await db["documents"].create_index("website_id")
        await db["documents"].create_index("url")

    @classmethod
    async def close(cls) -> None:
        if cls._client is not None:
            cls._client.close()
            cls._client = None
