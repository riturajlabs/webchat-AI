"""End-to-end HTTP tests for the /api/analytics endpoints using fakes.

Phase 11.3: read-only reporting over the existing session/message/usage data.
The window math and cost model live in `AnalyticsService`; the aggregations
live in the (fake) repository, so these tests exercise both layers and the
routing/RBAC/auth of the endpoints.
"""

from datetime import UTC, datetime, timedelta

import pytest
from backend.api.deps import get_analytics_service, get_auth_service
from backend.core.config import get_settings
from backend.main import create_app
from fastapi.testclient import TestClient

from tests.analytics_helpers import build_analytics_env, seed_day, seed_website
from tests.auth_helpers import VALID_PASSWORD, build_auth_env

REGISTER_PAYLOAD = {
    "name": "Alice",
    "email": "alice@example.com",
    "password": VALID_PASSWORD,
}

_ACCOUNT_SEQ = 0


@pytest.fixture
def client(monkeypatch):
    """A TestClient whose auth + analytics services use in-memory fakes."""
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    get_settings.cache_clear()
    auth_env = build_auth_env()
    analytics_env = build_analytics_env()
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: auth_env.service
    app.dependency_overrides[get_analytics_service] = lambda: analytics_env.service
    with TestClient(app) as test_client:
        yield test_client, auth_env, analytics_env
    get_settings.cache_clear()


def _auth(test_client: TestClient) -> tuple[dict[str, str], str]:
    """Register a fresh account and return (bearer headers, tenant_id)."""
    global _ACCOUNT_SEQ
    _ACCOUNT_SEQ += 1
    payload = {
        "name": "Alice",
        "email": f"alice{_ACCOUNT_SEQ}@example.com",
        "password": VALID_PASSWORD,
    }
    response = test_client.post("/api/auth/register", json=payload)
    assert response.status_code == 201, response.text
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["user"]["tenant_id"]


def _days_ago(days: int) -> datetime:
    return (datetime.now(UTC) - timedelta(days=days)).replace(hour=12, minute=0, second=0)


def test_analytics_requires_authentication(client) -> None:
    test_client, _, _ = client
    for path in (
        "/api/analytics/summary",
        "/api/analytics/timeseries",
        "/api/analytics/top-websites",
        "/api/analytics/performance",
    ):
        assert test_client.get(path).status_code == 401


