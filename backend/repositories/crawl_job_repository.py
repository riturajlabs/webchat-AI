"""Crawl job data access (Protocol + MongoDB implementation).

Every query is scoped by `tenant_id` (00-AI-Development-Rules §7) so a tenant
can never observe another tenant's crawl history. The Phase 12.5 admin surface
(`list_any`/`count_any`) is deliberately unscoped - it backs the global crawl
queue monitor in ADR-006 and is reachable only via `role=admin`.
"""

from datetime import datetime
from typing import Any, Protocol

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import DESCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError

from backend.core.errors import CrawlConflictError
from backend.core.security import utcnow
from backend.models.crawl_job import (
    CRAWL_ACTIVE_STATUSES,
    CrawlJob,
)


class CrawlJobRepository(Protocol):
    """Data access for the `crawl_jobs` collection (tenant-scoped)."""

    async def create(self, job: CrawlJob) -> None: ...

    async def find_by_id(self, tenant_id: str, job_id: str) -> CrawlJob | None: ...

    async def find_active_for_website(self, tenant_id: str, website_id: str) -> CrawlJob | None: ...

    async def update(self, job: CrawlJob) -> None: ...

    async def finish_if_active(
        self,
        job_id: str,
        tenant_id: str,
        *,
        terminal_status: str,
        completed_at: datetime | None = None,
        **fields: Any,
    ) -> bool: ...

    # Phase 12.5 admin surface (ADR-006 §Crawl Monitoring).
    async def list_any(
        self,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CrawlJob]: ...

    async def count_any(self, *, status: str | None = None) -> int: ...

    async def count_active_for_tenant(self, tenant_id: str) -> int: ...

    async def delete_by_website(self, tenant_id: str, website_id: str) -> int: ...


class MongoCrawlJobRepository:
    """MongoDB-backed crawl job repository (docs/05 §8, ADR-002)."""

    def __init__(self, db: AsyncIOMotorDatabase[Any]) -> None:
        self._collection = db["crawl_jobs"]

    async def create(self, job: CrawlJob) -> None:
        try:
            await self._collection.insert_one(job.to_doc())
        except DuplicateKeyError as exc:
            # FIND-02: the unique partial index (tenant_id, website_id, active)
            # is the atomic single-flight gate - a second active job row for the
            # same website is a *conflict*, not a database fault. Only genuine
            # uniqueness violations are translated; real Mongo errors propagate.
            raise CrawlConflictError("A crawl is already in progress for this website.") from exc

    async def find_by_id(self, tenant_id: str, job_id: str) -> CrawlJob | None:
        doc = await self._collection.find_one({"_id": job_id, "tenant_id": tenant_id})
        return CrawlJob.from_doc(doc) if doc else None

    async def find_by_id_any(self, job_id: str) -> CrawlJob | None:
        """Worker-internal lookup without tenant scoping.

        The worker is addressed by job id alone (ARQ payloads carry no tenant
        claims); the tenant is then read from the document itself.
        """
        doc = await self._collection.find_one({"_id": job_id})
        return CrawlJob.from_doc(doc) if doc else None

    async def find_active_for_website(self, tenant_id: str, website_id: str) -> CrawlJob | None:
        """Return the most recent non-terminal job for a website, if any."""
        doc = await self._collection.find_one(
            {
                "tenant_id": tenant_id,
                "website_id": website_id,
                "status": {"$in": sorted(CRAWL_ACTIVE_STATUSES)},
            },
            sort=[("created_at", -1)],
        )
        return CrawlJob.from_doc(doc) if doc else None

    async def update(self, job: CrawlJob) -> None:
        await self._collection.replace_one(
            {"_id": job.id, "tenant_id": job.tenant_id}, job.to_doc()
        )

    async def finish_if_active(
        self,
        job_id: str,
        tenant_id: str,
        *,
        terminal_status: str,
        completed_at: datetime | None = None,
        **fields: Any,
    ) -> bool:
        """Atomically transition an active crawl job to a terminal state.

        Fenced on `_id`, `tenant_id` and `status in ACTIVE`, the update matches
        at most one active row. Returning whether the transition actually
        happened makes this the terminal *ownership token*: the single attempt
        that gets `True` owns all side effects (audit, usage, website write,
        knowledge enqueue). A stale, already-terminal, foreign or missing job
        returns `False` and no terminal fields are overwritten.
        """
        now = utcnow()
        result = await self._collection.find_one_and_update(
            {
                "_id": job_id,
                "tenant_id": tenant_id,
                "status": {"$in": sorted(CRAWL_ACTIVE_STATUSES)},
            },
            {
                "$set": {
                    **fields,
                    "status": terminal_status,
                    "active": False,
                    "completed_at": completed_at,
                    "updated_at": now,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        return result is not None

    async def list_any(
        self,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CrawlJob]:
        query: dict[str, Any] = {}
        if status is not None:
            query["status"] = status
        cursor = (
            self._collection.find(query).sort("created_at", DESCENDING).skip(offset).limit(limit)
        )
        return [CrawlJob.from_doc(doc) async for doc in cursor]

    async def count_any(self, *, status: str | None = None) -> int:
        query: dict[str, Any] = {}
        if status is not None:
            query["status"] = status
        return await self._collection.count_documents(query)

    async def count_active_for_tenant(self, tenant_id: str) -> int:
        return await self._collection.count_documents(
            {
                "tenant_id": tenant_id,
                "status": {"$in": sorted(CRAWL_ACTIVE_STATUSES)},
            }
        )

    async def delete_by_website(self, tenant_id: str, website_id: str) -> int:
        result = await self._collection.delete_many(
            {"tenant_id": tenant_id, "website_id": website_id}
        )
        return result.deleted_count
