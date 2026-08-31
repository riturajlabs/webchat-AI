"""Regression tests for the Mongo feedback repository (Phase 12.4).

The fake collection mirrors the minimal Motor surface the repository touches:
`insert_one`, `find` (with sort/skip/limit), `count_documents` (with filter),
and `aggregate` `$match`/`$group` semantics. This catches query-shape bugs
(list ordering, filter predicates, summary bucketing, TTL field handling)
without a live MongoDB.
"""

from datetime import UTC, datetime, timedelta

from backend.models.feedback import Feedback
from backend.repositories.feedback_repository import MongoFeedbackRepository
from pymongo.errors import DuplicateKeyError

TENANT = "tenant-a"


def _feedback(message_id: str, rating: int, category: str, created_at: datetime) -> Feedback:
    return Feedback(
        id=f"fb-{message_id}",
        tenant_id=TENANT,
        website_id="web-1",
        session_id="session-1",
        message_id=message_id,
        rating=rating,
        category=category,
        created_at=created_at,
    )


class _FakeCursor:
    """Mirror Mongo's `find().sort().skip().limit()` (skip after sort)."""

    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    def sort(self, key: str, direction: int) -> "_FakeCursor":
        self._docs = sorted(self._docs, key=lambda doc: doc[key], reverse=direction < 0)
        return self

    def skip(self, n: int) -> "_FakeCursor":
        self._docs = self._docs[n:]
        return self

    def limit(self, n: int) -> "_FakeCursor":
        self._docs = self._docs[:n]
        return self

    def __aiter__(self) -> "_FakeCursor":
        return self

    async def __anext__(self) -> dict:
        if not self._docs:
            raise StopAsyncIteration
        return self._docs.pop(0)


class _FakeFeedbackCollection:
    def __init__(self, docs: list[Feedback]) -> None:
        self._docs = [doc.to_doc() for doc in docs]

    @staticmethod
    def _matches(query: dict, doc: dict) -> bool:
        for key, expected in query.items():
            if key == "created_at" and isinstance(expected, dict):
                if doc[key] < expected["$gte"]:
                    return False
            elif doc.get(key) != expected:
                return False
        return True

    async def insert_one(self, doc: dict) -> None:
        """Enforce the unique (tenant_id, message_id) index like MongoDB."""
        for existing in self._docs:
            if existing.get("tenant_id") == doc.get("tenant_id") and existing.get(
                "message_id"
            ) == doc.get("message_id"):
                raise DuplicateKeyError(
                    "E11000 duplicate key error collection: feedback index: uniq_tenant_message"
                )
        self._docs.append(doc)

    async def find_one(self, query: dict) -> dict | None:
        for doc in self._docs:
            if self._matches(query, doc):
                return doc
        return None

    def find(self, query: dict) -> "_FakeCursor":
        return _FakeCursor([doc for doc in self._docs if self._matches(query, doc)])

    async def count_documents(self, query: dict) -> int:
        return sum(1 for doc in self._docs if self._matches(query, doc))

    def aggregate(self, pipeline: list[dict]) -> "_FakeCursor":
        """Support the `$match` then `$group` shape the summary uses."""
        grouped: dict[object, int] = {}
        for doc in self._docs:
            skip = False
            for stage in pipeline:
                if "$match" in stage:
                    if not self._matches(stage["$match"], doc):
                        skip = True
                if skip:
                    break
                if "$group" in stage:
                    group_id = stage["$group"]["_id"]
                    if isinstance(group_id, str) and group_id.startswith("$"):
                        bucket = doc[group_id[1:]]
                    else:
                        bucket = doc[group_id]
                    grouped[bucket] = grouped.get(bucket, 0) + 1
        return _FakeCursor([{"_id": bucket, "count": count} for bucket, count in grouped.items()])


def _make_repo(docs: list[Feedback]) -> tuple[MongoFeedbackRepository, _FakeFeedbackCollection]:
    collection = _FakeFeedbackCollection(docs)
    repo = MongoFeedbackRepository.__new__(MongoFeedbackRepository)
    repo._collection = collection
    return repo, collection


