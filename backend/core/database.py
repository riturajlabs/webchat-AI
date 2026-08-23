"""MongoDB connection management via the async Motor driver."""

import logging
import threading
from collections.abc import Mapping
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import OperationFailure
from pymongo.monitoring import (
    CommandFailedEvent,
    CommandListener,
    CommandStartedEvent,
    CommandSucceededEvent,
)

from backend.core.config import get_settings
from backend.models.website import WEBSITE_STATUS_DELETED

logger = logging.getLogger("webchat_ai")

# ADR-005 §5.4: drop refresh-token documents 10 days after their expiry (40d).
_REFRESH_TOKEN_TTL_SECONDS = 40 * 24 * 60 * 60
# ADR-005 §5.7: audit log retention is 1 year.
_AUDIT_LOG_TTL_SECONDS = 365 * 24 * 60 * 60
# ADR-005 §5.7: crawl job records are retained 30 days.
_CRAWL_JOB_TTL_SECONDS = 30 * 24 * 60 * 60
# ADR-005 §5.7: visitor feedback is retained 2 years.
_FEEDBACK_TTL_SECONDS = 2 * 365 * 24 * 60 * 60
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


# Heartbeat/control commands that would only ever log as noise.
_NOISE_COMMANDS = {"ping", "hello", "ismaster", "saslStart", "saslContinue"}


def _command_namespace(event: CommandStartedEvent) -> str:
    """Best-effort `db.collection` namespace for a command event."""
    collection = (
        event.command.get("find")
        or event.command.get("aggregate")
        or event.command.get("count")
        or event.command.get("insert")
        or event.command.get("update")
        or event.command.get("delete")
    )
    if isinstance(collection, str):
        return f"{event.database_name}.{collection}"
    return event.database_name


