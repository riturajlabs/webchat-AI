"""MongoDB index-migration tests.

Verify that `MongoDB.init_indexes()` declares every index required by the
production audit (Priority 2) so that schema migrations stay correct:
users(tenant_id, status), refresh_tokens(tenant_id, user_id), the 1-year TTL
on audit_logs, and the unique constraints the app relies on for correctness.
"""

from collections import defaultdict

import pytest
from backend.core.database import MongoDB
from backend.models.website import WEBSITE_STATUS_DELETED

# ADR-005 §5.7 values (kept in sync with backend/core/database.py).
REFRESH_TOKEN_TTL = 40 * 24 * 60 * 60
AUDIT_LOG_TTL = 365 * 24 * 60 * 60
CRAWL_JOB_TTL = 30 * 24 * 60 * 60
CHAT_TTL = 90 * 24 * 60 * 60
USAGE_TTL = 3 * 365 * 24 * 60 * 60
# chat_sessions use the Mongo "deadline" TTL: delete exactly at `expires_at`
# (the field already encodes now + CHAT_RETENTION_DAYS), so expireAfterSeconds
# is 0 - never double-counting retention.
CHAT_SESSION_TTL = 0


def _default_index_name(keys: object) -> str:
    """MongoDB-style default index name for a single-field or compound key."""
    if isinstance(keys, str):
        return f"{keys}_1"
    return "_".join(f"{k}_{direction}" for k, direction in keys)


class _FakeCollection:
    def __init__(self) -> None:
        self.indexes: list[tuple[object, dict[str, object]]] = []
        self.dropped: list[str] = []
        self.updates: list[tuple[object, object]] = []
        self._index_infos: dict[str, dict[str, object]] = {}
        self.aggregate_results: list[object] = []

    async def create_index(self, keys: object, **kwargs: object) -> None:
        self.indexes.append((keys, kwargs))
        name = str(kwargs.get("name") or _default_index_name(keys))
        spec: dict[str, object] = {"key": {}, "unique": bool(kwargs.get("unique", False))}
        if isinstance(keys, str):
            spec["key"] = {keys: 1}
        else:
            spec["key"] = {k: v for k, v in keys}
        if "partialFilterExpression" in kwargs:
            spec["partialFilterExpression"] = kwargs["partialFilterExpression"]
        self._index_infos[name] = spec

    async def drop_index(self, name: str) -> None:
        self.dropped.append(name)
        self._index_infos.pop(name, None)

    async def update_many(self, filter: object, update: object) -> None:
        self.updates.append((filter, update))

    async def index_information(self) -> dict[str, dict[str, object]]:
        return {"_id_": {"key": {"_id": 1}}, **self._index_infos}

    def aggregate(self, _pipeline: object) -> "_FakeAggregate":
        return _FakeAggregate(self.aggregate_results)


class _FakeAggregate:
    """Bear-catcher for cursor.aggregate(...).to_list(...) in the index helper."""

    def __init__(self, results: list[object]) -> None:
        self._results = results

    async def to_list(self, length: int | None = None) -> list[object]:
        if length is None:
            return self._results
        return self._results[:length]


class _FakeDb:
    def __init__(self) -> None:
        self._collections: dict[str, _FakeCollection] = defaultdict(_FakeCollection)

    def __getitem__(self, name: str) -> _FakeCollection:
        return self._collections[name]


def _index_map(collection: _FakeCollection) -> dict[tuple[object, bool], dict[str, object]]:
    """{(keys, unique): kwargs} for easy assertions (lists normalized to tuples)."""
    normalized: list[tuple[tuple[object, bool], dict[str, object]]] = []
    for keys, kwargs in collection.indexes:
        if isinstance(keys, list):
            keys = tuple(keys)
        normalized.append(((keys, bool(kwargs.get("unique", False))), kwargs))
    return dict(normalized)


async def test_init_indexes_declares_required_user_indexes(monkeypatch) -> None:
    db = _FakeDb()
    monkeypatch.setattr("backend.core.database.MongoDB.db", lambda: db)

    await MongoDB.init_indexes()

    indexes = _index_map(db["users"])
    assert ("email", True) in indexes  # unique login key (race gatekeeper)
    assert ("tenant_id", False) in indexes  # tenant-scoped queries
    assert ("status", False) in indexes  # suspension filtering


