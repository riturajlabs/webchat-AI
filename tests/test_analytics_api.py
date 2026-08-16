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

from tests.analytics_helpers import (
    build_analytics_env,
    seed_answer,
    seed_day,
    seed_fallback,
    seed_feedback,
    seed_question,
    seed_website,
)
from tests.auth_helpers import build_auth_env
from tests.http_helpers import register_verified_account

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
    """Register + verify a fresh account and return (bearer headers, tenant_id)."""
    global _ACCOUNT_SEQ
    _ACCOUNT_SEQ += 1
    body = register_verified_account(
        test_client,
        name="Alice",
        email=f"alice{_ACCOUNT_SEQ}@example.com",
    )
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
        "/api/analytics/overview",
        "/api/analytics/questions",
        "/api/analytics/feedback",
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
        "avg_embedding_ms": None,
        "avg_retrieval_ms": None,
        "avg_generation_ms": None,
    }


async def test_performance_reports_stage_latencies(client) -> None:
    """The performance endpoint breaks the response time down into per-stage
    averages (embedding/retrieval/generation) from the persisted latencies."""
    test_client, _, analytics_env = client
    headers, tenant_id = _auth(test_client)
    await seed_website(analytics_env, tenant_id=tenant_id, website_id="web-1")
    await seed_day(
        analytics_env,
        tenant_id=tenant_id,
        website_id="web-1",
        date=_days_ago(1),
        response_times=[0.5, 1.5],
        embedding_ms=[20.0, 40.0],
        retrieval_ms=[10.0, 30.0],
        generation_ms=[100.0, 300.0],
    )

    response = test_client.get("/api/analytics/performance", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["avg_embedding_ms"] == 30.0
    assert body["avg_retrieval_ms"] == 20.0
    assert body["avg_generation_ms"] == 200.0
    assert body["avg_response_time"] == 1.0


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
    assert (
        test_client.get("/api/analytics/overview?days=0", headers=headers).status_code == 422
    )
    assert (
        test_client.get("/api/analytics/questions?limit=0", headers=headers).status_code == 422
    )
    assert (
        test_client.get("/api/analytics/questions?limit=51", headers=headers).status_code == 422
    )


async def test_analytics_requires_owner_or_admin_role(client) -> None:
    test_client, auth_env, _ = client
    headers, _tenant_id = _auth(test_client)
    member = next(iter(auth_env.members.members.values()))
    member.role = "viewer"

    response = test_client.get("/api/analytics/summary", headers=headers)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


# ---------------------------------------------------------------------------
# Phase 12.5: /overview, /questions, /feedback
# ---------------------------------------------------------------------------


async def test_overview_reports_resolution_metrics(client) -> None:
    test_client, _, analytics_env = client
    headers, tenant_id = _auth(test_client)
    await seed_website(analytics_env, tenant_id=tenant_id, website_id="web-1")
    await seed_day(
        analytics_env,
        tenant_id=tenant_id,
        website_id="web-1",
        date=_days_ago(1),
        chats=2,
        messages=4,
        input_tokens=100,
        output_tokens=50,
        response_times=[0.5, 1.5],
    )
    await seed_question(
        analytics_env,
        tenant_id=tenant_id,
        website_id="web-1",
        date=_days_ago(1),
        question="What courses are available?",
    )
    await seed_question(
        analytics_env,
        tenant_id=tenant_id,
        website_id="web-1",
        date=_days_ago(1),
        question="What courses are available?",
    )
    await seed_question(
        analytics_env,
        tenant_id=tenant_id,
        website_id="web-1",
        date=_days_ago(1),
        question="What are the pricing plans?",
    )
    await seed_fallback(
        analytics_env,
        tenant_id=tenant_id,
        website_id="web-1",
        date=_days_ago(1),
    )

    response = test_client.get("/api/analytics/overview", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["total_conversations"] == 2
    assert body["total_messages"] == 4
    assert body["total_questions"] == 3
    assert body["total_ai_responses"] == 3  # 2 seed_day answers + 1 fallback
    assert body["successful_answers"] == 2
    assert body["fallback_responses"] == 1
    assert body["resolution_rate"] == 66.7  # 2/3 * 100
    assert body["fallback_percentage"] == 33.3  # 1/3 * 100
    assert body["avg_response_time"] == 1.0  # only seed_day answers carry times


async def test_overview_empty_window_returns_zero_rates(client) -> None:
    test_client, _, analytics_env = client
    headers, tenant_id = _auth(test_client)
    await seed_website(analytics_env, tenant_id=tenant_id, website_id="web-1")

    response = test_client.get("/api/analytics/overview", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["total_conversations"] == 0
    assert body["total_questions"] == 0
    assert body["total_ai_responses"] == 0
    assert body["successful_answers"] == 0
    assert body["fallback_responses"] == 0
    assert body["resolution_rate"] == 0.0
    assert body["fallback_percentage"] == 0.0
    assert body["avg_response_time"] is None


async def test_overview_can_filter_by_website(client) -> None:
    test_client, _, analytics_env = client
    headers, tenant_id = _auth(test_client)
    await seed_website(analytics_env, tenant_id=tenant_id, website_id="web-a")
    await seed_website(analytics_env, tenant_id=tenant_id, website_id="web-b")
    await seed_answer(
        analytics_env,
        tenant_id=tenant_id,
        website_id="web-a",
        date=_days_ago(1),
        response_time=0.4,
    )
    await seed_answer(
        analytics_env,
        tenant_id=tenant_id,
        website_id="web-b",
        date=_days_ago(1),
        response_time=2.5,
    )

    response = test_client.get(
        "/api/analytics/overview?website_id=web-a", headers=headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_ai_responses"] == 1
    assert body["successful_answers"] == 1
    assert body["avg_response_time"] == 0.4


async def test_questions_ranks_most_asked(client) -> None:
    test_client, _, analytics_env = client
    headers, tenant_id = _auth(test_client)
    await seed_website(analytics_env, tenant_id=tenant_id, website_id="web-1")
    for question, times in (
        ("What courses are available?", 3),
        ("How do I reset my password?", 2),
        ("What are the pricing plans?", 1),
    ):
        for _ in range(times):
            await seed_question(
                analytics_env,
                tenant_id=tenant_id,
                website_id="web-1",
                date=_days_ago(1),
                question=question,
            )

    response = test_client.get("/api/analytics/questions", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert [item["question"] for item in body] == [
        "What courses are available?",
        "How do I reset my password?",
        "What are the pricing plans?",
    ]
    assert [item["count"] for item in body] == [3, 2, 1]


async def test_questions_respects_limit(client) -> None:
    test_client, _, analytics_env = client
    headers, tenant_id = _auth(test_client)
    await seed_website(analytics_env, tenant_id=tenant_id, website_id="web-1")
    for index in range(4):
        await seed_question(
            analytics_env,
            tenant_id=tenant_id,
            website_id="web-1",
            date=_days_ago(1),
            question=f"Question {index}?",
        )

    response = test_client.get("/api/analytics/questions?limit=2", headers=headers)

    assert response.status_code == 200
    assert len(response.json()) == 2


async def test_questions_defaults_to_7_days(client) -> None:
    test_client, _, analytics_env = client
    headers, tenant_id = _auth(test_client)
    await seed_website(analytics_env, tenant_id=tenant_id, website_id="web-1")
    await seed_question(
        analytics_env,
        tenant_id=tenant_id,
        website_id="web-1",
        date=_days_ago(1),
        question="Recent question?",
    )
    await seed_question(
        analytics_env,
        tenant_id=tenant_id,
        website_id="web-1",
        date=_days_ago(8),
        question="Old question?",
    )

    response = test_client.get("/api/analytics/questions", headers=headers)

    assert response.status_code == 200
    assert [item["question"] for item in response.json()] == ["Recent question?"]


async def test_questions_can_filter_by_website(client) -> None:
    test_client, _, analytics_env = client
    headers, tenant_id = _auth(test_client)
    await seed_website(analytics_env, tenant_id=tenant_id, website_id="web-a")
    await seed_website(analytics_env, tenant_id=tenant_id, website_id="web-b")
    await seed_question(
        analytics_env,
        tenant_id=tenant_id,
        website_id="web-a",
        date=_days_ago(1),
        question="For A?",
    )
    await seed_question(
        analytics_env,
        tenant_id=tenant_id,
        website_id="web-b",
        date=_days_ago(1),
        question="For B?",
    )

    response = test_client.get(
        "/api/analytics/questions?website_id=web-a", headers=headers
    )

    assert response.status_code == 200
    assert [item["question"] for item in response.json()] == ["For A?"]


async def test_feedback_reports_sentiment_and_distribution(client) -> None:
    test_client, _, analytics_env = client
    headers, tenant_id = _auth(test_client)
    await seed_website(analytics_env, tenant_id=tenant_id, website_id="web-1")
    for rating in (5, 5, 4, 3, 2, 1):
        await seed_feedback(
            analytics_env,
            tenant_id=tenant_id,
            website_id="web-1",
            rating=rating,
            date=_days_ago(1),
        )

    response = test_client.get("/api/analytics/feedback", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 6
    assert body["positive"] == 3  # 5, 5, 4
    assert body["neutral"] == 1  # 3
    assert body["negative"] == 2  # 2, 1
    assert body["positive_percentage"] == 50.0
    assert body["negative_percentage"] == 33.3
    assert body["average_rating"] == 3.33  # (5+5+4+3+2+1) / 6
    assert body["distribution"] == {"5": 2, "4": 1, "3": 1, "2": 1, "1": 1}


async def test_feedback_empty_returns_zero_sentiment(client) -> None:
    test_client, _, analytics_env = client
    headers, tenant_id = _auth(test_client)
    await seed_website(analytics_env, tenant_id=tenant_id, website_id="web-1")

    response = test_client.get("/api/analytics/feedback", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 0
    assert body["positive"] == 0
    assert body["negative"] == 0
    assert body["positive_percentage"] == 0.0
    assert body["negative_percentage"] == 0.0
    assert body["average_rating"] is None
    assert body["distribution"] == {}


async def test_analytics_isolates_tenants_for_questions_and_feedback(client) -> None:
    test_client, _, analytics_env = client
    owner_headers, owner_tenant = _auth(test_client)
    await seed_website(analytics_env, tenant_id=owner_tenant, website_id="web-1")
    await seed_question(
        analytics_env,
        tenant_id=owner_tenant,
        website_id="web-1",
        date=_days_ago(1),
        question="Private question?",
    )
    await seed_feedback(
        analytics_env,
        tenant_id=owner_tenant,
        website_id="web-1",
        rating=5,
        date=_days_ago(1),
    )

    other_headers, _other_tenant = _auth(test_client)

    assert test_client.get("/api/analytics/questions", headers=other_headers).json() == []
    assert test_client.get("/api/analytics/feedback", headers=other_headers).json()["total"] == 0
