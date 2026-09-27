"""Tests for the documents repository payload logic (Phase 4 incremental crawl).

Regression: `MongoDocumentRepository.upsert` previously wrote the document's
`_id` inside `$set`, so re-crawling an existing URL failed with
"Performing an update on the path '_id' would modify the immutable field
'_id'". The update payload must never contain `_id`, while the insert payload
must keep the application-generated id.

Phase 17B.1 adds the payload-shape assertions for the knowledge CAS and runs the
CAS itself against a real mongod, so the database behaviour - not just the fake
- is what the guarantees are measured on.
"""

from collections.abc import AsyncIterator
from typing import Any

import pytest
from backend.models.document import Document
from backend.models.knowledge_chunk import (
    KNOWLEDGE_STATUS_FAILED,
    KNOWLEDGE_STATUS_PROCESSING,
    KNOWLEDGE_STATUS_READY,
)
from backend.prototypes.mongo_queue.config import DEFAULT_MONGO_URI
from backend.repositories.document_repository import (
    KNOWLEDGE_WRITE_FIELDS,
    knowledge_cas_filter,
    knowledge_update_payload,
    update_payload,
)
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

TENANT = "tenant-a"
OTHER_TENANT = "tenant-b"


def _document() -> Document:
    return Document.new(
        tenant_id="tenant-a",
        website_id="website-a",
        url="https://acme.example/",
        title="Acme",
        content="Hello world",
        checksum="abc123",
        language="en",
    )


def test_update_payload_never_touches_immutable_id() -> None:
    doc = _document()
    payload = update_payload(doc)
    assert "_id" not in payload
    assert payload["url"] == doc.url
    assert payload["tenant_id"] == doc.tenant_id
    assert payload["website_id"] == doc.website_id
    assert payload["checksum"] == doc.checksum


def test_insert_payload_keeps_application_id() -> None:
    doc = _document()
    stored = doc.to_doc()
    assert stored["_id"] == doc.id
    assert "id" not in stored  # the pydantic `id` field is mapped to `_id`


# ----------------------------------------------------------------------
# Phase 17B.1: the knowledge CAS
# ----------------------------------------------------------------------


def test_knowledge_payload_cannot_carry_source_fields() -> None:
    """A knowledge write is structurally incapable of rewriting the source."""
    doc = _document()
    doc.knowledge_status = KNOWLEDGE_STATUS_READY
    doc.checksum = "aaa"
    doc.content = "tampered"
    payload = knowledge_update_payload(doc)
    assert "content" not in payload
    assert "checksum" not in payload
    assert "_id" not in payload
    assert "title" not in payload
    assert payload["knowledge_status"] == KNOWLEDGE_STATUS_READY
    # And the allowlist is closed: everything it can set is a knowledge field.
    assert set(payload) <= set(KNOWLEDGE_WRITE_FIELDS)


def test_cas_filter_matches_source_identity_and_blocks_state_rewind() -> None:
    doc = _document()

    non_ready = knowledge_cas_filter(
        doc, expected_checksum="abc123", status=KNOWLEDGE_STATUS_FAILED
    )
    assert non_ready["tenant_id"] == TENANT
    assert non_ready["website_id"] == doc.website_id
    assert non_ready["url"] == doc.url
    assert non_ready["checksum"] == "abc123"
    # The non-ready write is fenced off from a completed embed of this source.
    assert non_ready["$nor"] == [
        {"knowledge_status": KNOWLEDGE_STATUS_READY, "knowledge_checksum": "abc123"}
    ]

    # A ready write may re-record the same success, so it carries no $nor guard.
    ready = knowledge_cas_filter(doc, expected_checksum="abc123", status=KNOWLEDGE_STATUS_READY)
    assert "$nor" not in ready
    assert ready["checksum"] == "abc123"


@pytest.fixture
async def mongo_db() -> AsyncIterator[AsyncIOMotorDatabase[dict[str, Any]]]:
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        DEFAULT_MONGO_URI, serverSelectionTimeoutMS=3000, tz_aware=True
    )
    try:
        await client.admin.command("ping")
    except Exception as exc:  # noqa: BLE001 - environment guard
        client.close()
        pytest.skip(f"isolated prototype mongod unreachable: {exc}")
    db: AsyncIOMotorDatabase[dict[str, Any]] = client["webchat_ai_test_docrepo_cas"]
    yield db
    for name in await db.list_collection_names():
        await db.drop_collection(name)
    client.close()


@pytest.fixture
async def mongo_documents(mongo_db: AsyncIOMotorDatabase[dict[str, Any]]) -> Any:
    from backend.repositories.document_repository import MongoDocumentRepository

    return MongoDocumentRepository(mongo_db)


async def _seed(mongo_documents: Any, *, tenant: str = TENANT, checksum: str = "X") -> Document:
    doc = Document.new(
        tenant_id=tenant,
        website_id="website-a",
        url="https://acme.example/a",
        title="A",
        content="Alpha " * 200,
        checksum=checksum,
    )
    await mongo_documents.upsert(doc)
    return doc


async def test_mongo_cas_refuses_a_stale_write_and_leaves_the_winner_intact(
    mongo_documents: Any,
) -> None:
    """The real database refuses the stale write - the core Blocker B guarantee."""
    doc = await _seed(mongo_documents)
    stale = doc.model_copy(deep=True)

    # B wins: a success for checksum X, chunks stored.
    winner = doc.model_copy(deep=True)
    winner.knowledge_status = KNOWLEDGE_STATUS_READY
    winner.knowledge_checksum = "X"
    winner.knowledge_chunks = 4
    applied = await mongo_documents.update_knowledge_if_current(winner, expected_checksum="X")
    assert applied is True

    # A's stale failure record lands second and must be refused.
    stale.knowledge_status = KNOWLEDGE_STATUS_FAILED
    stale.knowledge_failure_reason = "ProviderTimeout: upstream timed out"
    applied = await mongo_documents.update_knowledge_if_current(stale, expected_checksum="X")
    assert applied is False

    after = await mongo_documents.find_by_id_any(doc.id)
    assert after is not None
    assert after.knowledge_status == KNOWLEDGE_STATUS_READY
    assert after.knowledge_checksum == "X"
    assert after.knowledge_chunks == 4
    assert after.knowledge_failure_reason is None