async def test_init_indexes_declares_required_refresh_token_indexes(monkeypatch) -> None:
    db = _FakeDb()
    monkeypatch.setattr("backend.core.database.MongoDB.db", lambda: db)

    await MongoDB.init_indexes()

    indexes = _index_map(db["refresh_tokens"])
    assert ("token_hash", True) in indexes  # reuse detection lookup
    assert ("tenant_id", False) in indexes  # tenant-scoped queries
    assert ("user_id", False) in indexes  # logout / revoke-all-for-user
    ttl = [
        kwargs for keys, kwargs in db["refresh_tokens"].indexes if kwargs.get("expireAfterSeconds")
    ]
    assert ttl == [{"expireAfterSeconds": REFRESH_TOKEN_TTL}]


async def test_init_indexes_declares_member_unique_compound_index(monkeypatch) -> None:
    db = _FakeDb()
    monkeypatch.setattr("backend.core.database.MongoDB.db", lambda: db)

    await MongoDB.init_indexes()

    indexes = _index_map(db["members"])
    assert any(keys == (("tenant_id", 1), ("user_id", 1)) and unique for (keys, unique) in indexes)


async def test_init_indexes_declares_audit_log_ttl_of_one_year(monkeypatch) -> None:
    db = _FakeDb()
    monkeypatch.setattr("backend.core.database.MongoDB.db", lambda: db)

    await MongoDB.init_indexes()

    ttl = [kwargs for keys, kwargs in db["audit_logs"].indexes if kwargs.get("expireAfterSeconds")]
    assert ttl == [{"expireAfterSeconds": AUDIT_LOG_TTL}]
    # The tenant-scoped sort index is also present (ADR-006 audit viewer).
    assert any(
        "tenant_id" in str(keys) and "created_at" in str(keys)
        for keys, _ in db["audit_logs"].indexes
    )


async def test_init_indexes_declares_admin_audit_log_indexes(monkeypatch) -> None:
    """Phase 15: the dedicated admin trail has no TTL (10-year compliance)."""
    db = _FakeDb()
    monkeypatch.setattr("backend.core.database.MongoDB.db", lambda: db)

    await MongoDB.init_indexes()

    indexes = _index_map(db["admin_audit_logs"])
    # List + filter sort keys used by GET /api/admin/audit.
    assert any(
        keys == (("tenant_id", 1), ("created_at", -1)) and not unique for (keys, unique) in indexes
    )
    assert any(
        keys == (("action", 1), ("created_at", -1)) and not unique for (keys, unique) in indexes
    )
    assert any(
        keys == (("actor_user_id", 1), ("created_at", -1)) and not unique
        for (keys, unique) in indexes
    )
    # No TTL index: the platform admin trail outlives the 1-year tenant audit.
    assert not any("expireAfterSeconds" in kwargs for _, kwargs in indexes.items())


async def test_init_indexes_declares_website_indexes(monkeypatch) -> None:
    db = _FakeDb()
    monkeypatch.setattr("backend.core.database.MongoDB.db", lambda: db)

    await MongoDB.init_indexes()

    indexes = _index_map(db["websites"])
    # (tenant_id, url) is unique among *active* websites: the race-free
    # duplicate gatekeeper. The partial filter (`deleted: false`, equality
    # only - MongoDB partial indexes cannot express `$ne`) excludes
    # soft-deleted records so a deleted website's URL can be re-registered.
    partial_unique = [
        kwargs
        for (keys, unique), kwargs in indexes.items()
        if keys == (("tenant_id", 1), ("url", 1)) and unique
    ]
    assert partial_unique == [{"unique": True, "partialFilterExpression": {"deleted": False}}]
    assert ("tenant_id", False) in indexes
    assert ("url", False) in indexes
    # The `deleted` flag is backfilled from the legacy `status` marker and the
    # legacy full-unique index is dropped so it no longer blocks URL reuse.
    assert (
        {"status": {"$ne": WEBSITE_STATUS_DELETED}},
        {"$set": {"deleted": False}},
    ) in db["websites"].updates
    assert ({"status": WEBSITE_STATUS_DELETED}, {"$set": {"deleted": True}}) in db[
        "websites"
    ].updates
    assert "tenant_id_1_url_1" in db["websites"].dropped


