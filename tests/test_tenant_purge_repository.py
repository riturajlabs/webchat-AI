"""Tests for `MongoTenantPurgeRepository` account-deletion cascade.

The purge performs an application-level cascade because MongoDB has no SQL
foreign-key CASCADE: deleting a tenant must remove every tenant-scoped
collection plus the tenant and its users. A fake DB records each `delete_many`
so we can assert the exact purge surface without a running Mongo.
"""

import pytest
from backend.repositories.tenant_purge_repository import (
    _TENANT_COLLECTIONS,
    MongoTenantPurgeRepository,
)


class _FakeCollection:
    def __init__(self, name: str, deletes: list[dict]) -> None:
        self.name = name
        self.deletes = deletes

    async def delete_many(self, query: dict) -> object:
        self.deletes.append({"collection": self.name, "query": query})
        return object()


class _FakeDb:
    def __init__(self) -> None:
        self.deletes: list[dict] = []
        self.collections = {name: _FakeCollection(name, self.deletes) for name in _COLLECTIONS}

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
async def test_purge_user_sessions_targets_refresh_tokens_by_user() -> None:
    db = _FakeDb()
    repo = MongoTenantPurgeRepository(db)

    await repo.purge_user_sessions("user-1")

    assert db.deletes == [{"collection": "refresh_tokens", "query": {"user_id": "user-1"}}]
