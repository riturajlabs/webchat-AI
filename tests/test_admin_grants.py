"""Service-level tests for Phase 16 manual plan grants (`AdminService`).

Covers the grant/revoke lifecycle against the fake repositories shared with the
admin API: complementary `admin_grant` subscriptions override paid plans and
`tenants.plan`, re-grants are idempotent, revokes fall back to the paid plan,
audit trails capture every change, and effective-plan resolution powers the
tenant/user read surface without leaking into revenue accounting
(`count_active`/`list_paid` exclude grants).
"""

from datetime import datetime, timedelta

import pytest
from backend.core.errors import (
    ForbiddenError,
    InvalidGrantError,
    PlanNotFoundError,
    PlanNotPurchasableError,
    TenantNotFoundError,
)
from backend.core.security import utcnow
from backend.models.audit_log import AUDIT_PLAN_GRANTED, AUDIT_PLAN_REVOKED
from backend.models.plan import PLAN_ENTERPRISE, PLAN_FREE, PLAN_PLUS, PLAN_PRO
from backend.models.subscription import (
    SUBSCRIPTION_SOURCE_ADMIN_GRANT,
    SUBSCRIPTION_SOURCE_PAYMENT,
    SUBSCRIPTION_STATUS_ACTIVE,
    SUBSCRIPTION_STATUS_CANCELLED,
    Subscription,
)
from backend.models.tenant import Tenant
from backend.services.admin import (
    ENTITLEMENT_SOURCE_ADMIN_GRANT,
    ENTITLEMENT_SOURCE_SUBSCRIPTION,
    ENTITLEMENT_SOURCE_TENANT_PLAN,
)

from tests.admin_helpers import build_admin_env

# Relative to the real clock: `AdminService` validates expirations against
# `utcnow()`, so grant dates must be in the future when the test runs.
NOW = utcnow()


def _seed_tenant(admin_env, *, tenant_id: str = "tenant-a", plan: str = PLAN_FREE) -> Tenant:
    tenant = Tenant.new(company_name="Acme")
    tenant.id = tenant_id
    tenant.plan = plan
    tenant.created_at = NOW
    tenant.updated_at = NOW
    admin_env.tenants.tenants[tenant.id] = tenant
    return tenant


async def _seed_paid_subscription(
    admin_env,
    *,
    tenant_id: str,
    plan_id: str = PLAN_PRO,
    amount_cents: int = 4900,
    start: datetime | None = None,
) -> Subscription:
    start = start or NOW - timedelta(days=10)
    subscription = Subscription.new(
        tenant_id=tenant_id,
        plan_id=plan_id,
        source=SUBSCRIPTION_SOURCE_PAYMENT,
        payment_provider="razorpay",
        payment_id=f"pay_{tenant_id}_{plan_id}",
        start_date=start,
        end_date=start + timedelta(days=30),
        amount_cents=amount_cents,
        currency="USD",
    )
    await admin_env.subscriptions.create(subscription)
    return subscription


def _active_grant(admin_env) -> Subscription:
    return next(
        subscription
        for subscription in admin_env.subscriptions.subscriptions
        if subscription.source == SUBSCRIPTION_SOURCE_ADMIN_GRANT
    )


@pytest.fixture
def env():
    return build_admin_env()


# ------------------------------------------------------------------- grants


async def test_grant_creates_active_admin_grant_subscription(env) -> None:
    tenant = _seed_tenant(env)
    result = await env.admin.grant_plan(
        tenant_id=tenant.id,
        plan_id=PLAN_PRO,
        admin_user_id="root-1",
        admin_tenant_id="admin-workspace",
        expires_at=None,
        reason="Onboarding partner",
        ip_address=None,
        user_agent=None,
    )

    assert result.changed is True
    grant = _active_grant(env)
    assert grant.tenant_id == tenant.id
    assert grant.plan_id == PLAN_PRO
    assert grant.status == SUBSCRIPTION_STATUS_ACTIVE
    assert grant.source == SUBSCRIPTION_SOURCE_ADMIN_GRANT
    assert grant.payment_provider == "admin"
    assert grant.payment_id is None
    assert grant.amount_cents == 0
    assert grant.currency == "USD"
    assert grant.granted_by == "root-1"
    assert grant.granted_at is not None
    assert grant.grant_reason == "Onboarding partner"
    assert grant.end_date is None

    # The response reflects the newly-resolved entitlement.
    assert result.entitlement.effective_plan == PLAN_PRO
    assert result.entitlement.source == ENTITLEMENT_SOURCE_ADMIN_GRANT