async def test_init_indexes_declares_widget_indexes(monkeypatch) -> None:
    db = _FakeDb()
    monkeypatch.setattr("backend.core.database.MongoDB.db", lambda: db)

    await MongoDB.init_indexes()

    indexes = _index_map(db["widgets"])
    assert ("widget_id", True) in indexes  # public widget identifier
    assert ("tenant_id", False) in indexes  # tenant-scoped queries
    # One widget per (tenant, website): (tenant_id, website_id) unique.
    assert any(
        keys == (("tenant_id", 1), ("website_id", 1)) and unique for (keys, unique) in indexes
    )


async def test_init_indexes_declares_crawl_job_ttl_of_30_days(monkeypatch) -> None:
    db = _FakeDb()
    monkeypatch.setattr("backend.core.database.MongoDB.db", lambda: db)

    await MongoDB.init_indexes()

    ttl = [kwargs for keys, kwargs in db["crawl_jobs"].indexes if kwargs.get("expireAfterSeconds")]
    assert ttl == [{"expireAfterSeconds": CRAWL_JOB_TTL}]
    # The status index drives the active-job gatekeeper and admin queue monitor.
    assert any(
        keys == (("tenant_id", 1), ("status", 1)) and not unique
        for (keys, unique) in _index_map(db["crawl_jobs"])
    )


async def test_init_indexes_declares_document_indexes(monkeypatch) -> None:
    db = _FakeDb()
    monkeypatch.setattr("backend.core.database.MongoDB.db", lambda: db)

    await MongoDB.init_indexes()

    indexes = _index_map(db["documents"])
    # The unique (tenant_id, website_id, url) triple makes re-crawls idempotent.
    assert any(
        keys == (("tenant_id", 1), ("website_id", 1), ("url", 1)) and unique
        for (keys, unique) in indexes
    )
    assert ("tenant_id", False) in indexes
    assert ("website_id", False) in indexes
    assert ("url", False) in indexes


async def test_init_indexes_declares_chat_session_indexes(monkeypatch) -> None:
    db = _FakeDb()
    monkeypatch.setattr("backend.core.database.MongoDB.db", lambda: db)

    await MongoDB.init_indexes()

    indexes = _index_map(db["chat_sessions"])
    assert ("session_id", True) in indexes  # conversation key (docs/05 §9)
    assert ("tenant_id", False) in indexes  # tenant-scoped queries
    assert any(
        keys == (("tenant_id", 1), ("website_id", 1)) and not unique for (keys, unique) in indexes
    )
    # PERF-K05: covering index for the (tenant, website) filter + last_activity
    # sort used by conversation listing (avoids an in-memory filesort).
    assert any(
        keys == (("tenant_id", 1), ("website_id", 1), ("last_activity", -1)) and not unique
        for (keys, unique) in indexes
    )
    ttl = [kwargs for keys, kwargs in db["chat_sessions"].indexes if "expireAfterSeconds" in kwargs]
    assert ttl == [{"expireAfterSeconds": CHAT_SESSION_TTL}]


async def test_init_indexes_declares_message_indexes(monkeypatch) -> None:
    db = _FakeDb()
    monkeypatch.setattr("backend.core.database.MongoDB.db", lambda: db)

    await MongoDB.init_indexes()

    indexes = _index_map(db["messages"])
    assert ("tenant_id", False) in indexes
    assert ("session_id", False) in indexes
    # Conversation-memory query: (tenant, session, created_at).
    assert any(
        keys == (("tenant_id", 1), ("session_id", 1), ("created_at", 1)) and not unique
        for (keys, unique) in indexes
    )
    # Dashboard-analytics query: (tenant, role, created_at).
    assert any(
        keys == (("tenant_id", 1), ("role", 1), ("created_at", 1)) and not unique
        for (keys, unique) in indexes
    )
    ttl = [kwargs for keys, kwargs in db["messages"].indexes if kwargs.get("expireAfterSeconds")]
    assert ttl == [{"expireAfterSeconds": CHAT_TTL}]


