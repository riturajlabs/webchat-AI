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
from backend.core.metrics import record_mongodb_command_duration
from backend.models.crawl_job import CRAWL_ACTIVE_STATUSES
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
_VECTOR_INDEX_NAME = "default"
# Messages TTL (on created_at) and usage_records TTL (on updated_at) are
# derived from config at index-creation time so CHAT_RETENTION_DAYS /
# USAGE_RETENTION_DAYS stay the single source of truth (defaults 90 days /
# 3 years, ADR-005 §5.7).


def _messages_ttl_seconds() -> int:
    return get_settings().chat_retention_days * 24 * 60 * 60


def _usage_ttl_seconds() -> int:
    return get_settings().usage_retention_days * 24 * 60 * 60


# Phase 16 subscriptions payment_id index name (used for migration detection).
_SUBSCRIPTION_PAYMENT_ID_INDEX = "payment_id_1"
_SUBSCRIPTION_PAYMENT_ID_PARTIAL_FILTER = {"payment_id": {"$type": "string"}}


async def _ensure_subscription_payment_id_index(db: AsyncIOMotorDatabase[Any]) -> None:
    """Create/migrate the subscriptions payment_id index.

    Paid subscriptions use payment_id as a gateway idempotency key and
    require uniqueness across the collection. Admin grants intentionally
    leave payment_id empty (None) because they carry no gateway id.

    The original non-partial unique index treated null as a single value,
    so inserting two admin grants anywhere in the collection always
    collided (E11000 on payment_id). A partial unique index restricted
    to string payment_ids preserves webhook idempotency for paid subs
    while allowing any number of grants.
    """
    collection = db["subscriptions"]
    info = await collection.index_information()
    current = info.get(_SUBSCRIPTION_PAYMENT_ID_INDEX)
    already_desired = (
        current is not None
        and current.get("unique") is True
        and current.get("partialFilterExpression") == _SUBSCRIPTION_PAYMENT_ID_PARTIAL_FILTER
    )
    if already_desired:
        return

    # Verify existing string payment_ids are unique before rebuilding the
    # index so a drop+create never masks data corruption.
    dupes = await collection.aggregate(
        [
            {"$match": {"payment_id": {"$type": "string"}}},
            {"$group": {"_id": "$payment_id", "count": {"$sum": 1}}},
            {"$match": {"count": {"$gt": 1}}},
            {"$limit": 1},
        ]
    ).to_list(1)
    if dupes:
        raise RuntimeError(
            "Duplicate payment_id values detected in subscriptions; "
            "fix data before migrating the payment_id index."
        )

    # Drop the legacy non-partial (or mismatched partial) unique index and
    # create the correct partial unique index. OperationFailure on drop is
    # expected on a fresh database where the index never existed.
    try:
        await collection.drop_index(_SUBSCRIPTION_PAYMENT_ID_INDEX)
    except OperationFailure:
        pass
    await collection.create_index(
        "payment_id",
        unique=True,
        partialFilterExpression=_SUBSCRIPTION_PAYMENT_ID_PARTIAL_FILTER,
    )


# FIND-02 single-flight gate on crawl_jobs. The default MongoDB compound name
# for [("tenant_id", 1), ("website_id", 1), ("active", 1)].
_CRAWL_JOB_ACTIVE_INDEX = "tenant_id_1_website_id_1_active_1"


async def _ensure_crawl_job_active_index(db: AsyncIOMotorDatabase[Any]) -> None:
    """Create the partial unique index that makes crawl-job inserts atomic.

    `(tenant_id, website_id, active)` is unique *among active jobs only*, so
    two racing `start_crawl` calls for the same website cannot both insert an
    active row. Legacy documents were backfilled with `active` before this
    helper runs. If pre-existing duplicate active rows would violate the
    unique constraint, we refuse loudly instead of silently deleting data
    (mirrors `_ensure_subscription_payment_id_index`).
    """
    collection = db["crawl_jobs"]
    info = await collection.index_information()
    current = info.get(_CRAWL_JOB_ACTIVE_INDEX)
    already_desired = (
        current is not None
        and current.get("unique") is True
        and current.get("partialFilterExpression") == {"active": True}
        and current.get("key") == {"tenant_id": 1, "website_id": 1, "active": 1}
    )
    if already_desired:
        return

    dupes = await collection.aggregate(
        [
            {"$match": {"active": True}},
            {
                "$group": {
                    "_id": {"tenant_id": "$tenant_id", "website_id": "$website_id"},
                    "count": {"$sum": 1},
                }
            },
            {"$match": {"count": {"$gt": 1}}},
            {"$limit": 1},
        ]
    ).to_list(1)
    if dupes:
        raise RuntimeError(
            "Duplicate active crawl_jobs rows detected (same tenant_id + website_id); "
            "resolve the conflicting rows before creating the FIND-02 single-flight index."
        )

    await collection.create_index(
        [("tenant_id", 1), ("website_id", 1), ("active", 1)],
        unique=True,
        partialFilterExpression={"active": True},
    )


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


