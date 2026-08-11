"""Unit tests for the ApiKeyService business logic (docs/05 §12)."""

import pytest
from backend.core.errors import ApiKeyNotFoundError
from backend.core.security import hash_api_key
from backend.models.api_key import API_KEY_PREFIX, API_KEY_STATUS_ACTIVE, API_KEY_STATUS_REVOKED
from backend.models.audit_log import AUDIT_API_KEY_CREATED, AUDIT_API_KEY_REVOKED

from tests.api_keys_helpers import build_api_keys_env, make_principal


async def test_create_api_key_returns_secret_once_and_stores_only_hash() -> None:
    env = build_api_keys_env()
    principal = make_principal()

    result = await env.service.create_api_key(
        principal=principal,
        name="Production",
        ip_address="1.2.3.4",
        user_agent="pytest",
    )

    assert result.api_key.tenant_id == principal.tenant_id
    assert result.api_key.name == "Production"
    assert result.api_key.status == API_KEY_STATUS_ACTIVE
    assert result.api_key.key_prefix == API_KEY_PREFIX
    # The raw secret is returned exactly once; the DB only holds its hash.
    assert result.raw_secret.startswith(API_KEY_PREFIX)
    stored = env.keys.keys[result.api_key.id]
    assert stored.hashed_secret == hash_api_key(result.raw_secret)
    assert stored.hashed_secret != result.raw_secret


async def test_create_api_key_audits_event() -> None:
    env = build_api_keys_env()
    principal = make_principal()

    await env.service.create_api_key(
        principal=principal,
        name="Staging",
        ip_address="1.2.3.4",
        user_agent="pytest",
    )

    assert env.audit.logs[-1].action == AUDIT_API_KEY_CREATED
    assert env.audit.logs[-1].tenant_id == principal.tenant_id
    assert env.audit.logs[-1].user_id == principal.user_id
    assert env.audit.logs[-1].ip_address == "1.2.3.4"


async def test_list_api_keys_returns_only_active_owned_keys() -> None:
    env = build_api_keys_env()
    principal = make_principal()
    first = await env.service.create_api_key(
        principal=principal, name="A", ip_address=None, user_agent=None
    )
    await env.service.create_api_key(
        principal=principal, name="B", ip_address=None, user_agent=None
    )
    # A foreign tenant's key must never leak into this tenant's listing.
    await env.service.create_api_key(
        principal=make_principal(tenant_id="tenant-b"),
        name="Foreign",
        ip_address=None,
        user_agent=None,
    )

    keys = await env.service.list_api_keys(principal.tenant_id)

    assert [key.name for key in keys] == ["B", "A"]
    assert first.api_key.id in {key.id for key in keys}
    assert env.keys.keys


async def test_revoke_api_key_soft_deletes_and_audits() -> None:
    env = build_api_keys_env()
    principal = make_principal()
    result = await env.service.create_api_key(
        principal=principal, name="A", ip_address="1.1.1.1", user_agent="t"
    )

    await env.service.revoke_api_key(
        principal=principal,
        key_id=result.api_key.id,
        ip_address="1.1.1.1",
        user_agent="t",
    )

    # The record persists (soft delete) but is no longer tenant-visible.
    assert env.keys.keys[result.api_key.id].status == API_KEY_STATUS_REVOKED
    assert await env.service.list_api_keys(principal.tenant_id) == []
    assert env.audit.logs[-1].action == AUDIT_API_KEY_REVOKED


async def test_revoke_api_key_missing_raises() -> None:
    env = build_api_keys_env()
    with pytest.raises(ApiKeyNotFoundError):
        await env.service.revoke_api_key(
            principal=make_principal(), key_id="missing", ip_address=None, user_agent=None
        )


async def test_revoke_api_key_is_tenant_scoped() -> None:
    env = build_api_keys_env()
    result = await env.service.create_api_key(
        principal=make_principal(tenant_id="tenant-a"),
        name="A",
        ip_address=None,
        user_agent=None,
    )

    # A different tenant must not revoke tenant-a's key.
    with pytest.raises(ApiKeyNotFoundError):
        await env.service.revoke_api_key(
            principal=make_principal(tenant_id="tenant-b"),
            key_id=result.api_key.id,
            ip_address=None,
            user_agent=None,
        )
    assert env.keys.keys[result.api_key.id].status == API_KEY_STATUS_ACTIVE
