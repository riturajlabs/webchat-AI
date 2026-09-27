"""Document data access (Protocol + MongoDB implementation).

`documents` stores one cleaned page per crawled URL. The unique
(tenant_id, website_id, url) index makes upserts idempotent: a re-crawl of the
same URL replaces the old content instead of duplicating it (incremental crawl).
"""

from typing import Any, Final, Protocol

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError

from backend.models.document import Document
from backend.models.knowledge_chunk import (
    KNOWLEDGE_STATUS_FAILED,
    KNOWLEDGE_STATUS_NONE,
    KNOWLEDGE_STATUS_PENDING,
    KNOWLEDGE_STATUS_PROCESSING,
    KNOWLEDGE_STATUS_RATE_LIMITED,
    KNOWLEDGE_STATUS_READY,
)


class DocumentRepository(Protocol):
    """Data access for the `documents` collection (tenant-scoped)."""

    async def upsert(self, document: Document) -> None: ...

    async def update_knowledge_if_current(
        self, document: Document, *, expected_checksum: str
    ) -> bool:
        """Persist knowledge state only if the document has not moved on.

        Returns ``True`` when the write was applied, ``False`` when it was
        refused because the document is no longer the one this execution read
        (see :func:`knowledge_cas_filter`). A refusal is a normal, expected
        outcome - it is how a superseded execution is prevented from rolling back
        newer authoritative state - not an error to raise.
        """
        ...

    async def count_by_website(
        self, tenant_id: str, website_id: str, *, source_type: str | None = None
    ) -> int: ...

    # Phase 13 billing: tenant-wide document count for the `max_documents`
    # plan limit (live count, not event tally).
    async def count_by_tenant(self, tenant_id: str, *, source_type: str | None = None) -> int: ...

    async def count_failed_by_website(self, tenant_id: str, website_id: str) -> int: ...

    async def count_non_terminal_by_website(self, tenant_id: str, website_id: str) -> int: ...

    async def all_checksums(
        self, tenant_id: str, website_id: str, *, source_type: str | None = None
    ) -> list[str]: ...

    async def find_by_id(self, tenant_id: str, document_id: str) -> Document | None: ...

    # Worker-side lookups: the document carries its tenant, so reads resolve
    # ownership from stored data (never from untrusted input).
    async def find_by_id_any(self, document_id: str) -> Document | None: ...

    async def find_by_file_checksum(
        self, tenant_id: str, website_id: str, file_checksum_sha256: str
    ) -> Document | None: ...

    async def list_by_website(
        self, tenant_id: str, website_id: str, *, source_type: str | None = None
    ) -> list[Document]: ...

    # Audit R-02: purge pages removed from the site (crawl reconciliation)
    # and drop the whole corpus when the parent website is deleted.
    async def delete_by_ids(self, tenant_id: str, document_ids: list[str]) -> int: ...

    async def delete_by_website(self, tenant_id: str, website_id: str) -> int: ...