async def test_grant_is_idempotent_for_identical_regrant(env) -> None:
    tenant = _seed_tenant(env)
    expires_at = NOW + timedelta(days=90)
    first = await env.admin.grant_plan(
        tenant_id=tenant.id,
        plan_id=PLAN_PRO,
        admin_user_id="root-1",
        admin_tenant_id="admin-workspace",
        expires_at=expires_at,
        reason="Onboarding partner",
        ip_address=None,
        user_agent=None,
    )
    second = await env.admin.grant_plan(
        tenant_id=tenant.id,
        plan_id=PLAN_PRO,
        admin_user_id="root-1",
        admin_tenant_id="admin-workspace",
        expires_at=expires_at,
        reason="Onboarding partner",
        ip_address=None,
        user_agent=None,
    )

    assert first.changed is True
    assert second.changed is False
    assert (
        len(
            [
                s
                for s in env.subscriptions.subscriptions
                if s.source == SUBSCRIPTION_SOURCE_ADMIN_GRANT
            ]
        )
        == 1
    )
    # A no-op re-grant writes no audit entry.
    assert len([log for log in env.auth.audit.logs if log.action == AUDIT_PLAN_GRANTED]) == 1
    assert len([log for log in env.admin_audit.logs if log.action == "PLAN_GRANTED"]) == 1


async def test_changed_regrant_updates_single_active_grant(env) -> None:
    tenant = _seed_tenant(env)
    await env.admin.grant_plan(
        tenant_id=tenant.id,
        plan_id=PLAN_PRO,
        admin_user_id="root-1",
        admin_tenant_id="admin-workspace",
        expires_at=None,
        reason="old",
        ip_address=None,
        user_agent=None,
    )
    await env.admin.grant_plan(
        tenant_id=tenant.id,
        plan_id=PLAN_ENTERPRISE,
        admin_user_id="root-1",
        admin_tenant_id="admin-workspace",
        expires_at=NOW + timedelta(days=7),
        reason="updated",
        ip_address=None,
        user_agent=None,
    )

    grants = [
        s for s in env.subscriptions.subscriptions if s.source == SUBSCRIPTION_SOURCE_ADMIN_GRANT
    ]
    assert len(grants) == 1
    assert grants[0].plan_id == PLAN_ENTERPRISE
    assert grants[0].end_date == NOW + timedelta(days=7)
    assert grants[0].grant_reason == "updated"
    assert len([log for log in env.auth.audit.logs if log.action == AUDIT_PLAN_GRANTED]) == 2


async def test_grant_writes_both_audit_trails_with_reason(env) -> None:
    tenant = _seed_tenant(env)
    await env.admin.grant_plan(
        tenant_id=tenant.id,
        plan_id=PLAN_PRO,
        admin_user_id="root-1",
        admin_tenant_id="admin-workspace",
        expires_at=None,
        reason="Referral deal",
        ip_address="10.0.0.1",
        user_agent="test-agent",
    )

    shared = next(log for log in env.auth.audit.logs if log.action == AUDIT_PLAN_GRANTED)
    assert shared.tenant_id == tenant.id
    assert shared.user_id == "root-1"
    assert shared.ip_address == "10.0.0.1"
    assert shared.grant_reason == "Referral deal"

    admin_log = next(log for log in env.admin_audit.logs if log.action == "PLAN_GRANTED")
    assert admin_log.actor_user_id == "root-1"
    assert admin_log.tenant_id == tenant.id
    assert admin_log.plan_id == PLAN_PRO
    assert admin_log.grant_reason == "Referral deal"


