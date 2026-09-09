"""PERF-K02 regression: MongoAdminRepository.platform_stats runs concurrently.

The admin overview previously issued 10 sequential ``count_documents`` waits
(one network round trip each). This test pins both correctness (the aggregated
values must be unchanged) and the concurrency fix (the queries overlap, so
``platform_stats`` costs one round trip, not ten).
"""

import asyncio
from typing import Any

from backend.repositories.admin_repository import MongoAdminRepository


class _Tracker:
    def __init__(self) -> None:
        self.current = 0
        self.max_seen = 0

    async def __aenter__(self) -> "_Tracker":
        self.current += 1
        self.max_seen = max(self.max_seen, self.current)
        # Yield control so concurrently-scheduled coroutines can enter too.
        await asyncio.sleep(0)
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.current -= 1


class _CountColl:
    """Serves a fixed answer sequence, one per count_documents call."""

    def __init__(self, answers: list[int], tracker: _Tracker) -> None:
        self._answers: list[int] = answers
        self._tracker = tracker

    async def count_documents(self, query: dict[str, Any]) -> int:
        async with self._tracker:
            return self._answers.pop(0)


class _UsageCursor:
    """One-document async cursor mirroring a `$group: null` result row."""

    def __init__(self, doc: dict[str, Any], tracker: _Tracker) -> None:
        self._doc = doc
        self._tracker = tracker
        self._done = False

    def __aiter__(self) -> "_UsageCursor":
        return self

    async def __anext__(self) -> dict[str, Any]:
        async with self._tracker:
            if self._done:
                raise StopAsyncIteration
            self._done = True
            return self._doc


class _UsageColl:
    def __init__(self, doc: dict[str, Any], tracker: _Tracker) -> None:
        self._doc = doc
        self._tracker = tracker

    def aggregate(self, pipeline: list[dict[str, Any]]) -> _UsageCursor:
        # Synchronous like Motor: `aggregate()` returns a cursor; `_first`
        # drives it with `async for`. (An `async def` here would return a
        # coroutine, not an async-iterable, breaking the `_first` contract.)
        return _UsageCursor(self._doc, self._tracker)


class _NullColl:
    """Stub for collections platform_stats() never touches."""

    async def count_documents(self, query: dict[str, Any]) -> int:
        raise AssertionError("platform_stats must not query this collection")


class _Db:
    def __init__(self, collections: dict[str, Any]) -> None:
        self._collections = collections

    def __getitem__(self, name: str) -> Any:
        return self._collections[name]


async def test_platform_stats_fires_counts_concurrently_and_returns_correct_values() -> None:
    tracker = _Tracker()
    tenants = _CountColl([10, 7, 2], tracker)  # total, active, suspended
    users = _CountColl([25, 18, 1], tracker)  # total, active, suspended
    crawl_jobs = _CountColl([40, 3, 5], tracker)  # total, active, failed
    usage_doc: dict[str, Any] = {
        "conversations": 1000,
        "messages": 3000,
        "input_tokens": 50000,
        "output_tokens": 20000,
    }
    usage = _UsageColl(usage_doc, tracker)
    db = _Db(
        {
            "tenants": tenants,
            "users": users,
            "crawl_jobs": crawl_jobs,
            "usage_records": usage,
            "chat_sessions": _NullColl(),
            "websites": _NullColl(),
            "widgets": _NullColl(),
            "documents": _NullColl(),
            "messages": _NullColl(),
            "api_keys": _NullColl(),
            "subscriptions": _NullColl(),
            "audit_logs": _NullColl(),
            "admin_audit_logs": _NullColl(),
        }
    )
    repo = MongoAdminRepository(db)

    stats = await repo.platform_stats()

    assert stats.total_tenants == 10
    assert stats.active_tenants == 7
    assert stats.suspended_tenants == 2
    assert stats.total_users == 25
    assert stats.active_users == 18
    assert stats.suspended_users == 1
    assert stats.total_crawl_jobs == 40
    assert stats.active_crawl_jobs == 3
    assert stats.failed_crawl_jobs == 5
    assert stats.total_conversations == 1000
    assert stats.total_messages == 3000
    assert stats.total_input_tokens == 50000
    assert stats.total_output_tokens == 20000

    # PERF-K02: the counts were collected together, not one sequential round
    # trip after another. A sequential implementation never exceeds 1 in flight.
    assert tracker.max_seen >= 4


async def test_collection_counts_gathers_concurrent_and_returns_values() -> None:
    """PERF-K04: the 12 admin collection counts run concurrently (gather)."""
    tracker = _Tracker()

    class _FixedColl:
        def __init__(self, value: int) -> None:
            self._value = value

        async def count_documents(self, query: dict[str, Any]) -> int:
            async with tracker:
                return self._value

    db = _Db(
        {
            "users": _FixedColl(101),
            "tenants": _FixedColl(102),
            "websites": _FixedColl(103),
            "widgets": _FixedColl(104),
            "documents": _FixedColl(105),
            "chat_sessions": _FixedColl(106),
            "messages": _FixedColl(107),
            "usage_records": _FixedColl(108),
            "api_keys": _FixedColl(109),
            "subscriptions": _FixedColl(110),
            "audit_logs": _FixedColl(111),
            "admin_audit_logs": _FixedColl(112),
            "crawl_jobs": _FixedColl(0),
        }
    )
    repo = MongoAdminRepository(db)

    counts = await repo.collection_counts()

    assert counts.users == 101
    assert counts.tenants == 102
    assert counts.websites == 103
    assert counts.widgets == 104
    assert counts.documents == 105
    assert counts.chat_sessions == 106
    assert counts.messages == 107
    assert counts.usage_records == 108
    assert counts.api_keys == 109
    assert counts.subscriptions == 110
    assert counts.audit_logs == 111
    assert counts.admin_audit_logs == 112

    # All 12 counts overlap: a sequential implementation never exceeds 1 in
    # flight, so max_seen >= 2 proves concurrency.
    assert tracker.max_seen >= 2
