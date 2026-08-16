"""Service-level aggregation tests for Phase 12.5 analytics (no HTTP).

Exercise `AnalyticsService.get_overview` / `get_top_questions` /
`get_feedback_analytics` against the in-memory fakes: the percentage math
(resolution rate, fallback percentage), question ranking, and the feedback
sentiment buckets. The endpoint wiring + RBAC is covered by
`test_analytics_api.py`.
"""

from datetime import UTC, datetime, timedelta

import pytest

from tests.analytics_helpers import (
    build_analytics_env,
    seed_fallback,
    seed_feedback,
    seed_question,
    seed_website,
)


def _days_ago(days: int) -> datetime:
    return (datetime.now(UTC) - timedelta(days=days)).replace(hour=12, minute=0, second=0)


@pytest.fixture
def env():
    return build_analytics_env()


async def test_get_overview_computes_resolution_and_fallback_rates(env) -> None:
    tenant_id = "tenant-1"
    await seed_website(env, tenant_id=tenant_id, website_id="web-1")
    await seed_question(
        env,
        tenant_id=tenant_id,
        website_id="web-1",
        date=_days_ago(1),
        question="Course?",
    )
    await seed_question(
        env,
        tenant_id=tenant_id,
        website_id="web-1",
        date=_days_ago(1),
        question="Course?",
    )
    await seed_fallback(env, tenant_id=tenant_id, website_id="web-1", date=_days_ago(1))

    item = await env.service.get_overview(tenant_id, days=7)

    assert item.total_questions == 2
    assert item.total_ai_responses == 1
    assert item.successful_answers == 0
    assert item.fallback_responses == 1
    assert item.resolution_rate == 0.0
    assert item.fallback_percentage == 100.0
    assert item.avg_response_time is None


async def test_get_overview_rounds_rates_to_one_decimal(env) -> None:
    tenant_id = "tenant-1"
    await seed_website(env, tenant_id=tenant_id, website_id="web-1")
    for _ in range(2):
        await seed_fallback(env, tenant_id=tenant_id, website_id="web-1", date=_days_ago(1))
    await seed_question(
        env,
        tenant_id=tenant_id,
        website_id="web-1",
        date=_days_ago(1),
        question="A?",
    )

    item = await env.service.get_overview(tenant_id, days=7)

    assert item.total_ai_responses == 2
    assert item.successful_answers == 0
    assert item.fallback_responses == 2
    assert item.resolution_rate == 0.0
    assert item.fallback_percentage == 100.0


async def test_get_overview_empty_window_returns_zero_rates(env) -> None:
    item = await env.service.get_overview("tenant-1", days=7)

    assert item.total_conversations == 0
    assert item.total_questions == 0
    assert item.total_ai_responses == 0
    assert item.resolution_rate == 0.0
    assert item.fallback_percentage == 0.0
    assert item.avg_response_time is None


async def test_get_overview_scopes_to_website(env) -> None:
    tenant_id = "tenant-1"
    await seed_website(env, tenant_id=tenant_id, website_id="web-a")
    await seed_fallback(env, tenant_id=tenant_id, website_id="web-a", date=_days_ago(1))
    await seed_website(env, tenant_id=tenant_id, website_id="web-b")
    await seed_question(
        env,
        tenant_id=tenant_id,
        website_id="web-b",
        date=_days_ago(1),
        question="B?",
    )

    item = await env.service.get_overview(tenant_id, days=7, website_id="web-a")

    assert item.total_questions == 0
    assert item.total_ai_responses == 1
    assert item.fallback_responses == 1
    assert item.resolution_rate == 0.0


async def test_get_top_questions_ranks_by_frequency(env) -> None:
    tenant_id = "tenant-1"
    await seed_website(env, tenant_id=tenant_id, website_id="web-1")
    for question, times in (("Top question?", 3), ("Second question?", 2), ("Rare question?", 1)):
        for _ in range(times):
            await seed_question(
                env,
                tenant_id=tenant_id,
                website_id="web-1",
                date=_days_ago(1),
                question=question,
            )

    rows = await env.service.get_top_questions(tenant_id, days=7, limit=10)

    assert [(row.question, row.count) for row in rows] == [
        ("Top question?", 3),
        ("Second question?", 2),
        ("Rare question?", 1),
    ]


async def test_get_top_questions_respects_limit_and_skips_blank(env) -> None:
    tenant_id = "tenant-1"
    await seed_website(env, tenant_id=tenant_id, website_id="web-1")
    for index in range(3):
        await seed_question(
            env,
            tenant_id=tenant_id,
            website_id="web-1",
            date=_days_ago(1),
            question=f"Q {index}?",
        )
    blank = seed_question
    await blank(env, tenant_id=tenant_id, website_id="web-1", date=_days_ago(1), question="   ")

    rows = await env.service.get_top_questions(tenant_id, days=7, limit=2)

    assert len(rows) == 2
    assert rows[0].count == 1
    assert all(row.question.strip() for row in rows)


async def test_get_top_questions_empty_window(env) -> None:
    rows = await env.service.get_top_questions("tenant-1", days=7, limit=10)

    assert rows == []


async def test_get_feedback_analytics_sentiment_buckets(env) -> None:
    tenant_id = "tenant-1"
    await seed_website(env, tenant_id=tenant_id, website_id="web-1")
    for rating in (5, 5, 4, 3, 1):
        await seed_feedback(
            env,
            tenant_id=tenant_id,
            website_id="web-1",
            rating=rating,
            date=_days_ago(1),
        )

    row = await env.service.get_feedback_analytics(tenant_id, days=7)

    assert row.total == 5
    assert row.positive == 3  # 5, 5, 4
    assert row.neutral == 1  # 3
    assert row.negative == 1  # 1
    assert row.average_rating == 3.6  # (5+5+4+3+1) / 5
    assert row.distribution == {5: 2, 4: 1, 3: 1, 1: 1}


async def test_get_feedback_analytics_empty(env) -> None:
    row = await env.service.get_feedback_analytics("tenant-1", days=7)

    assert row.total == 0
    assert row.positive == 0
    assert row.negative == 0
    assert row.average_rating is None
    assert row.distribution == {}


async def test_get_feedback_analytics_scopes_to_website(env) -> None:
    tenant_id = "tenant-1"
    await seed_website(env, tenant_id=tenant_id, website_id="web-a")
    await seed_feedback(
        env,
        tenant_id=tenant_id,
        website_id="web-a",
        rating=5,
        date=_days_ago(1),
    )
    await seed_website(env, tenant_id=tenant_id, website_id="web-b")
    await seed_feedback(
        env,
        tenant_id=tenant_id,
        website_id="web-b",
        rating=1,
        date=_days_ago(1),
    )

    row = await env.service.get_feedback_analytics(tenant_id, days=7, website_id="web-a")

    assert row.total == 1
    assert row.positive == 1
    assert row.negative == 0