async def test_grant_free_plan_is_rejected(env) -> None:
    tenant = _seed_tenant(env)
    with pytest.raises(PlanNotPurchasableError) as exc_info:
        await env.admin.grant_plan(
            tenant_id=tenant.id,
            plan_id=PLAN_FREE,
            admin_user_id="root-1",
            admin_tenant_id="admin-workspace",
            expires_at=None,
            reason=None,
            ip_address=None,
            user_agent=None,
        )
    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "PLAN_NOT_PURCHASABLE"
    assert env.subscriptions.subscriptions == []


async def test_grant_unknown_plan_raises_plan_not_found(env) -> None:
    tenant = _seed_tenant(env)
    with pytest.raises(PlanNotFoundError):
        await env.admin.grant_plan(
            tenant_id=tenant.id,
            plan_id="gold",
            admin_user_id="root-1",
            admin_tenant_id="admin-workspace",
            expires_at=None,
            reason=None,
            ip_address=None,
            user_agent=None,
        )


async def test_grant_rejects_past_expiration(env) -> None:
    tenant = _seed_tenant(env)
    with pytest.raises(InvalidGrantError) as exc_info:
        await env.admin.grant_plan(
            tenant_id=tenant.id,
            plan_id=PLAN_PRO,
            admin_user_id="root-1",
            admin_tenant_id="admin-workspace",
            expires_at=NOW - timedelta(minutes=1),
            reason=None,
            ip_address=None,
            user_agent=None,
        )
    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "INVALID_GRANT"


async def test_grant_rejects_own_tenant(env) -> None:
    tenant = _seed_tenant(env, tenant_id="admin-workspace")
    with pytest.raises(ForbiddenError):
        await env.admin.grant_plan(
            tenant_id=tenant.id,
            plan_id=PLAN_PRO,
            admin_user_id="root-1",
            admin_tenant_id="admin-workspace",
            expires_at=None,
            reason=None,
            ip_address=None,
            user_agent=None,
        )


async def test_grant_unknown_tenant_raises_not_found(env) -> None:
    with pytest.raises(TenantNotFoundError):
        await env.admin.grant_plan(
            tenant_id="missing",
            plan_id=PLAN_PRO,
            admin_user_id="root-1",
            admin_tenant_id="admin-workspace",
            expires_at=None,
            reason=None,
            ip_address=None,
            user_agent=None,
        )


# ------------------------------------------------------------ precedence


async def test_active_grant_beats_paid_subscription(env) -> None:
    tenant = _seed_tenant(env, plan=PLAN_FREE)
    await _seed_paid_subscription(env, tenant_id=tenant.id, plan_id=PLAN_PRO)
    await env.admin.grant_plan(
        tenant_id=tenant.id,
        plan_id=PLAN_ENTERPRISE,
        admin_user_id="root-1",
        admin_tenant_id="admin-workspace",
        expires_at=None,
        reason=None,
        ip_address=None,
        user_agent=None,
    )

    result = await env.admin.resolve_entitlements([tenant])
    assert result[tenant.id].effective_plan == PLAN_ENTERPRISE
    assert result[tenant.id].source == ENTITLEMENT_SOURCE_ADMIN_GRANT