async def test_init_indexes_declares_usage_record_indexes(monkeypatch) -> None:
    db = _FakeDb()
    monkeypatch.setattr("backend.core.database.MongoDB.db", lambda: db)

    await MongoDB.init_indexes()

    indexes = _index_map(db["usage_records"])
    # The unique (tenant, website, date) triple makes daily rollups idempotent.
    assert any(
        keys == (("tenant_id", 1), ("website_id", 1), ("date", 1)) and unique
        for (keys, unique) in indexes
    )
    assert ("tenant_id", False) in indexes
    assert ("date", False) in indexes
    ttl = [
        kwargs for keys, kwargs in db["usage_records"].indexes if kwargs.get("expireAfterSeconds")
    ]
    assert ttl == [{"expireAfterSeconds": USAGE_TTL}]


async def test_init_indexes_declares_api_key_indexes(monkeypatch) -> None:
    db = _FakeDb()
    monkeypatch.setattr("backend.core.database.MongoDB.db", lambda: db)

    await MongoDB.init_indexes()

    indexes = _index_map(db["api_keys"])
    # hashed_secret is the authentication lookup key: must be unique.
    assert ("hashed_secret", True) in indexes
    assert ("tenant_id", False) in indexes  # tenant-scoped queries
    # List + audit read sort: (tenant_id, created_at).
    assert any(
        keys == (("tenant_id", 1), ("created_at", -1)) and not unique for (keys, unique) in indexes
    )


async def test_init_indexes_declares_feedback_indexes(monkeypatch) -> None:
    """Phase 12.4 visitor feedback: tenant reads + the analytics breakdowns.

    The (tenant_id, website_id, created_at) compound index serves the
    feedback analytics endpoint filtered per website (retail analytics view),
    the (tenant_id, message_id) unique key keeps submissions write-once, and
    created_at TTL matches ADR-005 §5.7's two-year retention.
    """
    db = _FakeDb()
    monkeypatch.setattr("backend.core.database.MongoDB.db", lambda: db)

    await MongoDB.init_indexes()

    indexes = _index_map(db["feedback"])
    assert ("tenant_id", False) in indexes
    assert any(
        keys == (("tenant_id", 1), ("created_at", -1)) and not unique for (keys, unique) in indexes
    )
    assert any(
        keys == (("tenant_id", 1), ("website_id", 1), ("created_at", -1)) and not unique
        for (keys, unique) in indexes
    )
    assert any(
        keys == (("tenant_id", 1), ("message_id", 1)) and unique for (keys, unique) in indexes
    )
    ttl = [kwargs for keys, kwargs in db["feedback"].indexes if kwargs.get("expireAfterSeconds")]
    assert ttl == [{"expireAfterSeconds": 2 * 365 * 24 * 60 * 60}]


async def test_init_indexes_declares_subscription_payment_id_partial_unique_index(
    monkeypatch,
) -> None:
    """Phase 16: payment_id is unique only among real gateway ids.

    A partial unique filter (`$type: "string"`) keeps webhook idempotency for
    paid subscriptions while letting admin grants (payment_id empty) coexist.
    """
    db = _FakeDb()
    monkeypatch.setattr("backend.core.database.MongoDB.db", lambda: db)

    await MongoDB.init_indexes()

    infos = await db["subscriptions"].index_information()
    payment = infos["payment_id_1"]
    assert payment["key"] == {"payment_id": 1}
    assert payment["unique"] is True
    assert payment["partialFilterExpression"] == {"payment_id": {"$type": "string"}}


async def test_init_indexes_migrates_legacy_subscription_payment_id_index(monkeypatch) -> None:
    """The legacy non-partial unique index is replaced, not left conflicted."""
    db = _FakeDb()
    await db["subscriptions"].create_index("payment_id", unique=True)
    monkeypatch.setattr("backend.core.database.MongoDB.db", lambda: db)

    await MongoDB.init_indexes()

    collection = db["subscriptions"]
    assert "payment_id_1" in collection.dropped
    (created, kwargs) = collection.indexes[-1]
    assert created == "payment_id"
    assert kwargs == {
        "unique": True,
        "partialFilterExpression": {"payment_id": {"$type": "string"}},
    }
    infos = await collection.index_information()
    assert infos["payment_id_1"] == {
        "key": {"payment_id": 1},
        "unique": True,
        "partialFilterExpression": {"payment_id": {"$type": "string"}},
    }


