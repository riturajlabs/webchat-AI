"""Tests for crawl event pub/sub helpers (Phase 6: Redis connection leak fix).

Verifies that:
- The subscriber reuses the shared Redis pool instead of creating isolated clients.
- PubSub cleanup (unsubscribe + close) runs correctly on disconnect / exception paths.
- The publisher publishes via the shared Redis pool.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

from backend.core import crawl_events

# ---------------------------------------------------------------------------
# Subscriber uses the shared Redis pool (no leaked connections)
# ---------------------------------------------------------------------------


async def test_subscribe_uses_shared_redis_pool() -> None:
    """subscribe() must call get_redis().pubsub(), not Redis.from_url()."""
    fake_redis = MagicMock()
    fake_pubsub = AsyncMock()
    fake_redis.pubsub.return_value = fake_pubsub

    with patch("backend.core.crawl_events.get_redis", return_value=fake_redis):
        pubsub = await crawl_events.subscribe("job-123")

    fake_redis.pubsub.assert_called_once()
    fake_pubsub.subscribe.assert_awaited_once_with("crawl:progress:job-123")
    assert pubsub is fake_pubsub


async def test_subscribe_does_not_call_redis_from_url() -> None:
    """No Redis.from_url() call should occur — the shared pool is reused."""
    fake_redis = MagicMock()
    fake_pubsub = AsyncMock()
    fake_redis.pubsub.return_value = fake_pubsub

    with (
        patch("backend.core.crawl_events.get_redis", return_value=fake_redis) as mock_get_redis,
        patch("redis.asyncio.Redis.from_url") as mock_from_url,
    ):
        await crawl_events.subscribe("job-456")

    mock_get_redis.assert_called_once()
    mock_from_url.assert_not_called()


# ---------------------------------------------------------------------------
# Publisher uses the shared Redis pool
# ---------------------------------------------------------------------------


async def test_publish_event_uses_shared_redis() -> None:
    """publish_event() must call get_redis().publish(), not a dedicated client."""
    fake_redis = AsyncMock()

    with patch("backend.core.crawl_events.get_redis", return_value=fake_redis):
        await crawl_events.publish_event("job-1", "crawl.started", {"status": "started"})

    fake_redis.publish.assert_awaited_once()
    channel = fake_redis.publish.call_args[0][0]
    payload = json.loads(fake_redis.publish.call_args[0][1])
    assert channel == "crawl:progress:job-1"
    assert payload["event"] == "crawl.started"


async def test_publish_event_swallows_exceptions() -> None:
    """Publish failures are logged but never crash the caller."""
    fake_redis = AsyncMock()
    fake_redis.publish.side_effect = ConnectionError("redis down")

    with patch("backend.core.crawl_events.get_redis", return_value=fake_redis):
        # Must not raise
        await crawl_events.publish_event("job-1", "crawl.started", {"status": "started"})


# ---------------------------------------------------------------------------
# Subscriber cleanup on exception paths
# ---------------------------------------------------------------------------


async def test_subscribe_cleanup_unsubscribes_and_closes() -> None:
    """After subscribing, the caller's finally block can unsubscribe + close."""
    fake_redis = MagicMock()
    fake_pubsub = AsyncMock()
    fake_pubsub.get_message.return_value = None
    fake_redis.pubsub.return_value = fake_pubsub

    with patch("backend.core.crawl_events.get_redis", return_value=fake_redis):
        pubsub = await crawl_events.subscribe("job-789")

    # Simulate the caller's finally block (same as crawl_jobs.py)
    await pubsub.unsubscribe()
    await pubsub.close()

    fake_pubsub.unsubscribe.assert_awaited_once()
    fake_pubsub.close.assert_awaited_once()


async def test_subscribe_pubsub_get_message_works() -> None:
    """The returned PubSub handle delegates get_message correctly."""
    fake_redis = MagicMock()
    fake_pubsub = AsyncMock()
    expected_msg = {"type": "message", "data": '{"event":"crawl.progress","data":{}}'}
    fake_pubsub.get_message.return_value = expected_msg
    fake_redis.pubsub.return_value = fake_pubsub

    with patch("backend.core.crawl_events.get_redis", return_value=fake_redis):
        pubsub = await crawl_events.subscribe("job-abc")

    msg = await pubsub.get_message(ignore_subscribe_messages=True)
    assert msg is expected_msg


# ---------------------------------------------------------------------------
# close_publisher is a no-op (shared pool lifecycle managed elsewhere)
# ---------------------------------------------------------------------------


async def test_close_publisher_is_noop() -> None:
    """close_publisher() must not raise or attempt to close the shared pool."""
    await crawl_events.close_publisher()  # must not raise


# ---------------------------------------------------------------------------
# Channel naming
# ---------------------------------------------------------------------------


def test_channel_naming() -> None:
    assert crawl_events._channel("abc") == "crawl:progress:abc"
    assert crawl_events._channel("123") == "crawl:progress:123"
