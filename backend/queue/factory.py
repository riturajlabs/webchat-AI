"""Queue backend selection (Phase 17A).

``get_queue`` builds the adapter selected by ``QUEUE_BACKEND`` (default
``arq``). The Mongo path is reachable only when ``MONGO_QUEUE_ENABLED=true``
(both are enforced again at ``Settings`` construction, so a half-configured
deployment fails at boot rather than at the first enqueue), and it reuses the
existing ``MongoDB`` client - never a second unmanaged connection - while
targeting an explicit queue database, never the application database.
"""

from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.core.config import Settings, get_settings
from backend.queue.arq_adapter import ArqQueueAdapter
from backend.queue.errors import MongoQueueNotEnabledError
from backend.queue.protocol import WorkerQueue

#: Development fallback database when MONGO_QUEUE_DATABASE is unset. Never the
#: application database; production requires an explicit name (Settings
#: validation rejects the combination).
DEFAULT_QUEUE_DATABASE = "webchat_ai_queue"


def queue_database_name(settings: Settings | None = None) -> str:
    """Resolve the queue database name, refusing the application database."""
    settings = settings if settings is not None else get_settings()
    name = settings.mongo_queue_database.strip() or DEFAULT_QUEUE_DATABASE
    app_database = settings.mongodb_db.strip()
    if app_database and name == app_database:
        # Defensive: a queue collection must never sit beside tenant data.
        raise MongoQueueNotEnabledError(
            "MONGO_QUEUE_DATABASE must differ from the application database "
            f"({app_database!r}); queue rows are kept in their own database."
        )
    return name


def build_mongo_config_kwargs(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings if settings is not None else get_settings()
    return {
        "collection_name": settings.mongo_queue_collection,
        "lease_seconds": settings.mongo_queue_lease_seconds,
        "heartbeat_seconds": settings.mongo_queue_heartbeat_seconds,
        "max_tries": settings.mongo_queue_max_tries,
        "backoff_seconds": tuple(settings.mongo_queue_backoff_seconds),
        "poll_schedule": tuple(settings.mongo_queue_poll_schedule),
        "max_result_bytes": settings.mongo_queue_max_result_bytes,
        "retention_days": settings.mongo_queue_retention_days,
        "result_policy": settings.mongo_queue_result_policy,
    }


def get_queue(db: AsyncIOMotorDatabase[Any] | None = None) -> WorkerQueue:
    """Build the configured queue adapter.

    ``db`` is honoured only by the Mongo backend and only for tests / embedded
    callers that must point at an isolated database; the default path builds the
    queue database from the shared ``MongoDB`` client.

    ``queue_backend`` is normalized to lower case (matching ``Settings``' own
    case-insensitive validation) so a value like ``"MONGO"`` cannot silently
    build an ARQ adapter.
    """
    settings = get_settings()
    if settings.queue_backend.strip().lower() != "mongo":
        return ArqQueueAdapter(settings.redis_url)
    if not settings.mongo_queue_enabled:
        raise MongoQueueNotEnabledError(
            "Mongo queue requested but MONGO_QUEUE_ENABLED is false; ARQ remains "
            "the default. Opt in explicitly before using the Mongo backend."
        )
    from backend.core.database import MongoDB
    from backend.queue.mongo_adapter import MongoQueueAdapter

    if db is None:
        # Reuse the existing client/pool; target the explicit queue database.
        db = MongoDB.client()[queue_database_name(settings)]
    return MongoQueueAdapter(db, **build_mongo_config_kwargs(settings))


__all__ = [
    "DEFAULT_QUEUE_DATABASE",
    "build_mongo_config_kwargs",
    "get_queue",
    "queue_database_name",
]