class MongoDocumentRepository:
    """MongoDB-backed document repository (docs/05, Phase 4 ingestion)."""

    def __init__(self, db: AsyncIOMotorDatabase[Any]) -> None:
        self._collection = db["documents"]

    async def upsert(self, document: Document) -> None:
        query = {
            "tenant_id": document.tenant_id,
            "website_id": document.website_id,
            "url": document.url,
        }
        # `$set` never touches `_id` (Mongo forbids mutating it), while the
        # insert path keeps our application-generated `_id`.
        result = await self._collection.update_one(
            query, {"$set": update_payload(document)}, upsert=False
        )
        if result.matched_count > 0:
            return
        try:
            await self._collection.insert_one(document.to_doc())
        except DuplicateKeyError:
            # Concurrent insert raced on the unique (tenant, website, url)
            # index; the document already exists, so apply a plain update.
            await self._collection.update_one(
                query, {"$set": update_payload(document)}, upsert=False
            )

    async def update_knowledge_if_current(
        self, document: Document, *, expected_checksum: str
    ) -> bool:
        """Atomically write knowledge state if the document still matches.

        One ``update_one`` carrying both the precondition and the update, so the
        check and the write cannot be separated by another writer. ``matched_count``
        is the CAS result: 1 means applied, 0 means refused.
        """
        filter_doc = knowledge_cas_filter(
            document, expected_checksum=expected_checksum, status=document.knowledge_status
        )
        result = await self._collection.update_one(
            filter_doc,
            {"$set": knowledge_update_payload(document)},
            upsert=False,
        )
        return result.matched_count == 1

    @staticmethod
    def _build_source_filter(source_type: str | None) -> dict[str, Any]:
        if source_type is None:
            return {}
        if source_type == "website":
            # Legacy documents have no source_type field; treat missing as "website"
            return {"source_type": {"$ne": "file"}}
        return {"source_type": source_type}

    async def count_by_website(
        self, tenant_id: str, website_id: str, *, source_type: str | None = None
    ) -> int:
        query: dict[str, Any] = {"tenant_id": tenant_id, "website_id": website_id}
        if source_type is not None:
            query.update(self._build_source_filter(source_type))
        return await self._collection.count_documents(query)

    async def count_by_tenant(self, tenant_id: str, *, source_type: str | None = None) -> int:
        query: dict[str, Any] = {"tenant_id": tenant_id}
        if source_type is not None:
            query.update(self._build_source_filter(source_type))
        return await self._collection.count_documents(query)

    async def count_failed_by_website(self, tenant_id: str, website_id: str) -> int:
        return await self._collection.count_documents(
            {
                "tenant_id": tenant_id,
                "website_id": website_id,
                "knowledge_status": KNOWLEDGE_STATUS_FAILED,
            }
        )

    async def count_non_terminal_by_website(self, tenant_id: str, website_id: str) -> int:
        """Documents not yet in a terminal knowledge state (pending/processing/
        rate-limited-and-awaiting-retry). Rate-limited docs remain non-terminal:
        they are queued for a deferred retry, not permanently failed."""
        return await self._collection.count_documents(
            {
                "tenant_id": tenant_id,
                "website_id": website_id,
                "knowledge_status": {
                    "$in": [
                        KNOWLEDGE_STATUS_NONE,
                        KNOWLEDGE_STATUS_PENDING,
                        KNOWLEDGE_STATUS_PROCESSING,
                        KNOWLEDGE_STATUS_RATE_LIMITED,
                    ],
                },
            }
        )

    async def all_checksums(
        self, tenant_id: str, website_id: str, *, source_type: str | None = None
    ) -> list[str]:
        query: dict[str, Any] = {"tenant_id": tenant_id, "website_id": website_id}
        if source_type is not None:
            query.update(self._build_source_filter(source_type))
        cursor = self._collection.find(
            query,
            projection={"checksum": 1, "_id": 0},
        )
        return [str(doc["checksum"]) async for doc in cursor]

    async def find_by_id(self, tenant_id: str, document_id: str) -> Document | None:
        doc = await self._collection.find_one({"_id": document_id, "tenant_id": tenant_id})
        return Document.from_doc(doc) if doc is not None else None

    async def find_by_id_any(self, document_id: str) -> Document | None:
        doc = await self._collection.find_one({"_id": document_id})
        return Document.from_doc(doc) if doc is not None else None

    async def find_by_file_checksum(
        self, tenant_id: str, website_id: str, file_checksum_sha256: str
    ) -> Document | None:
        doc = await self._collection.find_one(
            {
                "tenant_id": tenant_id,
                "website_id": website_id,
                "file_checksum_sha256": file_checksum_sha256,
            }
        )
        return Document.from_doc(doc) if doc is not None else None

    async def list_by_website(
        self, tenant_id: str, website_id: str, *, source_type: str | None = None
    ) -> list[Document]:
        query: dict[str, Any] = {"tenant_id": tenant_id, "website_id": website_id}
        if source_type is not None:
            query.update(self._build_source_filter(source_type))
        cursor = self._collection.find(query)
        return [Document.from_doc(doc) async for doc in cursor]

    async def delete_by_ids(self, tenant_id: str, document_ids: list[str]) -> int:
        if not document_ids:
            return 0
        result = await self._collection.delete_many(
            {"tenant_id": tenant_id, "_id": {"$in": document_ids}}
        )
        return int(result.deleted_count)

    async def delete_by_website(self, tenant_id: str, website_id: str) -> int:
        result = await self._collection.delete_many(
            {"tenant_id": tenant_id, "website_id": website_id}
        )
        return int(result.deleted_count)


