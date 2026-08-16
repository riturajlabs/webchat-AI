"""Unit tests for the feedback service (Phase 12.4, ADR-005 §5.6).

Covers the widget submit path (validation, tenant/website/session binding,
dedup, idempotency) and the dashboard read paths (paginated list with
filters + satisfaction summary windowing). No FastAPI involvement: the
service depends only on repository Protocols.
"""

from datetime import UTC, datetime, timedelta

import pytest
from backend.core.errors import FeedbackMessageNotFoundError
from backend.models.chat_message import CHAT_ROLE_USER
from backend.models.feedback import Feedback
from pydantic import ValidationError

from tests.feedback_helpers import build_feedback_env, seed_assistant_message


async def test_submit_persists_rating_for_known_message() -> None:
    env = build_feedback_env()
    await seed_assistant_message(env, tenant_id="tenant-a", message_id="msg-1")

    await env.service.submit(
        tenant_id="tenant-a",
        website_id="web-1",
        session_id="session-1",
        message_id="msg-1",
        rating=5,
        category="helpful",
        comment="  Great answer  ",
    )

    stored = env.feedback.feedback
    assert len(stored) == 1
    item = stored[0]
    assert item.tenant_id == "tenant-a"
    assert item.website_id == "web-1"
    assert item.session_id == "session-1"
    assert item.message_id == "msg-1"
    assert item.rating == 5
    assert item.category == "helpful"
    assert item.comment == "Great answer"  # stripped


async def test_submit_rejects_unknown_message() -> None:
    env = build_feedback_env()

    with pytest.raises(FeedbackMessageNotFoundError):
        await env.service.submit(
            tenant_id="tenant-a",
            website_id="web-1",
            session_id="session-1",
            message_id="missing",
            rating=3,
            category="other",
        )
    assert env.feedback.feedback == []


async def test_submit_rejects_foreign_website_message() -> None:
    env = build_feedback_env()
    await seed_assistant_message(
        env, tenant_id="tenant-a", message_id="msg-1", website_id="other-web"
    )

    with pytest.raises(FeedbackMessageNotFoundError):
        await env.service.submit(
            tenant_id="tenant-a",
            website_id="web-1",
            session_id="session-1",
            message_id="msg-1",
            rating=3,
            category="other",
        )
    assert env.feedback.feedback == []


async def test_submit_rejects_session_mismatch() -> None:
    env = build_feedback_env()
    await seed_assistant_message(
        env, tenant_id="tenant-a", message_id="msg-1", session_id="session-1"
    )

    with pytest.raises(FeedbackMessageNotFoundError):
        await env.service.submit(
            tenant_id="tenant-a",
            website_id="web-1",
            session_id="other-session",
            message_id="msg-1",
            rating=3,
            category="other",
        )
    assert env.feedback.feedback == []


async def test_submit_rejects_user_message() -> None:
    env = build_feedback_env()
    message = await seed_assistant_message(env, tenant_id="tenant-a", message_id="msg-1")
    message.role = CHAT_ROLE_USER

    with pytest.raises(FeedbackMessageNotFoundError):
        await env.service.submit(
            tenant_id="tenant-a",
            website_id="web-1",
            session_id="session-1",
            message_id="msg-1",
            rating=3,
            category="other",
        )
    assert env.feedback.feedback == []


async def test_submit_is_idempotent_per_message() -> None:
    env = build_feedback_env()
    await seed_assistant_message(env, tenant_id="tenant-a", message_id="msg-1")

    for _ in range(2):
        await env.service.submit(
            tenant_id="tenant-a",
            website_id="web-1",
            session_id="session-1",
            message_id="msg-1",
            rating=4,
            category="helpful",
        )

    assert len(env.feedback.feedback) == 1
    assert env.feedback.feedback[0].rating == 4


async def test_submit_isolates_tenants() -> None:
    env = build_feedback_env()
    await seed_assistant_message(env, tenant_id="tenant-a", message_id="msg-1")
    await seed_assistant_message(env, tenant_id="tenant-b", message_id="msg-1")

    await env.service.submit(
        tenant_id="tenant-b",
        website_id="web-1",
        session_id="session-1",
        message_id="msg-1",
        rating=2,
        category="wrong",
    )

    # Tenant A sees nothing; tenant B sees exactly one.
    assert [item for item in env.feedback.feedback if item.tenant_id == "tenant-a"] == []
    assert len([item for item in env.feedback.feedback if item.tenant_id == "tenant-b"]) == 1


async def test_list_feedback_paginates_and_filters() -> None:
    env = build_feedback_env()
    for index in range(5):
        await seed_assistant_message(env, tenant_id="tenant-a", message_id=f"msg-{index}")
        await env.service.submit(
            tenant_id="tenant-a",
            website_id="web-1",
            session_id="session-1",
            message_id=f"msg-{index}",
            rating=index + 1,
            category="helpful" if index % 2 == 0 else "wrong",
        )

    items, total = await env.service.list_feedback("tenant-a", page=1, per_page=2)
    assert total == 5
    assert len(items) == 2
    # Newest first.
    assert [item.message_id for item in items] == ["msg-4", "msg-3"]

    filtered, filtered_total = await env.service.list_feedback(
        "tenant-a", page=1, per_page=20, category="wrong"
    )
    assert filtered_total == 2
    assert {item.message_id for item in filtered} == {"msg-1", "msg-3"}

    rated, rated_total = await env.service.list_feedback("tenant-a", page=1, per_page=20, rating=5)
    assert rated_total == 1
    assert rated[0].message_id == "msg-4"