async def test_expired_grant_does_not_override_paid_plan(env) -> None:
    tenant = _seed_tenant(env)
    paid = await _seed_paid_subscription(env, tenant_id=tenant.id, plan_id=PLAN_PLUS)
    grant = Subscription.new(
        tenant_id=tenant.id,
        plan_id=PLAN_PRO,
        source=SUBSCRIPTION_SOURCE_ADMIN_GRANT,
        payment_provider="admin",
        start_date=NOW - timedelta(days=30),
        end_date=NOW - timedelta(days=1),
        amount_cents=0,
        currency="USD",
        granted_by="root-1",
        granted_at=NOW - timedelta(days=30),
    )
    await env.subscriptions.create(grant)

    current = await env.admin.resolve_entitlements([tenant])

    # The grant lapsed; the paid subscription supplies the effective plan.
    assert current[tenant.id].effective_plan == paid.plan_id
    assert current[tenant.id].source == ENTITLEMENT_SOURCE_SUBSCRIPTION


async def test_resolve_entitlements_falls_back_to_tenant_plan(env) -> None:
    tenant = _seed_tenant(env, plan=PLAN_PLUS)
    entitlement = (await env.admin.resolve_entitlements([tenant]))[tenant.id]
    assert entitlement.effective_plan == PLAN_PLUS
    assert entitlement.source == ENTITLEMENT_SOURCE_TENANT_PLAN


async def test_resolve_entitlements_prefers_newest_paid_subscription(env) -> None:
    tenant = _seed_tenant(env)
    await _seed_paid_subscription(env, tenant_id=tenant.id, plan_id=PLAN_PLUS)
    latest = await _seed_paid_subscription(env, tenant_id=tenant.id, plan_id=PLAN_PRO, start=NOW)

    entitlement = (await env.admin.resolve_entitlements([tenant]))[tenant.id]

    assert entitlement.effective_plan == latest.plan_id
    assert entitlement.source == ENTITLEMENT_SOURCE_SUBSCRIPTION


async def test_resolve_entitlements_for_users_maps_by_tenant(env) -> None:
    tenant_a = _seed_tenant(env, tenant_id="tenant-a")
    tenant_b = _seed_tenant(env, tenant_id="tenant-b", plan=PLAN_PLUS)
    await _seed_paid_subscription(env, tenant_id=tenant_b.id, plan_id=PLAN_PRO)
    grant_sub = Subscription.new(
        tenant_id=tenant_a.id,
        plan_id=PLAN_ENTERPRISE,
        source=SUBSCRIPTION_SOURCE_ADMIN_GRANT,
        payment_provider="admin",
        amount_cents=0,
        currency="USD",
        granted_by="root-1",
    )
    await env.subscriptions.create(grant_sub)

    class _FakeUser:
        def __init__(self, tenant_id: str) -> None:
            self.tenant_id = tenant_id

    users = [_FakeUser("tenant-a"), _FakeUser("tenant-b"), _FakeUser("orphan")]
    entitlements = await env.admin.resolve_entitlements_for_users(users)  # type: ignore[arg-type]

    assert entitlements["tenant-a"].effective_plan == PLAN_ENTERPRISE
    assert entitlements["tenant-a"].source == ENTITLEMENT_SOURCE_ADMIN_GRANT
    assert entitlements["tenant-b"].effective_plan == PLAN_PRO
    assert entitlements["tenant-b"].source == ENTITLEMENT_SOURCE_SUBSCRIPTION
    # Tenant row missing → free tenant-plan fallback.
    assert entitlements["orphan"].effective_plan == PLAN_FREE
    assert entitlements["orphan"].source == ENTITLEMENT_SOURCE_TENANT_PLAN


# ----------------------------------------------------------------- revoke


async def test_revoke_restores_paid_subscription(env) -> None:
    tenant = _seed_tenant(env)
    await _seed_paid_subscription(env, tenant_id=tenant.id, plan_id=PLAN_PRO)
    await env.admin.grant_plan(
        tenant_id=tenant.id,
        plan_id=PLAN_ENTERPRISE,
        admin_user_id="root-1",
        admin_tenant_id="admin-workspace",
        expires_at=None,
        reason=None,
        ip_address=None,
        user_agent=None,
    )

    result = await env.admin.revoke_plan(
        tenant_id=tenant.id,
        admin_user_id="root-1",
        admin_tenant_id="admin-workspace",
        ip_address=None,
        user_agent=None,
    )

    assert result.changed is True
    grant = _active_grant(env)
    assert grant.status == SUBSCRIPTION_STATUS_CANCELLED
    assert result.entitlement.effective_plan == PLAN_PRO
    assert result.entitlement.source == ENTITLEMENT_SOURCE_SUBSCRIPTION
    assert len([log for log in env.auth.audit.logs if log.action == AUDIT_PLAN_REVOKED]) == 1
    assert len([log for log in env.admin_audit.logs if log.action == "PLAN_REVOKED"]) == 1