def test_list_by_tenant_sorts_newest_first() -> None:
    base = datetime(2026, 8, 1, tzinfo=UTC)
    docs = [
        _feedback("msg-1", 5, "helpful", base + timedelta(days=1)),
        _feedback("msg-2", 2, "wrong", base + timedelta(days=3)),
        _feedback("msg-3", 4, "helpful", base + timedelta(days=2)),
    ]
    repo, _ = _make_repo(docs)

    results = _run(repo.list_by_tenant(TENANT, limit=10, offset=0))

    assert [item.message_id for item in results] == ["msg-2", "msg-3", "msg-1"]


def test_list_by_tenant_applies_website_and_category_filters() -> None:
    base = datetime(2026, 8, 1, tzinfo=UTC)
    docs = [
        _feedback("msg-1", 5, "helpful", base),
        Feedback(
            id="fb-2",
            tenant_id=TENANT,
            website_id="web-2",
            session_id="s",
            message_id="msg-2",
            rating=1,
            category="wrong",
            created_at=base,
        ),
    ]
    repo, _ = _make_repo(docs)

    results = _run(repo.list_by_tenant(TENANT, website_id="web-1", limit=10, offset=0))
    assert [item.message_id for item in results] == ["msg-1"]

    results = _run(repo.list_by_tenant(TENANT, category="wrong", limit=10, offset=0))
    assert [item.message_id for item in results] == ["msg-2"]


def test_count_by_tenant_respects_filters() -> None:
    base = datetime(2026, 8, 1, tzinfo=UTC)
    docs = [
        _feedback("msg-1", 5, "helpful", base),
        _feedback("msg-2", 3, "incomplete", base),
        _feedback("msg-3", 1, "offensive", base),
    ]
    repo, _ = _make_repo(docs)

    assert _run(repo.count_by_tenant(TENANT)) == 3
    assert _run(repo.count_by_tenant(TENANT, rating=5)) == 1
    assert _run(repo.count_by_tenant(TENANT, category="offensive")) == 1


def test_summary_buckets_ratings_and_respects_window() -> None:
    base = datetime(2026, 8, 1, tzinfo=UTC)
    docs = [
        _feedback("msg-1", 5, "helpful", base),
        _feedback("msg-2", 5, "helpful", base + timedelta(days=10)),
        _feedback("msg-3", 1, "wrong", base + timedelta(days=20)),
    ]
    repo, _ = _make_repo(docs)

    summary = _run(repo.summary_by_tenant(TENANT, since=base + timedelta(days=5)))

    assert summary.total == 2
    assert summary.distribution == {5: 1, 1: 1}


def test_find_by_message_scopes_to_tenant() -> None:
    base = datetime(2026, 8, 1, tzinfo=UTC)
    other = Feedback(
        id="fb-other",
        tenant_id="tenant-b",
        website_id="web-1",
        session_id="s",
        message_id="msg-1",
        rating=4,
        category="helpful",
        created_at=base,
    )
    repo, _ = _make_repo([other])

    assert _run(repo.find_by_message(TENANT, "msg-1")) is None


def test_create_is_idempotent_on_duplicate_tenant_message() -> None:
    base = datetime(2026, 8, 1, tzinfo=UTC)
    repo, _ = _make_repo([])

    _run(repo.create(_feedback("msg-1", 5, "helpful", base)))
    _run(repo.create(_feedback("msg-1", 3, "wrong", base + timedelta(days=1))))

    items = _run(repo.list_by_tenant(TENANT))
    assert len(items) == 1
    assert items[0].rating == 5
    assert items[0].message_id == "msg-1"


def test_create_still_persists_distinct_messages_for_same_tenant() -> None:
    base = datetime(2026, 8, 1, tzinfo=UTC)
    repo, _ = _make_repo([])

    _run(repo.create(_feedback("msg-1", 5, "helpful", base)))
    _run(repo.create(_feedback("msg-2", 2, "wrong", base)))

    items = _run(repo.list_by_tenant(TENANT))
    assert {item.message_id for item in items} == {"msg-1", "msg-2"}


def _run(coro) -> object:
    """Synchronously drive an async repository call in tests."""
    import asyncio

    return asyncio.run(coro)