class SlowQueryListener(CommandListener):
    """Log MongoDB commands exceeding a threshold (Phase 12.1 instrumentation).

    Opt-in via `MONGODB_SLOW_QUERY_THRESHOLD_MS` (> 0). Logs the command name,
    namespace and duration plus, when the reply carries them,
    `docsExamined`/`nReturned` (numeric, non-sensitive). Query filters are
    never logged (00 rules §12/§20).
    """

    def __init__(self, threshold_ms: int) -> None:
        self._threshold_ms = max(1, threshold_ms)
        self._lock = threading.Lock()
        self._starts: dict[int, CommandStartedEvent] = {}

    def started(self, event: CommandStartedEvent) -> None:
        if event.operation_id is None:
            return
        with self._lock:
            self._starts[event.operation_id] = event

    def succeeded(self, event: CommandSucceededEvent) -> None:
        if event.operation_id is None:
            return
        with self._lock:
            started = self._starts.pop(event.operation_id, None)
        self._maybe_log(started, event.duration_micros, event.reply)

    def failed(self, event: CommandFailedEvent) -> None:
        if event.operation_id is None:
            return
        with self._lock:
            started = self._starts.pop(event.operation_id, None)
        self._maybe_log(started, event.duration_micros, None, failure=str(event.failure))

    def _maybe_log(
        self,
        started: CommandStartedEvent | None,
        duration_micros: int,
        reply: Mapping[str, Any] | None,
        *,
        failure: str | None = None,
    ) -> None:
        if started is None or started.command_name in _NOISE_COMMANDS:
            return
        duration_ms = duration_micros / 1000.0
        if duration_ms < self._threshold_ms:
            return
        extra: dict[str, Any] = {
            "command": started.command_name,
            "namespace": _command_namespace(started),
            "duration_ms": round(duration_ms, 2),
        }
        if reply is not None:
            docs_examined = reply.get("docsExamined")
            returned = reply.get("nReturned")
            if isinstance(docs_examined, int):
                extra["docs_examined"] = docs_examined
            if isinstance(returned, int):
                extra["n_returned"] = returned
        if failure is not None:
            extra["ok"] = False
            extra["error"] = failure
        logger.info("mongodb_slow_query", extra=extra)


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
            listeners: list[CommandListener] = []
            if settings.mongodb_slow_query_threshold_ms > 0:
                listeners.append(SlowQueryListener(settings.mongodb_slow_query_threshold_ms))
            cls._client = AsyncIOMotorClient[Any](
                settings.mongodb_uri,
                minPoolSize=settings.mongodb_min_pool_size,
                maxPoolSize=settings.mongodb_max_pool_size,
                serverSelectionTimeoutMS=settings.mongodb_server_selection_timeout_ms,
                event_listeners=listeners,
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
        chat_sessions.session_id, usage_records(tenant,website,date),
        api_keys.hashed_secret.
        TTL: refresh_tokens.expires_at (40 days, ADR-005 §5.4),
        audit_logs.created_at (1 year, ADR-005 §5.7),
        crawl_jobs.created_at (30 days, ADR-005 §5.7),
        chat_sessions.expires_at (deadline, expireAfterSeconds=0; §5.7),
        messages.created_at (90 days, configurable, §5.7),
        usage_records.updated_at (3 years, configurable, §5.7),
        feedback.created_at (2 years, ADR-005 §5.7).
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
        await db["members"].create_index([("tenant_id", 1), ("user_id", 1)], unique=True)
        await db["audit_logs"].create_index([("tenant_id", 1), ("created_at", -1)])
        await db["audit_logs"].create_index("created_at", expireAfterSeconds=_AUDIT_LOG_TTL_SECONDS)
        # Phase 15 platform admin trail (backend/models/admin_audit_log.py).
        # No TTL: retained for the 10-year platform compliance window (the
        # collection is append-only and small relative to tenant audit_logs).
        await db["admin_audit_logs"].create_index([("tenant_id", 1), ("created_at", -1)])
        await db["admin_audit_logs"].create_index([("action", 1), ("created_at", -1)])
        await db["admin_audit_logs"].create_index([("actor_user_id", 1), ("created_at", -1)])
        # Phase 3 website management (docs/05 §5-6, ADR-005 §5.3).
        # (tenant_id, url) is unique *among active websites*: the race-free
        # duplicate gatekeeper. Soft-deleted websites must not block URL
        # re-registration, so the uniqueness is enforced by a *partial* index
        # filtered to `deleted: false` (MongoDB partial filters only support
        # equality, hence the boolean flag on the model; `$ne` is not allowed).
        #
        # Migration (idempotent):
        #  1. Backfill the `deleted` flag from the legacy `status` marker so
        #     pre-flag documents participate in the partial index.
        #  2. Drop the legacy full-unique index that reserved deleted URLs.
        #  3. Create the partial unique index.
        await db["websites"].update_many(
            {"status": {"$ne": WEBSITE_STATUS_DELETED}}, {"$set": {"deleted": False}}
        )
        await db["websites"].update_many(
            {"status": WEBSITE_STATUS_DELETED}, {"$set": {"deleted": True}}
        )
        try:
            await db["websites"].drop_index("tenant_id_1_url_1")
        except OperationFailure:
            pass  # Fresh database: the legacy full-unique index never existed.
        await db["websites"].create_index(
            [("tenant_id", 1), ("url", 1)],
            unique=True,
            partialFilterExpression={"deleted": False},
        )
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
        await db["crawl_jobs"].create_index("created_at", expireAfterSeconds=_CRAWL_JOB_TTL_SECONDS)
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
        await db["knowledge_chunks"].create_index([("tenant_id", 1), ("website_id", 1)])
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
        await db["messages"].create_index([("tenant_id", 1), ("session_id", 1), ("created_at", 1)])
        await db["messages"].create_index("created_at", expireAfterSeconds=_messages_ttl_seconds())
        await db["usage_records"].create_index(
            [("tenant_id", 1), ("website_id", 1), ("date", 1)], unique=True
        )
        await db["usage_records"].create_index("tenant_id")
        await db["usage_records"].create_index("date")
        await db["usage_records"].create_index(
            "updated_at", expireAfterSeconds=_usage_ttl_seconds()
        )
        # Phase 13 SaaS billing (docs/05 §20, ADR-005 §5.9): `usage_events` is
        # the append-only counter log powering `/api/billing/usage` and plan
        # limit checks. `(tenant_id, created_at)` serves the monthly window
        # aggregation; TTL mirrors usage_records retention.
        await db["usage_events"].create_index([("tenant_id", 1), ("created_at", 1)])
        await db["usage_events"].create_index("created_at", expireAfterSeconds=_usage_ttl_seconds())
        # Phase 14 SaaS subscriptions: the tenant list (payment history + plan
        # resolution) and the webhook idempotency lookup keyed by provider id.
        await db["subscriptions"].create_index([("tenant_id", 1), ("created_at", -1)])
        await db["subscriptions"].create_index([("tenant_id", 1), ("status", 1), ("end_date", 1)])
        await db["subscriptions"].create_index("payment_id", unique=True)
        # API key management (docs/05 §12).
        await db["api_keys"].create_index("hashed_secret", unique=True)
        await db["api_keys"].create_index("tenant_id")
        await db["api_keys"].create_index([("tenant_id", 1), ("created_at", -1)])
        # Phase 12.4 visitor feedback (docs/05 §19, ADR-005 §5.6): tenant reads,
        # created_at sorting, rating/category filters, 2-year TTL.
        await db["feedback"].create_index("tenant_id")
        await db["feedback"].create_index([("tenant_id", 1), ("created_at", -1)])
        await db["feedback"].create_index("rating")
        await db["feedback"].create_index(
            [("tenant_id", 1), ("message_id", 1)], unique=True, name="uniq_tenant_message"
        )
        await db["feedback"].create_index("created_at", expireAfterSeconds=_FEEDBACK_TTL_SECONDS)

    @classmethod
    async def close(cls) -> None:
        if cls._client is not None:
            cls._client.close()
            cls._client = None