async def test_list_feedback_scopes_to_tenant() -> None:
    env = build_feedback_env()
    await seed_assistant_message(env, tenant_id="tenant-a", message_id="msg-a")
    await seed_assistant_message(env, tenant_id="tenant-b", message_id="msg-b")
    await env.service.submit(
        tenant_id="tenant-a",
        website_id="web-1",
        session_id="session-1",
        message_id="msg-a",
        rating=5,
        category="helpful",
    )
    await env.service.submit(
        tenant_id="tenant-b",
        website_id="web-1",
        session_id="session-1",
        message_id="msg-b",
        rating=1,
        category="offensive",
    )

    items, total = await env.service.list_feedback("tenant-a", page=1, per_page=20)
    assert total == 1
    assert items[0].message_id == "msg-a"


async def test_summary_computes_distribution_and_average() -> None:
    env = build_feedback_env()
    for index in range(5):
        await seed_assistant_message(env, tenant_id="tenant-a", message_id=f"msg-{index}")
        await env.service.submit(
            tenant_id="tenant-a",
            website_id="web-1",
            session_id="session-1",
            message_id=f"msg-{index}",
            rating=index + 1,
            category="other",
        )

    summary = await env.service.get_summary("tenant-a")

    assert summary.total == 5
    assert summary.distribution == {1: 1, 2: 1, 3: 1, 4: 1, 5: 1}


async def test_summary_defaults_to_30_day_window() -> None:
    env = build_feedback_env()
    await seed_assistant_message(env, tenant_id="tenant-a", message_id="msg-recent")
    await seed_assistant_message(env, tenant_id="tenant-a", message_id="msg-old")
    for message_id in ("msg-recent", "msg-old"):
        await env.service.submit(
            tenant_id="tenant-a",
            website_id="web-1",
            session_id="session-1",
            message_id=message_id,
            rating=5,
            category="helpful",
        )
    # Age one rating past the default 30-day window.
    old = env.feedback.feedback[0]
    old.created_at = datetime.now(UTC) - timedelta(days=60)

    summary = await env.service.get_summary("tenant-a")

    assert summary.total == 1
    assert summary.distribution == {5: 1}


async def test_summary_empty_window_returns_zeros() -> None:
    env = build_feedback_env()

    summary = await env.service.get_summary("tenant-a")

    assert summary.total == 0
    assert summary.distribution == {}


async def test_summary_respects_website_filter() -> None:
    env = build_feedback_env()
    for website in ("web-1", "web-2"):
        await seed_assistant_message(
            env, tenant_id="tenant-a", message_id=f"msg-{website}", website_id=website
        )
        await env.service.submit(
            tenant_id="tenant-a",
            website_id=website,
            session_id="session-1",
            message_id=f"msg-{website}",
            rating=5,
            category="helpful",
        )

    summary = await env.service.get_summary("tenant-a", website_id="web-1")

    assert summary.total == 1
    assert summary.distribution == {5: 1}


async def test_summary_respects_explicit_since() -> None:
    env = build_feedback_env()
    await seed_assistant_message(env, tenant_id="tenant-a", message_id="msg-1")
    await env.service.submit(
        tenant_id="tenant-a",
        website_id="web-1",
        session_id="session-1",
        message_id="msg-1",
        rating=4,
        category="helpful",
    )

    summary = await env.service.get_summary("tenant-a", since=datetime.now(UTC) - timedelta(days=1))
    assert summary.total == 1
    assert summary.distribution == {4: 1}

    none = await env.service.get_summary("tenant-a", since=datetime.now(UTC))
    assert none.total == 0


async def test_summary_respects_days_window() -> None:
    env = build_feedback_env()
    # Two ratings today, one from 10 days ago, one from 40 days ago.
    for message_id, age_days in (
        ("msg-today-1", 0),
        ("msg-today-2", 0),
        ("msg-ten-days", 10),
        ("msg-forty-days", 40),
    ):
        await seed_assistant_message(env, tenant_id="tenant-a", message_id=message_id)
        await env.service.submit(
            tenant_id="tenant-a",
            website_id="web-1",
            session_id="session-1",
            message_id=message_id,
            rating=5,
            category="helpful",
        )
        stored = next(item for item in env.feedback.feedback if item.message_id == message_id)
        stored.created_at = datetime.now(UTC) - timedelta(days=age_days)

    # 30-day window includes today + the 10-day-old rating.
    summary = await env.service.get_summary("tenant-a", days=30)
    assert summary.total == 3
    assert summary.distribution == {5: 3}

    # 7-day window includes only today's ratings.
    short = await env.service.get_summary("tenant-a", days=7)
    assert short.total == 2


def test_feedback_model_validates_rating() -> None:
    with pytest.raises(ValidationError):
        Feedback.new(
            tenant_id="t",
            website_id="w",
            session_id="s",
            message_id="m",
            rating=6,
            category="helpful",
        )
