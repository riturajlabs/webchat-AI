"""End-to-end HTTP tests for the /api/admin endpoints using fakes.

Phase 12.5 (ADR-006): the admin router guards every route with `role=admin`,
mutations write audit logs through the shared audit system, and platform-wide
reads never leak to tenant-scoped owner users. The AdminService is backed by
the same fake repositories as the auth service, so registered accounts are the
tenants/users the admin manages.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import pytest
from backend.api.deps import get_admin_service, get_auth_service
from backend.core.config import get_settings
from backend.core.rbac import ROLE_SUPER_ADMIN
from backend.main import create_app
from backend.models.crawl_job import CrawlJob
from backend.models.subscription import Subscription
from backend.models.website import Website
from fastapi.testclient import TestClient

from tests.admin_helpers import build_admin_env
from tests.http_helpers import register_verified_account

_ACCOUNT_SEQ = 0


def _next_email() -> str:
    global _ACCOUNT_SEQ
    _ACCOUNT_SEQ += 1
    return f"user{_ACCOUNT_SEQ}@example.com"


@pytest.fixture
def client(monkeypatch):
    """A TestClient whose auth + admin services share in-memory fakes."""
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    get_settings.cache_clear()
    admin_env = build_admin_env()
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: admin_env.auth.service
    app.dependency_overrides[get_admin_service] = lambda: admin_env.admin
    with TestClient(app) as test_client:
        yield test_client, admin_env
    get_settings.cache_clear()


def _register(test_client: TestClient, *, name: str = "Alice") -> dict:
    body = register_verified_account(test_client, name=name, email=_next_email())
    return {
        "access_token": body["access_token"],
        "user_id": body["user"]["id"],
        "tenant_id": body["user"]["tenant_id"],
        "headers": {"Authorization": f"Bearer {body['access_token']}"},
    }


def _register_admin(test_client: TestClient, admin_env, *, name: str = "Root") -> dict:
    """Register an account and promote it to the platform `super_admin` role.

    `AuthService.authenticate` re-resolves the role from the live membership
    on every request, so mutating the member after registration is enough for
    the access token to carry `super_admin`.
    """
    account = _register(test_client, name=name)
    member = next(
        member
        for member in admin_env.auth.members.members.values()
        if member.user_id == account["user_id"]
    )
    member.role = ROLE_SUPER_ADMIN
    return account


async def _create_subscription(
    admin_env,
    *,
    tenant_id: str,
    amount_cents: int,
    status: str = "active",
    start: datetime | None = None,
) -> Subscription:
    subscription = Subscription.new(
        tenant_id=tenant_id,
        plan_id="pro",
        status=status,
        payment_provider="mock",
        payment_id=f"pay_{amount_cents}_{len(admin_env.subscriptions.subscriptions)}",
        start_date=start or datetime.now(UTC),
        amount_cents=amount_cents,
        currency="USD",
    )
    await admin_env.subscriptions.create(subscription)
    return subscription


def _seed_subscription(admin_env, **kwargs: Any) -> Subscription:
    return asyncio.run(_create_subscription(admin_env, **kwargs))


def _seed_job(admin_env, *, tenant_id: str, status: str = "completed") -> CrawlJob:
    job = CrawlJob.new(tenant_id=tenant_id, website_id="web-1")
    job.status = status
    await_created = job
    admin_env.crawl_jobs.jobs[job.id] = job
    return await_created


# -------------------------------------------------------------- authz (RBAC)


def test_admin_requires_authentication(client) -> None:
    test_client, _ = client
    for path in (
        "/api/admin/tenants",
        "/api/admin/tenants/t-1",
        "/api/admin/users",
        "/api/admin/stats",
        "/api/admin/crawl-jobs",
        "/api/admin/audit-logs",
        "/api/admin/overview",
        "/api/admin/usage",
        "/api/admin/revenue",
        "/api/admin/system-health",
        "/api/admin/audit",
    ):
        assert test_client.get(path).status_code == 401


def test_owner_cannot_access_admin_endpoints(client) -> None:
    test_client, _ = client
    headers = _register(test_client)["headers"]

    for method, path in (
        ("GET", "/api/admin/tenants"),
        ("GET", "/api/admin/stats"),
        ("GET", "/api/admin/crawl-jobs"),
        ("GET", "/api/admin/audit-logs"),
        ("GET", "/api/admin/users"),
        ("GET", "/api/admin/overview"),
        ("GET", "/api/admin/usage"),
        ("GET", "/api/admin/revenue"),
        ("GET", "/api/admin/system-health"),
        ("GET", "/api/admin/audit"),
    ):
        response = getattr(test_client, method.lower())(path, headers=headers)
        assert response.status_code == 403, path
        assert response.json()["error"]["code"] == "FORBIDDEN"

    owner_account = _register(test_client)
    response = test_client.patch(
        f"/api/admin/tenants/{owner_account['tenant_id']}",
        json={"status": "suspended"},
        headers=headers,
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_tenant_admin_role_cannot_access_admin_endpoints(client) -> None:
    """Phase 15 RBAC: tenant `admin` is below the platform `super_admin`."""
    test_client, admin_env = client
    account = _register(test_client)
    member = next(
        member
        for member in admin_env.auth.members.members.values()
        if member.user_id == account["user_id"]
    )
    member.role = "admin"

    for path in (
        "/api/admin/tenants",
        "/api/admin/stats",
        "/api/admin/overview",
        "/api/admin/revenue",
    ):
        response = test_client.get(path, headers=account["headers"])
        assert response.status_code == 403, path
        assert response.json()["error"]["code"] == "FORBIDDEN"


def test_admin_can_access_admin_endpoints(client) -> None:
    test_client, admin_env = client
    admin = _register_admin(test_client, admin_env)
    _register(test_client)

    response = test_client.get("/api/admin/tenants", headers=admin["headers"])
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2
    assert response.headers["X-Total-Count"] == "2"


# ------------------------------------------------------------------- tenants


def test_tenants_list_search_and_pagination(client) -> None:
    test_client, admin_env = client
    admin = _register_admin(test_client, admin_env, name="Root Inc")
    _register(test_client, name="Alpha Corp")
    _register(test_client, name="Beta Works")

    response = test_client.get(
        "/api/admin/tenants?search=alpha&page=1&per_page=10", headers=admin["headers"]
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["company_name"] == "Alpha Corp"

    response = test_client.get("/api/admin/tenants?page=1&per_page=2", headers=admin["headers"])
    assert response.status_code == 200
    assert len(response.json()["items"]) == 2
    assert response.json()["total"] == 3


async def test_tenant_detail_reports_websites_users_usage_status(client) -> None:
    test_client, admin_env = client
    admin = _register_admin(test_client, admin_env)
    target = _register(test_client, name="Target Co")
    tenant_id = target["tenant_id"]

    website = Website.new(tenant_id=tenant_id, name="Site", url="https://site.test")
    website.id = "web-1"
    await admin_env.websites.create(website)
    await admin_env.usage.increment(
        tenant_id=tenant_id,
        website_id="web-1",
        date=datetime.now(UTC).date().isoformat(),
        counters={"chats": 3, "messages": 9, "input_tokens": 100, "output_tokens": 50},
    )

    response = test_client.get(f"/api/admin/tenants/{tenant_id}", headers=admin["headers"])

    assert response.status_code == 200
    body = response.json()
    assert body["company_name"] == "Target Co"
    assert body["website_count"] == 1
    assert body["user_count"] == 1
    assert body["active_crawl_jobs"] == 0
    assert body["usage"] == {
        "conversations": 3,
        "messages": 9,
        "input_tokens": 100,
        "output_tokens": 50,
    }


def test_tenant_detail_not_found(client) -> None:
    test_client, admin_env = client
    admin = _register_admin(test_client, admin_env)

    response = test_client.get("/api/admin/tenants/nope", headers=admin["headers"])

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TENANT_NOT_FOUND"


def test_tenant_suspend_activate_and_audit(client) -> None:
    test_client, admin_env = client
    admin = _register_admin(test_client, admin_env)
    target = _register(test_client, name="Target Co")
    tenant_id = target["tenant_id"]

    response = test_client.patch(
        f"/api/admin/tenants/{tenant_id}", json={"status": "suspended"}, headers=admin["headers"]
    )
    assert response.status_code == 200
    assert response.json()["status"] == "suspended"
    assert admin_env.tenants.tenants[tenant_id].status == "suspended"

    response = test_client.patch(
        f"/api/admin/tenants/{tenant_id}", json={"status": "active"}, headers=admin["headers"]
    )
    assert response.status_code == 200
    assert response.json()["status"] == "active"

    actions = [log.action for log in admin_env.auth.audit.logs if log.user_id == admin["user_id"]]
    assert "TENANT_SUSPENDED" in actions
    assert "TENANT_ACTIVATED" in actions
    suspended_logs = [
        log
        for log in admin_env.auth.audit.logs
        if log.action == "TENANT_SUSPENDED" and log.tenant_id == tenant_id
    ]
    assert len(suspended_logs) == 1
    assert suspended_logs[0].user_id == admin["user_id"]


def test_tenant_plan_change(client) -> None:
    test_client, admin_env = client
    admin = _register_admin(test_client, admin_env)
    target = _register(test_client, name="Target Co")

    response = test_client.patch(
        f"/api/admin/tenants/{target['tenant_id']}",
        json={"plan": "pro"},
        headers=admin["headers"],
    )

    assert response.status_code == 200
    assert response.json()["plan"] == "pro"
    assert any(log.action == "TENANT_PLAN_CHANGED" for log in admin_env.auth.audit.logs)


def test_admin_cannot_suspend_own_tenant(client) -> None:
    test_client, admin_env = client
    admin = _register_admin(test_client, admin_env)

    response = test_client.patch(
        f"/api/admin/tenants/{admin['tenant_id']}",
        json={"status": "suspended"},
        headers=admin["headers"],
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


# --------------------------------------------------------------------- users


def test_users_list_search_and_status_filter(client) -> None:
    test_client, admin_env = client
    admin = _register_admin(test_client, admin_env, name="Root")
    bob = _register(test_client, name="Bob Smith")
    _register(test_client, name="Carol Jones")

    response = test_client.get(
        "/api/admin/users?search=bob&status=active", headers=admin["headers"]
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "Bob Smith"
    assert body["items"][0]["email"] == admin_env.users.users[bob["user_id"]].email
    assert all(item["status"] == "active" for item in body["items"])

    # No status filter returns everyone.
    response = test_client.get("/api/admin/users", headers=admin["headers"])
    assert response.json()["total"] == 3
    assert {item["name"] for item in response.json()["items"]} >= {
        "Root",
        "Bob Smith",
        "Carol Jones",
    }


def test_suspend_user_and_audit(client) -> None:
    test_client, admin_env = client
    admin = _register_admin(test_client, admin_env, name="Root")
    target = _register(test_client, name="Target Co")
    user_id = target["user_id"]

    response = test_client.post(
        f"/api/admin/tenants/{target['tenant_id']}/users/{user_id}/suspend",
        headers=admin["headers"],
    )

    assert response.status_code == 200
    assert response.json()["status"] == "suspended"
    assert admin_env.users.users[user_id].status == "suspended"
    suspended_logs = [
        log
        for log in admin_env.auth.audit.logs
        if log.action == "USER_SUSPENDED" and log.tenant_id == target["tenant_id"]
    ]
    assert len(suspended_logs) == 1
    assert suspended_logs[0].user_id == admin["user_id"]

    # Suspending again is a no-op (no duplicate audit event).
    response = test_client.post(
        f"/api/admin/tenants/{target['tenant_id']}/users/{user_id}/suspend",
        headers=admin["headers"],
    )
    assert response.status_code == 200
    assert len([log for log in admin_env.auth.audit.logs if log.action == "USER_SUSPENDED"]) == 1


def test_force_logout_revokes_refresh_tokens(client) -> None:
    test_client, admin_env = client
    admin = _register_admin(test_client, admin_env, name="Root")
    target = _register(test_client, name="Target Co")
    user_id = target["user_id"]

    active_tokens = [
        token
        for token in admin_env.auth.refresh_tokens.tokens.values()
        if token.user_id == user_id and token.revoked_at is None
    ]
    assert len(active_tokens) >= 1

    response = test_client.post(
        f"/api/admin/tenants/{target['tenant_id']}/users/{user_id}/force-logout",
        headers=admin["headers"],
    )

    assert response.status_code == 200
    assert all(
        token.revoked_at is not None
        for token in admin_env.auth.refresh_tokens.tokens.values()
        if token.user_id == user_id
    )
    assert any(
        log.action == "FORCE_LOGOUT"
        and log.user_id == admin["user_id"]
        and log.tenant_id == target["tenant_id"]
        for log in admin_env.auth.audit.logs
    )


def test_admin_cannot_suspend_or_force_logout_self(client) -> None:
    test_client, admin_env = client
    admin = _register_admin(test_client, admin_env, name="Root")

    response = test_client.post(
        f"/api/admin/tenants/{admin['tenant_id']}/users/{admin['user_id']}/suspend",
        headers=admin["headers"],
    )
    assert response.status_code == 403

    response = test_client.post(
        f"/api/admin/tenants/{admin['tenant_id']}/users/{admin['user_id']}/force-logout",
        headers=admin["headers"],
    )
    assert response.status_code == 403


def test_user_not_found_in_tenant(client) -> None:
    test_client, admin_env = client
    admin = _register_admin(test_client, admin_env, name="Root")
    target = _register(test_client, name="Target Co")

    response = test_client.post(
        f"/api/admin/tenants/{target['tenant_id']}/users/missing/suspend",
        headers=admin["headers"],
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "USER_NOT_FOUND"


# --------------------------------------------------------- platform reads


async def test_platform_stats_kpis(client) -> None:
    test_client, admin_env = client
    admin = _register_admin(test_client, admin_env, name="Root")
    tenant_a = _register(test_client, name="Alpha")
    tenant_b = _register(test_client, name="Beta")

    # Suspend Beta's tenant so KPI buckets are non-trivial.
    await admin_env.admin.update_tenant(
        tenant_id=tenant_b["tenant_id"],
        status="suspended",
        plan=None,
        admin_user_id=admin["user_id"],
        admin_tenant_id=admin["tenant_id"],
        ip_address=None,
        user_agent=None,
    )
    await admin_env.usage.increment(
        tenant_id=tenant_a["tenant_id"],
        website_id="web-1",
        date=datetime.now(UTC).date().isoformat(),
        counters={"chats": 5, "messages": 20, "input_tokens": 200, "output_tokens": 100},
    )
    _seed_job(admin_env, tenant_id=tenant_a["tenant_id"], status="running")
    _seed_job(admin_env, tenant_id=tenant_b["tenant_id"], status="failed")

    response = test_client.get("/api/admin/stats", headers=admin["headers"])

    assert response.status_code == 200
    body = response.json()
    assert body["tenants"] == {"total": 3, "active": 2, "suspended": 1}
    assert body["users"] == {"total": 3, "active": 3, "suspended": 0}
    assert body["usage"] == {
        "conversations": 5,
        "messages": 20,
        "input_tokens": 200,
        "output_tokens": 100,
        "total_tokens": 300,
    }
    assert body["crawl_jobs"] == {"total": 2, "active": 1, "failed": 1, "error_rate": 0.5}


def test_crawl_queue_response(client) -> None:
    test_client, admin_env = client
    admin = _register_admin(test_client, admin_env, name="Root")
    tenant_a = _register(test_client, name="Alpha")
    tenant_b = _register(test_client, name="Beta")
    job_a = _seed_job(admin_env, tenant_id=tenant_a["tenant_id"], status="running")
    _seed_job(admin_env, tenant_id=tenant_b["tenant_id"], status="failed")

    response = test_client.get("/api/admin/crawl-jobs", headers=admin["headers"])

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert {item["tenant_id"] for item in body["items"]} == {
        tenant_a["tenant_id"],
        tenant_b["tenant_id"],
    }

    response = test_client.get("/api/admin/crawl-jobs?status=running", headers=admin["headers"])
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["id"] == job_a.id


def test_audit_logs_viewer_and_filters(client) -> None:
    test_client, admin_env = client
    admin = _register_admin(test_client, admin_env, name="Root")
    target = _register(test_client, name="Target Co")

    response = test_client.get("/api/admin/audit-logs", headers=admin["headers"])

    assert response.status_code == 200
    assert response.json()["total"] >= 2  # one REGISTER per account (admin + target)

    response = test_client.get(
        f"/api/admin/audit-logs?tenant_id={target['tenant_id']}&action=REGISTER",
        headers=admin["headers"],
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["action"] == "REGISTER"
    assert body["items"][0]["tenant_id"] == target["tenant_id"]

    since = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    response = test_client.get(
        f"/api/admin/audit-logs?{urlencode({'since': since, 'user_id': target['user_id']})}",
        headers=admin["headers"],
    )
    assert response.status_code == 200
    assert all(item["user_id"] == target["user_id"] for item in response.json()["items"])


# ----------------------------------------------------------- validation


def test_admin_pagination_and_filter_validation(client) -> None:
    test_client, admin_env = client
    admin = _register_admin(test_client, admin_env, name="Root")
    headers = admin["headers"]

    assert test_client.get("/api/admin/tenants?page=0", headers=headers).status_code == 422
    assert test_client.get("/api/admin/tenants?per_page=101", headers=headers).status_code == 422
    assert (
        test_client.get("/api/admin/tenants?search=" + "x" * 101, headers=headers).status_code
        == 422
    )
    assert test_client.get("/api/admin/tenants?status=evil", headers=headers).status_code == 422
    assert test_client.get("/api/admin/users?status=evil", headers=headers).status_code == 422
    assert test_client.get("/api/admin/crawl-jobs?status=evil", headers=headers).status_code == 422
    assert (
        test_client.get("/api/admin/audit-logs?since=garbage", headers=headers).status_code == 422
    )
    assert test_client.get("/api/admin/audit?since=garbage", headers=headers).status_code == 422


def test_admin_tenant_update_requires_known_status(client) -> None:
    test_client, admin_env = client
    admin = _register_admin(test_client, admin_env, name="Root")
    target = _register(test_client, name="Target Co")

    response = test_client.patch(
        f"/api/admin/tenants/{target['tenant_id']}",
        json={"status": "deleted"},
        headers=admin["headers"],
    )

    assert response.status_code == 422


# ------------------------------------------------ Phase 15: tenant operations


def test_tenants_list_plan_and_status_filters(client) -> None:
    test_client, admin_env = client
    admin = _register_admin(test_client, admin_env, name="Root Inc")
    alpha = _register(test_client, name="Alpha Corp")
    beta = _register(test_client, name="Beta Works")
    admin_env.tenants.tenants[beta["tenant_id"]].plan = "pro"
    admin_env.tenants.tenants[alpha["tenant_id"]].status = "suspended"

    response = test_client.get("/api/admin/tenants?plan=pro", headers=admin["headers"])
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["company_name"] == "Beta Works"

    response = test_client.get("/api/admin/tenants?status=suspended", headers=admin["headers"])
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["company_name"] == "Alpha Corp"

    response = test_client.get(
        "/api/admin/tenants?plan=free&status=active", headers=admin["headers"]
    )
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["company_name"] == "Root Inc"


def test_tenant_suspend_activate_endpoints(client) -> None:
    test_client, admin_env = client
    admin = _register_admin(test_client, admin_env)
    target = _register(test_client, name="Target Co")
    tenant_id = target["tenant_id"]

    response = test_client.post(
        f"/api/admin/tenants/{tenant_id}/suspend", headers=admin["headers"]
    )
    assert response.status_code == 200
    assert response.json()["status"] == "suspended"
    assert admin_env.tenants.tenants[tenant_id].status == "suspended"
    assert any(log.action == "TENANT_SUSPENDED" for log in admin_env.auth.audit.logs)
    # The dedicated admin trail records the operator (actor), not the tenant.
    assert any(
        log.action == "TENANT_SUSPENDED"
        and log.actor_user_id == admin["user_id"]
        and log.tenant_id == tenant_id
        for log in admin_env.admin_audit.logs
    )

    # Idempotent: a second suspend writes no new audit event.
    response = test_client.post(
        f"/api/admin/tenants/{tenant_id}/suspend", headers=admin["headers"]
    )
    assert response.status_code == 200
    assert (
        len([log for log in admin_env.admin_audit.logs if log.action == "TENANT_SUSPENDED"]) == 1
    )

    response = test_client.post(
        f"/api/admin/tenants/{tenant_id}/activate", headers=admin["headers"]
    )
    assert response.status_code == 200
    assert response.json()["status"] == "active"
    assert any(
        log.action == "TENANT_ACTIVATED" and log.actor_user_id == admin["user_id"]
        for log in admin_env.admin_audit.logs
    )


def test_tenant_plan_change_endpoint(client) -> None:
    test_client, admin_env = client
    admin = _register_admin(test_client, admin_env)
    target = _register(test_client, name="Target Co")
    tenant_id = target["tenant_id"]

    response = test_client.post(
        f"/api/admin/tenants/{tenant_id}/plan", json={"plan": "pro"}, headers=admin["headers"]
    )
    assert response.status_code == 200
    assert response.json()["plan"] == "pro"
    assert any(log.action == "TENANT_PLAN_CHANGED" for log in admin_env.auth.audit.logs)
    assert any(
        log.action == "TENANT_PLAN_CHANGED"
        and log.plan_id == "pro"
        and log.actor_user_id == admin["user_id"]
        for log in admin_env.admin_audit.logs
    )

    response = test_client.post(
        f"/api/admin/tenants/{tenant_id}/plan", json={"plan": "gold"}, headers=admin["headers"]
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PLAN_NOT_FOUND"

    # Re-applying the same plan is a no-op (no duplicate audit event).
    response = test_client.post(
        f"/api/admin/tenants/{tenant_id}/plan", json={"plan": "pro"}, headers=admin["headers"]
    )
    assert response.status_code == 200
    assert (
        len([log for log in admin_env.admin_audit.logs if log.action == "TENANT_PLAN_CHANGED"])
        == 1
    )


def test_super_admin_cannot_suspend_own_tenant(client) -> None:
    test_client, admin_env = client
    admin = _register_admin(test_client, admin_env)

    response = test_client.post(
        f"/api/admin/tenants/{admin['tenant_id']}/suspend", headers=admin["headers"]
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_activate_user(client) -> None:
    test_client, admin_env = client
    admin = _register_admin(test_client, admin_env, name="Root")
    target = _register(test_client, name="Target Co")
    user_id = target["user_id"]
    asyncio.run(admin_env.users.set_status(user_id, "suspended", datetime.now(UTC)))

    response = test_client.post(
        f"/api/admin/tenants/{target['tenant_id']}/users/{user_id}/activate",
        headers=admin["headers"],
    )

    assert response.status_code == 200
    assert response.json()["status"] == "active"
    assert admin_env.users.users[user_id].status == "active"
    assert any(
        log.action == "USER_ACTIVATED" and log.user_id == user_id
        for log in admin_env.admin_audit.logs
    )


# ------------------------------------------- Phase 15: platform read surface


def test_overview(client) -> None:
    test_client, admin_env = client
    admin = _register_admin(test_client, admin_env, name="Root")
    _register(test_client, name="Alpha")
    _seed_subscription(admin_env, tenant_id=admin["tenant_id"], amount_cents=2900)

    response = test_client.get("/api/admin/overview", headers=admin["headers"])

    assert response.status_code == 200
    body = response.json()
    assert body["stats"]["tenants"] == {"total": 2, "active": 2, "suspended": 0}
    assert body["counts"]["users"] == 2
    assert body["counts"]["tenants"] == 2
    assert body["active_subscriptions"] == 1
    assert body["total_revenue_cents"] == 2900
    assert body["currency"] == "USD"


async def test_usage_endpoint(client) -> None:
    test_client, admin_env = client
    admin = _register_admin(test_client, admin_env, name="Root")
    target = _register(test_client, name="Target Co")
    await admin_env.usage.increment(
        tenant_id=target["tenant_id"],
        website_id="web-1",
        date=datetime.now(UTC).date().isoformat(),
        counters={
            "chats": 3,
            "messages": 9,
            "input_tokens": 100,
            "output_tokens": 50,
            "embeddings_created": 7,
            "vector_queries": 20,
            "crawl_pages": 4,
        },
    )

    response = test_client.get("/api/admin/usage", headers=admin["headers"])

    assert response.status_code == 200
    body = response.json()
    assert body["conversations"] == 3
    assert body["messages"] == 9
    assert body["input_tokens"] == 100
    assert body["output_tokens"] == 50
    assert body["total_tokens"] == 150
    assert body["embeddings_created"] == 7
    assert body["vector_queries"] == 20
    assert body["crawl_pages"] == 4


async def test_revenue_report(client) -> None:
    test_client, admin_env = client
    admin = _register_admin(test_client, admin_env, name="Root")
    target = _register(test_client, name="Target Co")
    now = datetime.now(UTC)
    await _create_subscription(
        admin_env, tenant_id=target["tenant_id"], amount_cents=2900, start=now
    )
    await _create_subscription(
        admin_env,
        tenant_id=target["tenant_id"],
        amount_cents=2900,
        start=now - timedelta(days=40),
    )
    await _create_subscription(admin_env, tenant_id=admin["tenant_id"], amount_cents=0)

    response = test_client.get("/api/admin/revenue", headers=admin["headers"])

    assert response.status_code == 200
    body = response.json()
    # Zero-amount "payments" are excluded from revenue but still live subs.
    assert body["total_revenue_cents"] == 5800
    assert body["paid_payments"] == 2
    assert body["active_subscriptions"] == 3
    assert body["currency"] == "USD"
    assert len(body["periods"]) == 2
    assert body["periods"][0]["period"] >= body["periods"][1]["period"]
    assert sum(period["revenue_cents"] for period in body["periods"]) == 5800
    assert body["recent_payments"][0]["amount_cents"] == 2900
    assert body["recent_payments"][0]["tenant_id"] == target["tenant_id"]


def test_system_health_reports_probes_and_counts(client, monkeypatch) -> None:
    test_client, admin_env = client
    admin = _register_admin(test_client, admin_env, name="Root")
    _register(test_client, name="Alpha")

    from backend.api.routes import admin as admin_module

    async def fake_db_ping() -> bool:
        return True

    async def fake_redis_ping() -> bool:
        return True

    monkeypatch.setattr(admin_module.MongoDB, "ping", fake_db_ping)
    monkeypatch.setattr(admin_module, "ping_redis", fake_redis_ping)

    response = test_client.get("/api/admin/system-health", headers=admin["headers"])

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert {check["name"]: check["status"] for check in body["checks"]} == {
        "database": "ok",
        "redis": "ok",
    }
    assert body["counts"]["users"] == 2
    assert body["counts"]["tenants"] == 2


def test_system_health_fails_closed_when_dependency_down(client, monkeypatch) -> None:
    test_client, admin_env = client
    admin = _register_admin(test_client, admin_env, name="Root")

    from backend.api.routes import admin as admin_module

    async def fake_db_ping() -> bool:
        return False

    async def fake_redis_ping() -> bool:
        return False

    monkeypatch.setattr(admin_module.MongoDB, "ping", fake_db_ping)
    monkeypatch.setattr(admin_module, "ping_redis", fake_redis_ping)

    response = test_client.get("/api/admin/system-health", headers=admin["headers"])

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert all(check["status"] == "degraded" for check in body["checks"])


def test_admin_audit_dedicated_trail_viewer(client) -> None:
    test_client, admin_env = client
    admin = _register_admin(test_client, admin_env, name="Root")
    target = _register(test_client, name="Target Co")
    tenant_id = target["tenant_id"]

    response = test_client.post(
        f"/api/admin/tenants/{tenant_id}/suspend", headers=admin["headers"]
    )
    assert response.status_code == 200
    response = test_client.post(
        f"/api/admin/tenants/{tenant_id}/plan", json={"plan": "pro"}, headers=admin["headers"]
    )
    assert response.status_code == 200

    response = test_client.get("/api/admin/audit", headers=admin["headers"])

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert {item["action"] for item in body["items"]} == {
        "TENANT_SUSPENDED",
        "TENANT_PLAN_CHANGED",
    }
    assert all(item["actor_user_id"] == admin["user_id"] for item in body["items"])

    response = test_client.get(
        "/api/admin/audit?action=TENANT_PLAN_CHANGED",
        headers=admin["headers"],
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["plan_id"] == "pro"
    assert body["items"][0]["tenant_id"] == tenant_id