async def test_init_indexes_migration_is_idempotent(monkeypatch) -> None:
    """Migrating a fresh partial index is a no-op (already-desired early exit)."""
    db = _FakeDb()
    monkeypatch.setattr("backend.core.database.MongoDB.db", lambda: db)

    await MongoDB.init_indexes()
    dropped_snapshot = list(db["subscriptions"].dropped)

    await MongoDB.init_indexes()

    assert db["subscriptions"].dropped == dropped_snapshot
    payment_creates = [entry for entry in db["subscriptions"].indexes if entry[0] == "payment_id"]
    assert len(payment_creates) == 1
    assert payment_creates[0][1] == {
        "unique": True,
        "partialFilterExpression": {"payment_id": {"$type": "string"}},
    }


async def test_init_indexes_aborts_migration_on_duplicate_payment_ids(monkeypatch) -> None:
    """Duplicate string payment_ids must block the drop+create, not mask it."""
    db = _FakeDb()
    await db["subscriptions"].create_index("payment_id", unique=True)
    db["subscriptions"].aggregate_results = [{"_id": "pm_dup", "count": 2}]
    monkeypatch.setattr("backend.core.database.MongoDB.db", lambda: db)

    with pytest.raises(RuntimeError, match="Duplicate payment_id"):
        await MongoDB.init_indexes()

    # The legacy index is untouched when the safety check fails.
    assert "payment_id_1" not in db["subscriptions"].dropped
    infos = await db["subscriptions"].index_information()
    assert infos["payment_id_1"].get("partialFilterExpression") is None


# ---------------------------------------------------------------------------
# FIND-02 crawl_jobs single-flight index (tenant_id, website_id, active)
# ---------------------------------------------------------------------------


def _crawl_active_index_keys():
    return ("tenant_id", 1), ("website_id", 1), ("active", 1)


async def test_init_indexes_backfills_active_flag_and_creates_partial_unique_index(
    monkeypatch,
) -> None:
    """Non-terminal jobs stay gate-blocking (`active=True`), terminal jobs
    release the fence (`active=False`), and the partial unique index is
    declared exactly once."""
    db = _FakeDb()
    monkeypatch.setattr("backend.core.database.MongoDB.db", lambda: db)

    await MongoDB.init_indexes()

    # Backfill order: active rows first, then terminal rows.
    assert db["crawl_jobs"].updates == [
        ({"status": {"$in": ["pending", "processing", "running"]}}, {"$set": {"active": True}}),
        ({"status": {"$nin": ["pending", "processing", "running"]}}, {"$set": {"active": False}}),
    ]
    index_map = _index_map(db["crawl_jobs"])
    assert (_crawl_active_index_keys(), True) in index_map
    kwargs = index_map[(_crawl_active_index_keys(), True)]
    assert kwargs["partialFilterExpression"] == {"active": True}
    # TTL index still declared alongside FIND-02.
    ttl_creates = [entry for entry in db["crawl_jobs"].indexes if "expireAfterSeconds" in entry[1]]
    assert len(ttl_creates) == 1


async def test_init_indexes_crawl_active_index_is_idempotent(monkeypatch) -> None:
    """A matching existing partial unique index is left untouched (no recreate,
    no aggregate, no error) - safe for repeated worker/boot migrations."""
    db = _FakeDb()
    await db["crawl_jobs"].create_index(
        [("tenant_id", 1), ("website_id", 1), ("active", 1)],
        unique=True,
        partialFilterExpression={"active": True},
    )
    monkeypatch.setattr("backend.core.database.MongoDB.db", lambda: db)

    await MongoDB.init_indexes()
    await MongoDB.init_indexes()

    creates = [
        entry for entry in db["crawl_jobs"].indexes if tuple(entry[0]) == _crawl_active_index_keys()
    ]
    assert len(creates) == 1
    assert creates[0][1]["partialFilterExpression"] == {"active": True}


async def test_init_indexes_refuses_duplicate_active_crawl_jobs(monkeypatch) -> None:
    """Pre-existing duplicate ACTIVE rows must fail loudly instead of silently
    deleting data when the FIND-02 index is created."""
    db = _FakeDb()
    db["crawl_jobs"].aggregate_results = [
        {"_id": {"tenant_id": "tenant-a", "website_id": "w1"}, "count": 2}
    ]
    monkeypatch.setattr("backend.core.database.MongoDB.db", lambda: db)

    with pytest.raises(RuntimeError, match="Duplicate active crawl_jobs"):
        await MongoDB.init_indexes()

    index_map = _index_map(db["crawl_jobs"])
    assert (_crawl_active_index_keys(), True) not in index_map