async def test_summary_reports_totals_and_estimated_cost(client) -> None:
    test_client, _, analytics_env = client
    headers, tenant_id = _auth(test_client)
    await seed_website(analytics_env, tenant_id=tenant_id, website_id="web-1")
    await seed_day(
        analytics_env,
        tenant_id=tenant_id,
        website_id="web-1",
        date=_days_ago(1),
        chats=3,
        messages=10,
        input_tokens=1000,
        output_tokens=500,
        response_times=[0.5, 1.5],
    )

    response = test_client.get("/api/analytics/summary", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["total_conversations"] == 3
    assert body["total_messages"] == 10
    assert body["total_ai_responses"] == 2
    assert body["total_tokens"] == 1500
    assert body["total_input_tokens"] == 1000
    assert body["total_output_tokens"] == 500
    # 1000 input @ $0.30/M + 500 output @ $1.50/M = $0.00105.
    assert body["estimated_cost"] == 0.00105
    assert body["avg_response_time"] == 1.0


async def test_summary_defaults_to_last_7_days(client) -> None:
    test_client, _, analytics_env = client
    headers, tenant_id = _auth(test_client)
    await seed_website(analytics_env, tenant_id=tenant_id, website_id="web-1")
    await seed_day(analytics_env, tenant_id=tenant_id, website_id="web-1", date=_days_ago(1))
    await seed_day(analytics_env, tenant_id=tenant_id, website_id="web-1", date=_days_ago(8))

    response = test_client.get("/api/analytics/summary", headers=headers)

    assert response.status_code == 200
    assert response.json()["total_conversations"] == 1


async def test_summary_can_filter_by_website(client) -> None:
    test_client, _, analytics_env = client
    headers, tenant_id = _auth(test_client)
    await seed_website(analytics_env, tenant_id=tenant_id, website_id="web-a")
    await seed_website(analytics_env, tenant_id=tenant_id, website_id="web-b")
    await seed_day(analytics_env, tenant_id=tenant_id, website_id="web-a", date=_days_ago(1))
    await seed_day(analytics_env, tenant_id=tenant_id, website_id="web-b", date=_days_ago(1))

    response = test_client.get(
        "/api/analytics/summary?website_id=web-a", headers=headers
    )

    assert response.status_code == 200
    assert response.json()["total_conversations"] == 1


async def test_timeseries_returns_zero_filled_daily_points(client) -> None:
    test_client, _, analytics_env = client
    headers, tenant_id = _auth(test_client)
    await seed_website(analytics_env, tenant_id=tenant_id, website_id="web-1")
    await seed_day(
        analytics_env,
        tenant_id=tenant_id,
        website_id="web-1",
        date=_days_ago(2),
        chats=4,
        messages=8,
        input_tokens=200,
        output_tokens=100,
    )

    response = test_client.get("/api/analytics/timeseries?days=5", headers=headers)

    assert response.status_code == 200
    points = response.json()
    assert len(points) == 5
    assert [point["date"] for point in points] == [
        _days_ago(4).date().isoformat(),
        _days_ago(3).date().isoformat(),
        _days_ago(2).date().isoformat(),
        _days_ago(1).date().isoformat(),
        _days_ago(0).date().isoformat(),
    ]
    active = next(point for point in points if point["date"] == _days_ago(2).date().isoformat())
    assert active["conversations"] == 4
    assert active["messages"] == 8
    assert active["tokens"] == 300
    assert active["input_tokens"] == 200
    assert active["output_tokens"] == 100
    for point in points:
        if point is active:
            continue
        assert point["conversations"] == 0
        assert point["tokens"] == 0


async def test_timeseries_respects_custom_window(client) -> None:
    test_client, _, analytics_env = client
    headers, tenant_id = _auth(test_client)
    await seed_website(analytics_env, tenant_id=tenant_id, website_id="web-1")
    await seed_day(analytics_env, tenant_id=tenant_id, website_id="web-1", date=_days_ago(1))

    response = test_client.get("/api/analytics/timeseries?days=1", headers=headers)

    assert response.status_code == 200
    assert len(response.json()) == 1


async def test_top_websites_ranks_by_activity_and_resolves_names(client) -> None:
    test_client, _, analytics_env = client
    headers, tenant_id = _auth(test_client)
    await seed_website(analytics_env, tenant_id=tenant_id, website_id="web-a", name="Alpha")
    await seed_website(analytics_env, tenant_id=tenant_id, website_id="web-b", name="Beta")
    await seed_day(
        analytics_env, tenant_id=tenant_id, website_id="web-a", date=_days_ago(1), chats=2
    )
    await seed_day(
        analytics_env, tenant_id=tenant_id, website_id="web-b", date=_days_ago(1), chats=5
    )

    response = test_client.get("/api/analytics/top-websites", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert [item["website_id"] for item in body] == ["web-b", "web-a"]
    assert body[0]["website_name"] == "Beta"
    assert body[0]["conversations"] == 5


async def test_top_websites_respects_limit(client) -> None:
    test_client, _, analytics_env = client
    headers, tenant_id = _auth(test_client)
    for index in range(3):
        await seed_website(analytics_env, tenant_id=tenant_id, website_id=f"web-{index}")
        await seed_day(
            analytics_env, tenant_id=tenant_id, website_id=f"web-{index}", date=_days_ago(1)
        )

    response = test_client.get("/api/analytics/top-websites?limit=2", headers=headers)

    assert response.status_code == 200
    assert len(response.json()) == 2


async def test_performance_reports_response_time_stats(client) -> None:
    test_client, _, analytics_env = client
    headers, tenant_id = _auth(test_client)
    await seed_website(analytics_env, tenant_id=tenant_id, website_id="web-1")
    await seed_day(
        analytics_env,
        tenant_id=tenant_id,
        website_id="web-1",
        date=_days_ago(1),
        response_times=[0.5, 1.5, 3.0],
    )

    response = test_client.get("/api/analytics/performance", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["avg_response_time"] == 1.667
    assert body["fastest_response_time"] == 0.5
    assert body["slowest_response_time"] == 3.0


async def test_performance_empty_returns_nulls(client) -> None:
    test_client, _, analytics_env = client
    headers, tenant_id = _auth(test_client)
    await seed_website(analytics_env, tenant_id=tenant_id, website_id="web-1")

    response = test_client.get("/api/analytics/performance", headers=headers)

    assert response.status_code == 200
    assert response.json() == {
        "avg_response_time": None,
        "fastest_response_time": None,
        "slowest_response_time": None,
    }


async def test_analytics_isolates_tenants(client) -> None:
    test_client, _, analytics_env = client
    owner_headers, owner_tenant = _auth(test_client)
    await seed_website(analytics_env, tenant_id=owner_tenant, website_id="web-1")
    await seed_day(
        analytics_env, tenant_id=owner_tenant, website_id="web-1", date=_days_ago(1), chats=9
    )

    other_headers, _other_tenant = _auth(test_client)

    assert test_client.get("/api/analytics/summary", headers=other_headers).json()[
        "total_conversations"
    ] == 0
    assert test_client.get("/api/analytics/top-websites", headers=other_headers).json() == []


async def test_analytics_rejects_invalid_days(client) -> None:
    test_client, _, _ = client
    headers, _tenant_id = _auth(test_client)

    assert test_client.get("/api/analytics/summary?days=0", headers=headers).status_code == 422
    assert test_client.get("/api/analytics/summary?days=91", headers=headers).status_code == 422
    assert (
        test_client.get("/api/analytics/top-websites?limit=0", headers=headers).status_code == 422
    )


async def test_analytics_requires_owner_or_admin_role(client) -> None:
    test_client, auth_env, _ = client
    headers, _tenant_id = _auth(test_client)
    member = next(iter(auth_env.members.members.values()))
    member.role = "viewer"

    response = test_client.get("/api/analytics/summary", headers=headers)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
