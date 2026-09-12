"""Mongo-backed crawl-job repository fences (FIND-02).

Exercises the *production* `MongoCrawlJobRepository` (and the website
`update_if_crawl_owner` fence) against a minimal in-memory Mongo collection
stub that mirrors the unique partial index `(tenant_id, website_id, active)`
and `find_one_and_update` semantics. This keeps the fences under test without
requiring a live MongoDB / mongomock dependency.
"""

from typing import Any

import pytest
from backend.core.errors import CrawlConflictError
from backend.core.security import utcnow
from backend.models.crawl_job import (
    CRAWL_STATUS_COMPLETED,
    CRAWL_STATUS_FAILED,
    CrawlJob,
)
from backend.models.website import (
    WEBSITE_STATUS_DELETED,
    WEBSITE_STATUS_READY,
    Website,
)
from backend.repositories.crawl_job_repository import MongoCrawlJobRepository
from backend.repositories.website_repository import MongoWebsiteRepository
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError


class _Cursor:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs
        self._offset = 0
        self._limit: int | None = None

    def sort(self, *args: Any, **kwargs: Any) -> "_Cursor":
        return self

    def skip(self, count: int) -> "_Cursor":
        self._offset = count
        return self

    def limit(self, count: int) -> "_Cursor":
        self._limit = count
        return self

    def __aiter__(self):
        async def gen():
            end = None if self._limit is None else self._offset + self._limit
            for raw in self._docs[self._offset : end]:
                yield dict(raw)

        return gen()


class _ReplaceResult:
    def __init__(self, matched_count: int) -> None:
        self.matched_count = matched_count
        self.modified_count = matched_count


class _DeleteResult:
    def __init__(self, deleted_count: int) -> None:
        self.deleted_count = deleted_count


def _matches(filter_doc: dict[str, Any], doc: dict[str, Any]) -> bool:
    for key, expected in filter_doc.items():
        if isinstance(expected, dict):
            if "$in" in expected and doc.get(key) not in expected["$in"]:
                return False
            if "$ne" in expected and doc.get(key) == expected["$ne"]:
                return False
            continue
        if doc.get(key) != expected:
            return False
    return True


class _FakeMongoCollection:
    """Minimal async Mongo collection modelling the FIND-02 index + operators."""

    def __init__(self) -> None:
        self._docs: list[dict[str, Any]] = []

    @property
    def documents(self) -> list[dict[str, Any]]:
        return [dict(raw) for raw in self._docs]

    async def insert_one(self, document: dict[str, Any]) -> object:
        for other in self._docs:
            if (
                document.get("active")
                and other.get("active")
                and document.get("tenant_id") == other.get("tenant_id")
                and document.get("website_id") == other.get("website_id")
            ):
                raise DuplicateKeyError(
                    f"E11000 duplicate key active|{document['tenant_id']}|{document['website_id']}"
                )
        self._docs.append(dict(document))
        return object()

    async def find_one(self, filter_doc: dict[str, Any], **_: Any) -> dict[str, Any] | None:
        for raw in self._docs:
            if _matches(filter_doc, raw):
                return dict(raw)
        return None

    async def replace_one(
        self, filter_doc: dict[str, Any], document: dict[str, Any]
    ) -> _ReplaceResult:
        for i, raw in enumerate(self._docs):
            if _matches(filter_doc, raw):
                self._docs[i] = dict(document)
                return _ReplaceResult(matched_count=1)
        return _ReplaceResult(matched_count=0)

    async def find_one_and_update(
        self,
        filter_doc: dict[str, Any],
        update: dict[str, Any],
        *,
        return_document: int | None = None,
    ) -> dict[str, Any] | None:
        for i, raw in enumerate(self._docs):
            if not _matches(filter_doc, raw):
                continue
            before = dict(raw)
            after = dict(raw)
            for key, value in (update.get("$set") or {}).items():
                after[key] = value
            self._docs[i] = after
            if return_document == ReturnDocument.BEFORE:
                return before
            return after
        return None

    async def count_documents(self, filter_doc: dict[str, Any]) -> int:
        return sum(1 for raw in self._docs if _matches(filter_doc, raw))

    async def delete_many(self, filter_doc: dict[str, Any]) -> _DeleteResult:
        before = len(self._docs)
        self._docs = [raw for raw in self._docs if not _matches(filter_doc, raw)]
        return _DeleteResult(deleted_count=before - len(self._docs))

    def find(self, filter_doc: dict[str, Any]) -> _Cursor:
        return _Cursor([raw for raw in self._docs if _matches(filter_doc, raw)])


class _FakeDb:
    def __init__(self) -> None:
        self._collections: dict[str, _FakeMongoCollection] = {}

    def __getitem__(self, name: str) -> _FakeMongoCollection:
        return self._collections.setdefault(name, _FakeMongoCollection())


@pytest.fixture
def repos() -> tuple[MongoCrawlJobRepository, MongoWebsiteRepository, _FakeDb]:
    db = _FakeDb()
    return MongoCrawlJobRepository(db), MongoWebsiteRepository(db), db


async def test_create_conflict_translates_duplicate_key(repos) -> None:
    jobs, _, _ = repos
    job = CrawlJob.new(tenant_id="tenant-a", website_id="w1")
    await jobs.create(job)

    with pytest.raises(CrawlConflictError):
        await jobs.create(CrawlJob.new(tenant_id="tenant-a", website_id="w1"))