def update_payload(document: Document) -> dict[str, Any]:
    """`$set` payload for a document update (never mutates the `_id` field).

    MongoDB rejects an update that rewrites `_id`, so the application-generated
    id is stripped here while `Document.to_doc()` keeps it for inserts.
    """
    payload = document.to_doc()
    payload.pop("_id", None)
    return payload


#: The document fields a *knowledge* write is allowed to touch. A knowledge
#: pass computes embeddings for content it read earlier; it has no business
#: rewriting the source `content`/`checksum` it was derived from. Restricting the
#: `$set` to this list is what makes a stale knowledge write harmless even if the
#: guard below were somehow bypassed: the worst it could do is roll back
#: knowledge bookkeeping, never the source of truth for the document.
KNOWLEDGE_WRITE_FIELDS: Final[tuple[str, ...]] = (
    "knowledge_status",
    "knowledge_checksum",
    "knowledge_chunks",
    "knowledge_processed_at",
    "knowledge_retry_count",
    "knowledge_last_attempt_at",
    "knowledge_failure_reason",
    "updated_at",
)


def knowledge_update_payload(document: Document) -> dict[str, Any]:
    """`$set` payload containing only knowledge-state fields (never `_id`)."""
    doc = document.to_doc()
    return {field: doc[field] for field in KNOWLEDGE_WRITE_FIELDS if field in doc}


def knowledge_cas_filter(
    document: Document, *, expected_checksum: str, status: str
) -> dict[str, Any]:
    """Build the single atomic filter guarding one knowledge write.

    Phase 17B.1 (Blocker B). ``upsert`` is a whole-document replace with no
    precondition, so an execution holding a stale ``Document`` snapshot could
    overwrite a newer run's authoritative ``knowledge_checksum``/``knowledge_status``
    - and, because ``update_payload`` carries the entire document, the source
    ``content``/``checksum`` too. Two guards, both expressed in existing domain
    fields, combined into ONE ``update_one`` (no read-then-write, so no TOCTOU):

    1. **Source identity** - ``checksum == expected_checksum``, the content this
       pass read. If the document was re-crawled in the meantime the stored
       checksum has moved on and this write is refused, because embedding the old
       content and stamping its checksum onto new content is wrong.

    2. **Knowledge-state monotonicity** - a *non-ready* write (processing,
       failed, rate-limited) is refused when the row already records a completed
       embed **of this same source**. Without it, a slow failure record could
       overwrite a success that has already stored its chunks, leaving the
       document permanently marked failed while its chunks sit in the vector
       store. A *ready* write is not subject to this guard: re-recording the same
       success is idempotent and must stay allowed so it can still repair
       bookkeeping such as a chunk count that was reset out of band.

    ``status`` is the knowledge status this write intends to store, which is what
    decides whether guard 2 applies.
    """
    filter_doc: dict[str, Any] = {
        "tenant_id": document.tenant_id,
        "website_id": document.website_id,
        "url": document.url,
        "checksum": expected_checksum,
    }
    if status != KNOWLEDGE_STATUS_READY:
        filter_doc["$nor"] = [
            {
                "knowledge_status": KNOWLEDGE_STATUS_READY,
                "knowledge_checksum": expected_checksum,
            }
        ]
    return filter_doc
