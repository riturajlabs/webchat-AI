"""MongoDB index-migration tests.

Verify that `MongoDB.init_indexes()` declares every index required by the
production audit (Priority 2) so that schema migrations stay correct:
users(tenant_id, status), refresh_tokens(tenant_id, user_id), the 1-year TTL
on audit_logs, and the unique constraints the app relies on for correctness.
"""

from collections import defaultdict

from backend.core.database import MongoDB

# ADR-005 §5.7 values (kept in sync with backend/core/database.py).
REFRESH_TOKEN_TTL = 40 * 24 * 60 * 60
AUDIT_LOG_TTL = 365 * 24 * 60 * 60
CRAWL_JOB_TTL = 30 * 24 * 60 * 60


class _FakeCollection:
    def __init__(self) -> None:
        self.indexes: list[tuple[object, dict[str, object]]] = []

    async def create_index(self, keys: object, **kwargs: object) -> None:
        self.indexes.append((keys, kwargs))


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
    assert ("email", True) in indexes          # unique login key (race gatekeeper)
    assert ("tenant_id", False) in indexes      # tenant-scoped queries
    assert ("status", False) in indexes         # suspension filtering


async def test_init_indexes_declares_required_refresh_token_indexes(monkeypatch) -> None:
    db = _FakeDb()
    monkeypatch.setattr("backend.core.database.MongoDB.db", lambda: db)

    await MongoDB.init_indexes()

    indexes = _index_map(db["refresh_tokens"])
    assert ("token_hash", True) in indexes      # reuse detection lookup
    assert ("tenant_id", False) in indexes      # tenant-scoped queries
    assert ("user_id", False) in indexes        # logout / revoke-all-for-user
    ttl = [kwargs for keys, kwargs in db["refresh_tokens"].indexes
           if kwargs.get("expireAfterSeconds")]
    assert ttl == [{"expireAfterSeconds": REFRESH_TOKEN_TTL}]


async def test_init_indexes_declares_member_unique_compound_index(monkeypatch) -> None:
    db = _FakeDb()
    monkeypatch.setattr("backend.core.database.MongoDB.db", lambda: db)

    await MongoDB.init_indexes()

    indexes = _index_map(db["members"])
    assert any(
        keys == (("tenant_id", 1), ("user_id", 1)) and unique
        for (keys, unique) in indexes
    )


async def test_init_indexes_declares_audit_log_ttl_of_one_year(monkeypatch) -> None:
    db = _FakeDb()
    monkeypatch.setattr("backend.core.database.MongoDB.db", lambda: db)

    await MongoDB.init_indexes()

    ttl = [kwargs for keys, kwargs in db["audit_logs"].indexes
           if kwargs.get("expireAfterSeconds")]
    assert ttl == [{"expireAfterSeconds": AUDIT_LOG_TTL}]
    # The tenant-scoped sort index is also present (ADR-006 audit viewer).
    assert any("tenant_id" in str(keys) and "created_at" in str(keys)
               for keys, _ in db["audit_logs"].indexes)


async def test_init_indexes_declares_website_indexes(monkeypatch) -> None:
    db = _FakeDb()
    monkeypatch.setattr("backend.core.database.MongoDB.db", lambda: db)

    await MongoDB.init_indexes()

    indexes = _index_map(db["websites"])
    # The unique (tenant_id, url) pair is the duplicate gatekeeper (Phase 3).
    assert any(
        keys == (("tenant_id", 1), ("url", 1)) and unique
        for (keys, unique) in indexes
    )
    assert ("tenant_id", False) in indexes
    assert ("url", False) in indexes


async def test_init_indexes_declares_widget_indexes(monkeypatch) -> None:
    db = _FakeDb()
    monkeypatch.setattr("backend.core.database.MongoDB.db", lambda: db)

    await MongoDB.init_indexes()

    indexes = _index_map(db["widgets"])
    assert ("widget_id", True) in indexes        # public widget identifier
    assert ("tenant_id", False) in indexes        # tenant-scoped queries
    # One widget per (tenant, website): (tenant_id, website_id) unique.
    assert any(
        keys == (("tenant_id", 1), ("website_id", 1)) and unique
        for (keys, unique) in indexes
    )


async def test_init_indexes_declares_crawl_job_ttl_of_30_days(monkeypatch) -> None:
    db = _FakeDb()
    monkeypatch.setattr("backend.core.database.MongoDB.db", lambda: db)

    await MongoDB.init_indexes()

    ttl = [kwargs for keys, kwargs in db["crawl_jobs"].indexes
           if kwargs.get("expireAfterSeconds")]
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