async def test_revoke_with_non_grant_subscription_is_noop(env) -> None:
    tenant = _seed_tenant(env)
    await _seed_paid_subscription(env, tenant_id=tenant.id)

    result = await env.admin.revoke_plan(
        tenant_id=tenant.id,
        admin_user_id="root-1",
        admin_tenant_id="admin-workspace",
        ip_address=None,
        user_agent=None,
    )

    assert result.changed is False
    assert len(env.admin_audit.logs) == 0
    assert env.subscriptions.subscriptions[0].status == SUBSCRIPTION_STATUS_ACTIVE


async def test_revoke_restores_tenant_plan_without_paid_subscription(env) -> None:
    tenant = _seed_tenant(env, plan=PLAN_PLUS)
    await env.admin.grant_plan(
        tenant_id=tenant.id,
        plan_id=PLAN_PRO,
        admin_user_id="root-1",
        admin_tenant_id="admin-workspace",
        expires_at=None,
        reason=None,
        ip_address=None,
        user_agent=None,
    )

    result = await env.admin.revoke_plan(
        tenant_id=tenant.id,
        admin_user_id="root-1",
        admin_tenant_id="admin-workspace",
        ip_address=None,
        user_agent=None,
    )

    assert result.changed is True
    assert result.entitlement.effective_plan == PLAN_PLUS
    assert result.entitlement.source == ENTITLEMENT_SOURCE_TENANT_PLAN


async def test_revoke_rejects_own_tenant(env) -> None:
    tenant = _seed_tenant(env, tenant_id="admin-workspace")
    with pytest.raises(ForbiddenError):
        await env.admin.revoke_plan(
            tenant_id=tenant.id,
            admin_user_id="root-1",
            admin_tenant_id="admin-workspace",
            ip_address=None,
            user_agent=None,
        )


# -------------------------------------------------- revenue bulletproofing


async def test_count_active_excludes_admin_grants(env) -> None:
    tenant = _seed_tenant(env)
    await _seed_paid_subscription(env, tenant_id=tenant.id)
    await env.admin.grant_plan(
        tenant_id=tenant.id,
        plan_id=PLAN_ENTERPRISE,
        admin_user_id="root-1",
        admin_tenant_id="admin-workspace",
        expires_at=None,
        reason=None,
        ip_address=None,
        user_agent=None,
    )

    # The paid sub counts; the zero-amount admin grant does not inflate MRR.
    assert await env.subscriptions.count_active(now=NOW) == 1


async def test_find_active_by_tenant_prefers_grant_over_newer_payment(env) -> None:
    tenant = _seed_tenant(env)
    await _seed_paid_subscription(env, tenant_id=tenant.id, plan_id=PLAN_PRO)
    grant = Subscription.new(
        tenant_id=tenant.id,
        plan_id=PLAN_ENTERPRISE,
        source=SUBSCRIPTION_SOURCE_ADMIN_GRANT,
        payment_provider="admin",
        start_date=NOW + timedelta(minutes=1),
        amount_cents=0,
        currency="USD",
        granted_by="root-1",
        granted_at=NOW + timedelta(minutes=1),
    )
    await env.subscriptions.create(grant)

    current = await env.subscriptions.find_active_by_tenant(tenant.id, now=NOW + timedelta(days=1))

    assert current == grant
    assert current.source == SUBSCRIPTION_SOURCE_ADMIN_GRANT