class MongoMetricsListener(CommandListener):
    """Record MongoDB command durations into the metrics registry (OBS-05).

    Always attached to the Motor client (unlike the opt-in slow-query logger),
    so DB latency is observable even when slow-query logging is disabled.
    Pure observation: the registry update is a thread-safe dict lookup + float
    add and can never break the command path. Heartbeat/control commands are
    skipped so series stay meaningful.
    """

    def __init__(self) -> None:
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
        self._record(started, event.duration_micros)

    def failed(self, event: CommandFailedEvent) -> None:
        if event.operation_id is None:
            return
        with self._lock:
            started = self._starts.pop(event.operation_id, None)
        self._record(started, event.duration_micros)

    def _record(self, started: CommandStartedEvent | None, duration_micros: int) -> None:
        if started is None or started.command_name in _NOISE_COMMANDS:
            return
        record_mongodb_command_duration(
            command=started.command_name,
            duration_seconds=duration_micros / 1_000_000.0,
        )


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
            listeners: list[CommandListener] = [MongoMetricsListener()]
            if settings.mongodb_slow_query_threshold_ms > 0:
                listeners.append(SlowQueryListener(settings.mongodb_slow_query_threshold_ms))
            cls._client = AsyncIOMotorClient[Any](
                settings.mongodb_uri,
                minPoolSize=settings.mongodb_min_pool_size,
                maxPoolSize=settings.mongodb_max_pool_size,
                serverSelectionTimeoutMS=settings.mongodb_server_selection_timeout_ms,
                socketTimeoutMS=settings.mongodb_socket_timeout_ms,
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
        Partial unique: subscriptions.payment_id (string-only, for webhook
        idempotency; admin grants leave payment_id empty, §16).
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
        # FIND-02: the *atomic single-flight gate* for active crawl jobs.
        # `(tenant_id, website_id, active)` is unique among active jobs only, so
        # two racing `start_crawl` calls for the same website cannot both insert
        # an active `crawl_jobs` row - the loser hits `DuplicateKeyError` and
        # the repository translates it to `CrawlConflictError` (409).
        #
        # Migration (idempotent):
        #  1. Backfill the `active` flag from the legacy `status` marker so
        #     pre-flag documents participate in the partial index.
        #  2. Refuse (do NOT delete) pre-existing duplicate active rows so the
        #     failure is loud and an operator fixes the data (mirrors
        #     `_ensure_subscription_payment_id_index`).
        #  3. Create the partial unique index.
        await db["crawl_jobs"].update_many(
            {"status": {"$in": sorted(CRAWL_ACTIVE_STATUSES)}}, {"$set": {"active": True}}
        )
        await db["crawl_jobs"].update_many(
            {"status": {"$nin": sorted(CRAWL_ACTIVE_STATUSES)}}, {"$set": {"active": False}}
        )
        await _ensure_crawl_job_active_index(db)
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
        # PERF-K05: conversation listing filters on (tenant, website) then sorts
        # by `last_activity`. The compound index covers the sort so MongoDB
        # can stream the result instead of doing an in-memory filesort.
        await db["chat_sessions"].create_index(
            [("tenant_id", 1), ("website_id", 1), ("last_activity", -1)]
        )
        await db["chat_sessions"].create_index(
            "expires_at", expireAfterSeconds=_CHAT_SESSION_TTL_SECONDS
        )
        await db["messages"].create_index("tenant_id")
        await db["messages"].create_index("session_id")
        await db["messages"].create_index([("tenant_id", 1), ("session_id", 1), ("created_at", 1)])
        # Audit A-01: dashboard analytics aggregate on (tenant_id, role,
        # created_at); without this compound the $match filters role/date in
        # memory over the single-field tenant index.
        await db["messages"].create_index([("tenant_id", 1), ("role", 1), ("created_at", 1)])
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
        # payment_id unique *among real gateway ids* only: admin grants leave it
        # empty (§16), so the index is partial on string values. The helper
        # migrates the legacy non-partial index where one exists.
        await _ensure_subscription_payment_id_index(db)
        # API key management (docs/05 §12).
        await db["api_keys"].create_index("hashed_secret", unique=True)
        await db["api_keys"].create_index("tenant_id")
        await db["api_keys"].create_index([("tenant_id", 1), ("created_at", -1)])
        # Phase 12.4 visitor feedback (docs/05 §19, ADR-005 §5.6): tenant reads,
        # created_at sorting, rating/category filters, 2-year TTL. The
        # (tenant, website, created_at) index serves the dashboard's feedback
        # analytics breakdowns filtered per website (retail analytics view).
        await db["feedback"].create_index("tenant_id")
        await db["feedback"].create_index([("tenant_id", 1), ("created_at", -1)])
        await db["feedback"].create_index([("tenant_id", 1), ("website_id", 1), ("created_at", -1)])
        await db["feedback"].create_index("rating")
        await db["feedback"].create_index(
            [("tenant_id", 1), ("message_id", 1)], unique=True, name="uniq_tenant_message"
        )
        await db["feedback"].create_index("created_at", expireAfterSeconds=_FEEDBACK_TTL_SECONDS)
        await cls._validate_vector_search_index(db)

    @classmethod
    async def _validate_vector_search_index(cls, db: AsyncIOMotorDatabase[Any]) -> bool:
        """Warn when the Atlas vector index is absent or incompatible.

        Atlas Search indexes are managed separately from MongoDB B-tree
        indexes, so ``init_indexes`` cannot create the vector index. This probe
        keeps startup non-fatal for local MongoDB while making a production
        misconfiguration visible before traffic reaches the brute-force
        fallback.
        """
        expected_dimensions = get_settings().embedding_dimensions
        expected_filters = {
            "tenant_id",
            "website_id",
            "embedding_provider",
            "embedding_model",
            "embedding_dimensions",
            "embedding_version",
        }
        try:
            cursor = db["knowledge_chunks"].aggregate(
                [{"$listSearchIndexes": {"name": _VECTOR_INDEX_NAME}}]
            )
            async for index in cursor:
                if not isinstance(index, dict):
                    continue
                definition = index.get("latestDefinition") or index.get("definition") or {}
                fields = definition.get("fields", []) if isinstance(definition, dict) else []
                vector_fields = [
                    field
                    for field in fields
                    if isinstance(field, dict)
                    and field.get("type") == "vector"
                    and field.get("path") == "embedding"
                ]
                filter_paths = {
                    field.get("path")
                    for field in fields
                    if isinstance(field, dict) and field.get("type") == "filter"
                }
                vector = vector_fields[0] if vector_fields else None
                valid = (
                    index.get("status") in (None, "READY")
                    and index.get("queryable") is not False
                    and vector is not None
                    and vector.get("numDimensions") == expected_dimensions
                    and vector.get("similarity") == "cosine"
                    and expected_filters <= filter_paths
                )
                if valid:
                    logger.info(
                        "mongodb_vector_index_ready name=%s dimensions=%s",
                        _VECTOR_INDEX_NAME,
                        expected_dimensions,
                    )
                    return True
                logger.warning(
                    "mongodb_vector_index_misconfigured name=%s expected_path=embedding "
                    "expected_dimensions=%s expected_similarity=cosine missing_filters=%s",
                    _VECTOR_INDEX_NAME,
                    expected_dimensions,
                    sorted(expected_filters - filter_paths),
                )
                return False
            logger.warning(
                "mongodb_vector_index_missing name=%s expected_path=embedding "
                "expected_dimensions=%s; provision it in Atlas Search administration",
                _VECTOR_INDEX_NAME,
                expected_dimensions,
            )
        except Exception as exc:  # local MongoDB does not support $listSearchIndexes
            logger.warning(
                "mongodb_vector_index_probe_unavailable name=%s error_type=%s; "
                "Atlas vector search must be provisioned for production",
                _VECTOR_INDEX_NAME,
                type(exc).__name__,
            )
        return False

    @classmethod
    async def close(cls) -> None:
        if cls._client is not None:
            # Motor's AsyncIOMotorClient.close() is a synchronous teardown in the
            # pinned version (returns None), so it is invoked directly rather
            # than awaited.
            cls._client.close()
            cls._client = None
