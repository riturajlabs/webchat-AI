"""Tests for the documents repository payload logic (Phase 4 incremental crawl).

Regression: `MongoDocumentRepository.upsert` previously wrote the document's
`_id` inside `$set`, so re-crawling an existing URL failed with
"Performing an update on the path '_id' would modify the immutable field
'_id'". The update payload must never contain `_id`, while the insert payload
must keep the application-generated id.
"""

from backend.models.document import Document
from backend.repositories.document_repository import update_payload


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
