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
# ADR-005 §5.7: chat sessions are deleted exactly at `expires_at` (the Mongo
# "deadline" pattern, expireAfterSeconds=0). `expires_at` is already set to
# now + CHAT_RETENTION_DAYS by ChatSession.new, so this yields the configured
# 90-day retention without double-counting.
_CHAT_SESSION_TTL_SECONDS = 0
# Messages TTL (on created_at) and usage_records TTL (on updated_at) are
# derived from config at index-creation time so CHAT_RETENTION_DAYS /
# USAGE_RETENTION_DAYS stay the single source of truth (defaults 90 days /
# 3 years, ADR-005 §5.7).


def _messages_ttl_seconds() -> int:
    return get_settings().chat_retention_days * 24 * 60 * 60


def _usage_ttl_seconds() -> int:
    return get_settings().usage_retention_days * 24 * 60 * 60


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
        websites(tenant,url), widgets.widget_id, widgets(tenant,website),
        chat_sessions.session_id, usage_records(tenant,website,date).
        TTL: refresh_tokens.expires_at (40 days, ADR-005 §5.4),
        audit_logs.created_at (1 year, ADR-005 §5.7),
        crawl_jobs.created_at (30 days, ADR-005 §5.7),
        chat_sessions.expires_at (deadline, expireAfterSeconds=0; §5.7),
        messages.created_at (90 days, configurable, §5.7),
        usage_records.updated_at (3 years, configurable, §5.7).
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
        # Phase 5 knowledge processing (docs/05 §7, ADR-008).
        # The unique (tenant, website, document, chunk_index) key makes chunk
        # inserts idempotent (duplicate prevention).
        await db["knowledge_chunks"].create_index(
            [
                ("tenant_id", 1),
                ("website_id", 1),
                ("document_id", 1),
                ("chunk_index", 1),
            ],
            unique=True,
        )
        await db["knowledge_chunks"].create_index("tenant_id")
        await db["knowledge_chunks"].create_index("website_id")
        await db["knowledge_chunks"].create_index("document_id")
        await db["knowledge_chunks"].create_index(
            [("tenant_id", 1), ("website_id", 1)]
        )
        # Phase 6 RAG pipeline (docs/05 §9-10, ADR-005 §5.5-5.8).
        # `session_id` is unique: the conversation key used by messages and the
        # future widget API. TTLs: sessions on `expires_at`, messages on
        # `created_at` (90 days), usage_records on `updated_at` (3 years).
        await db["chat_sessions"].create_index("session_id", unique=True)
        await db["chat_sessions"].create_index("tenant_id")
        await db["chat_sessions"].create_index([("tenant_id", 1), ("website_id", 1)])
        await db["chat_sessions"].create_index(
            "expires_at", expireAfterSeconds=_CHAT_SESSION_TTL_SECONDS
        )
        await db["messages"].create_index("tenant_id")
        await db["messages"].create_index("session_id")
        await db["messages"].create_index(
            [("tenant_id", 1), ("session_id", 1), ("created_at", 1)]
        )
        await db["messages"].create_index(
            "created_at", expireAfterSeconds=_messages_ttl_seconds()
        )
        await db["usage_records"].create_index(
            [("tenant_id", 1), ("website_id", 1), ("date", 1)], unique=True
        )
        await db["usage_records"].create_index("tenant_id")
        await db["usage_records"].create_index("date")
        await db["usage_records"].create_index(
            "updated_at", expireAfterSeconds=_usage_ttl_seconds()
        )

    @classmethod
    async def close(cls) -> None:
        if cls._client is not None:
            cls._client.close()
            cls._client = None