async def test_create_allows_second_job_once_fence_released(repos) -> None:
    jobs, _, _ = repos
    first = CrawlJob.new(tenant_id="tenant-a", website_id="w1")
    await jobs.create(first)
    await jobs.finish_if_active(
        first.id, "tenant-a", terminal_status=CRAWL_STATUS_COMPLETED, completed_at=utcnow()
    )

    await jobs.create(CrawlJob.new(tenant_id="tenant-a", website_id="w1"))


async def test_create_allows_same_website_id_under_different_tenants(repos) -> None:
    jobs, _, db = repos
    await jobs.create(CrawlJob.new(tenant_id="tenant-a", website_id="w1"))
    await jobs.create(CrawlJob.new(tenant_id="tenant-b", website_id="w1"))
    assert len(db["crawl_jobs"].documents) == 2


async def test_finish_if_active_is_true_exactly_once(repos) -> None:
    jobs, _, _ = repos
    job = CrawlJob.new(tenant_id="tenant-a", website_id="w1")
    await jobs.create(job)
    assert job.to_doc()["active"] is True

    assert (
        await jobs.finish_if_active(
            job.id,
            "tenant-a",
            terminal_status=CRAWL_STATUS_COMPLETED,
            completed_at=utcnow(),
            pages_completed=5,
        )
        is True
    )
    stored = await jobs.find_by_id_any(job.id)
    assert stored is not None
    assert stored.status == CRAWL_STATUS_COMPLETED
    assert stored.active is False
    assert stored.pages_completed == 5
    assert stored.completed_at is not None

    assert (
        await jobs.finish_if_active(job.id, "tenant-a", terminal_status=CRAWL_STATUS_FAILED)
        is False
    )
    reloaded = await jobs.find_by_id_any(job.id)
    assert reloaded is not None
    assert reloaded.status == CRAWL_STATUS_COMPLETED
    assert reloaded.pages_completed == 5


async def test_finish_if_active_never_matches_terminal_status(repos) -> None:
    jobs, _, _ = repos
    job = CrawlJob.new(tenant_id="tenant-a", website_id="w1")
    job.status = CRAWL_STATUS_FAILED
    job.active = False
    await jobs.create(job)

    assert (
        await jobs.finish_if_active(job.id, "tenant-a", terminal_status=CRAWL_STATUS_FAILED)
        is False
    )
    assert (await jobs.find_by_id_any(job.id)) is not None


async def test_finish_if_active_is_tenant_scoped(repos) -> None:
    jobs, _, _ = repos
    job = CrawlJob.new(tenant_id="tenant-a", website_id="w1")
    await jobs.create(job)

    assert (
        await jobs.finish_if_active(job.id, "other-tenant", terminal_status=CRAWL_STATUS_FAILED)
        is False
    )
    stored = await jobs.find_by_id_any(job.id)
    assert stored is not None
    assert stored.active is True


async def test_finish_if_active_updates_completed_at_and_updated_at(repos) -> None:
    jobs, _, _ = repos
    job = CrawlJob.new(tenant_id="tenant-a", website_id="w1")
    await jobs.create(job)
    completed_at = utcnow()

    await jobs.finish_if_active(
        job.id, "tenant-a", terminal_status=CRAWL_STATUS_COMPLETED, completed_at=completed_at
    )
    stored = await jobs.find_by_id_any(job.id)
    assert stored is not None
    assert stored.completed_at == completed_at
    assert stored.updated_at is not None


async def test_website_owner_fence_matches_only_current_owner(repos) -> None:
    _, websites, _ = repos
    website = Website.new(tenant_id="tenant-a", name="Acme", url="https://acme.example/")
    website.crawl_job_id = "job-1"
    await websites.create(website)

    new_state = website.model_copy(update={"status": WEBSITE_STATUS_READY})

    ok = await websites.update_if_crawl_owner("tenant-a", website.id, "job-1", new_state)
    assert ok is True

    stale = website.model_copy(update={"status": WEBSITE_STATUS_READY})
    ok = await websites.update_if_crawl_owner("tenant-a", website.id, "stale-job", stale)
    assert ok is False


async def test_website_owner_fence_blocks_wrong_tenant_and_deleted(repos) -> None:
    _, websites, _ = repos
    website = Website.new(tenant_id="tenant-a", name="Acme", url="https://acme.example/")
    website.crawl_job_id = "job-1"
    await websites.create(website)

    new_state = website.model_copy(update={"status": WEBSITE_STATUS_READY})
    ok = await websites.update_if_crawl_owner("tenant-b", website.id, "job-1", new_state)
    assert ok is False

    deleted = website.model_copy(update={"status": WEBSITE_STATUS_DELETED, "deleted": True})
    ok = await websites.update_if_crawl_owner("tenant-a", website.id, "job-1", deleted)
    assert ok is True

    resurrection = deleted.model_copy(update={"status": WEBSITE_STATUS_READY, "deleted": False})
    ok = await websites.update_if_crawl_owner("tenant-a", website.id, "job-1", resurrection)
    assert ok is False


async def test_website_owner_fence_preserves_owner_after_mismatch(repos) -> None:
    _, websites, _ = repos
    website = Website.new(tenant_id="tenant-a", name="Acme", url="https://acme.example/")
    website.crawl_job_id = "job-1"
    await websites.create(website)

    newer = website.model_copy(update={"crawl_job_id": "job-2", "status": WEBSITE_STATUS_READY})
    await websites.update_if_crawl_owner("tenant-a", website.id, "job-1", newer)

    older = website.model_copy(update={"status": WEBSITE_STATUS_READY})
    ok = await websites.update_if_crawl_owner("tenant-a", website.id, "job-1", older)
    assert ok is False
    stored = await websites.find_by_id_any(website.id)
    assert stored is not None
    assert stored.crawl_job_id == "job-2"