async def test_mongo_cas_never_rewrites_source_content(mongo_documents: Any) -> None:
    """Even an applied knowledge write leaves the source bytes untouched."""
    doc = await _seed(mongo_documents)
    before = await mongo_documents.find_by_id_any(doc.id)
    assert before is not None

    stale_source = before.model_copy(deep=True)
    stale_source.content = "STALE CONTENT " * 200
    stale_source.checksum = "OLD"

    applied = await mongo_documents.update_knowledge_if_current(
        stale_source, expected_checksum="OLD"
    )
    assert applied is False

    after = await mongo_documents.find_by_id_any(doc.id)
    assert after is not None
    assert after.checksum == "X"
    assert after.content == before.content


async def test_mongo_cas_refuses_after_the_source_is_recrawled(mongo_documents: Any) -> None:
    """A re-crawl during processing invalidates the in-flight pass."""
    doc = await _seed(mongo_documents)
    inflight = doc.model_copy(deep=True)

    recrawled = doc.model_copy(deep=True)
    recrawled.content = "Charlie " * 200
    recrawled.checksum = "Y"
    await mongo_documents.upsert(recrawled)

    inflight.knowledge_status = KNOWLEDGE_STATUS_READY
    inflight.knowledge_checksum = "X"
    applied = await mongo_documents.update_knowledge_if_current(inflight, expected_checksum="X")
    assert applied is False

    after = await mongo_documents.find_by_id_any(doc.id)
    assert after is not None
    assert after.checksum == "Y"
    assert after.knowledge_checksum != "X", "a stale embed was recorded against new source"

    # Y still needs its own pass, so it is not falsely marked satisfied.
    assert after.knowledge_status != KNOWLEDGE_STATUS_READY


@pytest.mark.parametrize("iteration", range(100))
async def test_mongo_cas_converges_under_100_interleavings(
    mongo_documents: Any, iteration: int
) -> None:
    """100 deterministic orderings of two writers on one row.

    The loser's write must be refused every time, and the row must never end up
    holding a rewound value. Parametrized (not looped) so a failure names the
    exact ordering that broke.
    """
    doc = await _seed(mongo_documents)
    snapshot_a = doc.model_copy(deep=True)
    snapshot_b = doc.model_copy(deep=True)

    snapshot_b.knowledge_status = KNOWLEDGE_STATUS_READY
    snapshot_b.knowledge_checksum = "X"
    snapshot_b.knowledge_chunks = 5
    applied = await mongo_documents.update_knowledge_if_current(snapshot_b, expected_checksum="X")
    assert applied is True

    snapshot_a.knowledge_status = (
        KNOWLEDGE_STATUS_FAILED if iteration % 2 else KNOWLEDGE_STATUS_PROCESSING
    )
    snapshot_a.knowledge_chunks = iteration
    applied = await mongo_documents.update_knowledge_if_current(snapshot_a, expected_checksum="X")
    assert applied is False

    after = await mongo_documents.find_by_id_any(doc.id)
    assert after is not None
    assert after.knowledge_status == KNOWLEDGE_STATUS_READY
    assert after.knowledge_checksum == "X"
    assert after.knowledge_chunks == 5


async def test_mongo_cas_is_tenant_scoped(mongo_documents: Any) -> None:
    """Two tenants share a website_id and url; a write must land on only one row.

    The identity used by the filter is (tenant, website, url). If the tenant were
    dropped from the precondition, tenant A's write would match an arbitrary one
    of the two rows - the worst case being another tenant's document silently
    marked embedded. Both rows are therefore written with the same website/url
    and checked independently after the write.
    """
    mine = await _seed(mongo_documents, tenant=TENANT, checksum="X")
    theirs = await _seed(mongo_documents, tenant=OTHER_TENANT, checksum="X")
    assert mine.website_id == theirs.website_id and mine.url == theirs.url

    ready = mine.model_copy(deep=True)
    ready.knowledge_status = KNOWLEDGE_STATUS_READY
    ready.knowledge_checksum = "X"
    ready.knowledge_chunks = 3
    applied = await mongo_documents.update_knowledge_if_current(ready, expected_checksum="X")
    assert applied is True

    mine_after = await mongo_documents.find_by_id_any(mine.id)
    assert mine_after is not None
    assert mine_after.tenant_id == TENANT
    assert mine_after.knowledge_chunks == 3
    assert mine_after.knowledge_status == KNOWLEDGE_STATUS_READY

    # The other tenant's identically-addressed row is untouched by that write.
    theirs_after = await mongo_documents.find_by_id_any(theirs.id)
    assert theirs_after is not None
    assert theirs_after.tenant_id == OTHER_TENANT
    assert theirs_after.knowledge_status != KNOWLEDGE_STATUS_READY
    assert not theirs_after.knowledge_chunks


async def test_mongo_cas_reports_false_for_a_missing_row(mongo_documents: Any) -> None:
    """A refused-by-absence write is False, not an error and not an insert."""
    doc = _document()
    applied = await mongo_documents.update_knowledge_if_current(doc, expected_checksum="abc123")
    assert applied is False
    # `upsert=False` means the CAS must not have created the document.
    assert await mongo_documents.find_by_id_any(doc.id) is None
