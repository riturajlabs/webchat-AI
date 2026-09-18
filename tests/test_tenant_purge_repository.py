"""Tests for `MongoTenantPurgeRepository` account-deletion cascade.

The purge performs an application-level cascade because MongoDB has no SQL
foreign-key CASCADE: deleting a tenant must remove every tenant-scoped
collection plus the tenant and its users. A fake DB records each `delete_many`
so we can assert the exact purge surface without a running Mongo.
"""

import pytest
from backend.core.errors import StorageError
from backend.repositories.tenant_purge_repository import (
    _TENANT_COLLECTIONS,
    MongoTenantPurgeRepository,
)

from tests.fakes import FakeStorageService


class _FakeCollection:
    def __init__(self, name: str, deletes: list[dict], docs: list[dict] | None = None) -> None:
        self.name = name
        self.deletes = deletes
        self.docs = docs if docs is not None else []

    def find(self, query: dict, projection: dict | None = None):
        class _AsyncCursor:
            def __init__(self, items: list[dict]) -> None:
                self._items = items

            def __aiter__(self):
                self._iter = iter(self._items)
                return self

            async def __anext__(self) -> dict:
                try:
                    return next(self._iter)
                except StopIteration:
                    raise StopAsyncIteration from None

        matched = []
        for doc in self.docs:
            matches = True
            for k, v in query.items():
                if k == "storage_key" and isinstance(v, dict) and "$nin" in v:
                    if doc.get("storage_key") in v["$nin"]:
                        matches = False
                        break
                elif doc.get(k) != v:
                    matches = False
                    break
            if matches:
                matched.append(doc)
        return _AsyncCursor(matched)

    async def delete_many(self, query: dict) -> object:
        self.deletes.append({"collection": self.name, "query": query})
        return object()


class _FakeDb:
    def __init__(self, documents: list[dict] | None = None) -> None:
        self.deletes: list[dict] = []
        self.collections = {
            name: _FakeCollection(
                name, self.deletes, docs=documents if name == "documents" else None
            )
            for name in _COLLECTIONS
        }

    def __getitem__(self, name: str) -> _FakeCollection:
        return self.collections[name]


_COLLECTIONS = (
    *_TENANT_COLLECTIONS,
    "tenants",
    "users",
)


@pytest.mark.asyncio
async def test_purge_tenant_deletes_every_tenant_scoped_collection() -> None:
    db = _FakeDb()
    repo = MongoTenantPurgeRepository(db)
    tenant_id = "tenant-a"

    await repo.purge_tenant(tenant_id)

    cleared = {entry["collection"] for entry in db.deletes}
    # Every tenant-scoped collection plus tenants and users is cleared.
    assert cleared == set(_COLLECTIONS)
    # Each tenant-scoped purge is filtered by tenant_id.
    for entry in db.deletes:
        if entry["collection"] in _TENANT_COLLECTIONS:
            assert entry["query"]["tenant_id"] == tenant_id
        elif entry["collection"] == "users":
            assert entry["query"]["tenant_id"] == tenant_id
        else:
            assert entry["query"] == {"_id": tenant_id}


@pytest.mark.asyncio
async def test_purge_tenant_removes_uploaded_file_storage_and_preserves_cross_tenant() -> None:
    """FU-01 (TEST B & TEST C): Tenant purge cascades to GridFS storage for uploaded files only.

    - Tenant A's file document storage is deleted.
    - Tenant B's storage remains untouched.
    - Website documents without storage do not trigger storage deletion.
    """
    storage = FakeStorageService()
    key_a = await storage.upload(
        tenant_id="tenant-a",
        website_id="site-a",
        document_id="doc-a",
        filename="file_a.pdf",
        content=b"content-a",
        mime_type="application/pdf",
    )
    key_b = await storage.upload(
        tenant_id="tenant-b",
        website_id="site-b",
        document_id="doc-b",
        filename="file_b.pdf",
        content=b"content-b",
        mime_type="application/pdf",
    )

    documents_data = [
        {"_id": "doc-a", "tenant_id": "tenant-a", "source_type": "file", "storage_key": key_a},
        {
            "_id": "doc-a-web",
            "tenant_id": "tenant-a",
            "source_type": "website",
            "storage_key": None,
        },
        {"_id": "doc-b", "tenant_id": "tenant-b", "source_type": "file", "storage_key": key_b},
    ]
    db = _FakeDb(documents=documents_data)
    repo = MongoTenantPurgeRepository(db, storage=storage)

    await repo.purge_tenant("tenant-a")

    # Tenant A's file storage was deleted
    assert ("tenant-a", key_a) not in storage.files
    # Tenant B's storage remains intact (cross-tenant safety)
    assert ("tenant-b", key_b) in storage.files
    # All tenant-scoped collections for tenant-a were deleted
    cleared = {entry["collection"] for entry in db.deletes}
    assert cleared == set(_COLLECTIONS)
    for entry in db.deletes:
        if entry["collection"] in _TENANT_COLLECTIONS:
            assert entry["query"]["tenant_id"] == "tenant-a"


@pytest.mark.asyncio
async def test_purge_tenant_aborts_on_storage_failure() -> None:
    """FU-01 failure semantics: If storage deletion fails, collections are not purged."""
    storage = FakeStorageService()
    # File record in Mongo documents, but missing from storage backend -> delete returns False
    documents_data = [
        {
            "_id": "doc-a",
            "tenant_id": "tenant-a",
            "source_type": "file",
            "storage_key": "missing-key",
        },
    ]
    db = _FakeDb(documents=documents_data)
    repo = MongoTenantPurgeRepository(db, storage=storage)

    with pytest.raises(StorageError) as exc_info:
        await repo.purge_tenant("tenant-a")

    assert "Failed to delete stored files for tenant tenant-a" in str(exc_info.value)
    # Crucial: NO collections were purged because failure occurred first
    assert db.deletes == []


@pytest.mark.asyncio
async def test_purge_user_sessions_targets_refresh_tokens_by_user() -> None:
    db = _FakeDb()
    repo = MongoTenantPurgeRepository(db)

    await repo.purge_user_sessions("user-1")

    assert db.deletes == [{"collection": "refresh_tokens", "query": {"user_id": "user-1"}}]
