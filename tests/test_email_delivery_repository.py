"""Real-Mongo regression tests for the durable email delivery store.

The email state machine's behaviour was previously asserted only against
``FakeEmailDeliveryRepository``. The fake keys its records in a dict by
``delivery_id``, so it is structurally incapable of exhibiting a claim that
crosses from one delivery into another. These tests run the same guarantees
against a real ``mongod`` so the database - not the fake - is the thing being
measured.

Three defects are pinned here, all of which the fake could not see:

1. A claim must be scoped to its own delivery. An unscoped claim filter lets a
   delivery hijack an unrelated retryable row.
2. ``provider_key_expires_at`` is anchored to the *first* attempt. Resetting it
   on every claim would let a repeatedly-retried ``unknown`` delivery drift past
   the provider's real idempotency window and be re-sent for real.
3. A reclaim must match the identity it is claiming. Same delivery id, different
   provider key, means corrupt or forged input and must not take over the row.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from backend.prototypes.mongo_queue.config import DEFAULT_MONGO_URI
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

WINDOW = timedelta(hours=24)
STALE = timedelta(seconds=120)


def _now() -> datetime:
    return datetime.now(UTC)


async def _claim(repo: Any, delivery_id: str, *, token: str, now: datetime, **kw: Any) -> Any:
    defaults: dict[str, Any] = {
        "tenant_id": "tenant-a",
        "provider_key": f"email:tenant-a:{delivery_id}",
        "content_hash": "h",
        "now": now,
        "provider_window": WINDOW,
        "stale_after": STALE,
    }
    defaults.update(kw)
    return await repo.begin_attempt(delivery_id, attempt_token=token, **defaults)


@pytest.fixture
async def mongo_db() -> AsyncIterator[AsyncIOMotorDatabase[dict[str, Any]]]:
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        DEFAULT_MONGO_URI, serverSelectionTimeoutMS=3000, tz_aware=True
    )
    try:
        await client.admin.command("ping")
    except Exception as exc:  # noqa: BLE001 - environment guard
        client.close()
        pytest.skip(f"isolated prototype mongod unreachable: {exc}")
    db: AsyncIOMotorDatabase[dict[str, Any]] = client["webchat_ai_test_email_delivery"]
    yield db
    for name in await db.list_collection_names():
        await db.drop_collection(name)
    client.close()


@pytest.fixture
async def repo(mongo_db: AsyncIOMotorDatabase[dict[str, Any]]) -> Any:
    from backend.repositories.email_delivery_repository import MongoEmailDeliveryRepository

    return MongoEmailDeliveryRepository(mongo_db)


# --------------------------------------------------------------------------
# 1. Claim scoping: a claim must never cross into another delivery
# --------------------------------------------------------------------------


async def test_a_claim_cannot_hijack_another_deliverys_retryable_row(repo: Any) -> None:
    """The core scoping guarantee.

    Delivery ``b`` is left in a retryable state. A later claim for delivery
    ``a`` must create and claim *its own* row, leaving ``b`` untouched. An
    unscoped claim filter matches ``b`` and mutates it instead.
    """
    now = _now()
    b = await _claim(repo, "delivery-b", token="t-b1", now=now)
    assert b.refusal is None
    await repo.mark_failed("delivery-b", "t-b1", "h5", now=now)

    a = await _claim(repo, "delivery-a", token="t-a1", now=now)

    assert a.refusal is None
    assert a.record.delivery_id == "delivery-a"

    # `b` must be exactly as the previous attempt left it: still failed, one
    # attempt, not re-claimed by somebody else's delivery.
    b_row = await repo.get("delivery-b")
    assert b_row is not None
    assert b_row.state == "failed"
    assert b_row.attempts == 1
    assert b_row.attempt_token == "t-b1"

    a_row = await repo.get("delivery-a")
    assert a_row is not None
    assert a_row.state == "sending"
    assert a_row.attempts == 1


async def test_a_duplicate_claim_cannot_reopen_an_accepted_delivery(
    repo: Any,
) -> None:
    """A redelivery of an accepted message must not consume another delivery.

    This is the dangerous shape of the same bug: with an unscoped filter, a
    duplicate payload for the already-accepted ``a`` claims the failed ``b`` and
    the mail goes out a second time, while ``a`` still reads accepted.
    """
    now = _now()
    first_a = await _claim(repo, "delivery-a", token="t-a1", now=now)
    assert first_a.refusal is None
    assert await repo.mark_accepted("delivery-a", "t-a1", "msg-1", now=now)

    first_b = await _claim(repo, "delivery-b", token="t-b1", now=now)
    assert first_b.refusal is None
    await repo.mark_failed("delivery-b", "t-b1", "h5", now=now)

    # A redelivery of `a` (same delivery id, fresh attempt token).
    again = await _claim(repo, "delivery-a", token="t-a2", now=now)

    assert again.refusal is not None
    b_row = await repo.get("delivery-b")
    assert b_row is not None
    assert b_row.state == "failed", "an accepted delivery's retry consumed another row"
    assert b_row.attempt_token == "t-b1"


async def test_concurrent_claims_of_one_delivery_produce_exactly_one_winner(
    repo: Any,
) -> None:
    """Two workers racing the same delivery: one may send, the other must not."""
    import asyncio

    now = _now()
    results = await asyncio.gather(
        _claim(repo, "delivery-a", token="t-1", now=now),
        _claim(repo, "delivery-a", token="t-2", now=now),
    )
    granted = [r for r in results if r.refusal is None]
    assert len(granted) == 1, "exactly one claim may be granted"
    row = await repo.get("delivery-a")
    assert row is not None
    assert row.attempts == 1


# --------------------------------------------------------------------------
# 2. The provider-key window is anchored to the first attempt
# --------------------------------------------------------------------------


async def test_the_key_window_is_anchored_to_the_first_attempt(repo: Any) -> None:
    """Retrying must not extend the provider's real idempotency window.

    The window says "the provider will still collapse a retry onto the original
    send for this long". That is a fact about the provider's first request, not
    something a retry can renew. If a claim resets the deadline, a delivery that
    keeps failing keeps pushing the deadline out and is eventually re-sent long
    after the provider stopped honouring the key - a real duplicate.
    """
    now = _now()
    first = await _claim(repo, "delivery-a", token="t-1", now=now)
    assert first.refusal is None
    original = (await repo.get("delivery-a")).provider_key_expires_at  # type: ignore[union-attr]

    # A later, definitive failure, then a fresh claim well after the original
    # window would have closed.
    later = now + WINDOW - timedelta(minutes=1)
    await repo.mark_failed("delivery-a", "t-1", "h5", now=later)
    await _claim(repo, "delivery-a", token="t-2", now=later)

    row = await repo.get("delivery-a")
    assert row is not None
    assert row.provider_key_expires_at == original, "the key window was extended by a retry"


async def test_an_unknown_past_the_original_window_is_never_resent(repo: Any) -> None:
    """End-to-end version of the anchoring guarantee, on a real database."""
    now = _now()
    await _claim(repo, "delivery-a", token="t-1", now=now)
    await repo.mark_unknown("delivery-a", "t-1", now=now)

    past = await _claim(repo, "delivery-a", token="t-2", now=now + WINDOW + timedelta(hours=1))

    assert past.refusal == "unknown_expired"
    row = await repo.get("delivery-a")
    assert row is not None
    assert row.state == "unknown"


async def test_a_crashed_sending_attempt_past_the_key_window_escalates(repo: Any) -> None:
    """A takeover must not outlive the provider's willingness to deduplicate.

    A worker that dies mid-send leaves the row in `sending`. The attempt may have
    died *after* the provider accepted. Taking the row over while the provider
    still honours the key is safe; taking it over after the window closes would
    send a second copy, because the provider would treat the retry as new mail.
    So a stale `sending` row past the window is escalated, exactly like
    `unknown` - it is the same unknowable outcome reached by a different route.
    """
    now = _now()
    await _claim(repo, "delivery-a", token="t-1", now=now)

    too_soon = await _claim(repo, "delivery-a", token="t-2", now=now + STALE + timedelta(seconds=1))
    assert too_soon.refusal is None, "a crashed attempt inside the window is reclaimable"

    past = await _claim(repo, "delivery-a", token="t-3", now=now + WINDOW + timedelta(hours=1))

    assert past.refusal == "unknown_expired"
    row = await repo.get("delivery-a")
    assert row is not None
    assert row.state == "sending", "the escalated row must be left as it was found"
    assert row.provider_message_id is None


# --------------------------------------------------------------------------
# 3. A reclaim must match the identity it claims
# --------------------------------------------------------------------------


async def test_a_claim_with_a_different_provider_key_is_refused(repo: Any) -> None:
    """Same delivery id, different key: refuse rather than take over.

    The delivery id is the row's identity. If a payload arrives claiming that id
    with a different provider key, either the queue has been tampered with or a
    caller minted a key inconsistently. Overwriting the stored key would let one
    delivery's identity be re-pointed at a different send, so the row is left
    alone.
    """
    now = _now()
    await _claim(repo, "delivery-a", token="t-1", now=now)
    await repo.mark_failed("delivery-a", "t-1", "h5", now=now)

    impostor = await _claim(
        repo, "delivery-a", token="t-2", now=now, provider_key="email:tenant-a:other"
    )

    assert impostor.refusal is not None
    row = await repo.get("delivery-a")
    assert row is not None
    assert row.provider_key == "email:tenant-a:delivery-a", "stored key was overwritten"
    assert row.attempts == 1


async def test_a_claim_from_another_tenant_is_refused(repo: Any) -> None:
    """The stored tenant is part of the identity, not decoration."""
    now = _now()
    await _claim(repo, "delivery-a", token="t-1", now=now, tenant_id="tenant-a")
    await repo.mark_failed("delivery-a", "t-1", "h5", now=now)

    other = await _claim(
        repo,
        "delivery-a",
        token="t-2",
        now=now,
        tenant_id="tenant-b",
        provider_key="email:tenant-b:delivery-a",
    )

    assert other.refusal is not None
    row = await repo.get("delivery-a")
    assert row is not None
    assert row.tenant_id == "tenant-a"


# --------------------------------------------------------------------------
# Stored shape and lifecycle
# --------------------------------------------------------------------------


async def test_the_record_holds_no_recipient_or_body(repo: Any, mongo_db: Any) -> None:
    """The durable store must not become a second home for customer mail."""
    now = _now()
    await _claim(repo, "delivery-a", token="t-1", now=now)
    await repo.mark_accepted("delivery-a", "t-1", "msg-1", now=now)

    raw = await mongo_db["email_deliveries"].find_one({"_id": "delivery-a"})
    assert raw is not None
    blob = " ".join(str(v) for v in raw.values()).lower()
    for forbidden in ("to@", "recipient", "subject", "body", "text", "html"):
        assert forbidden not in blob, f"delivery row leaked {forbidden!r}"


async def test_a_corrupt_stored_state_is_normalised_rather_than_returned(
    repo: Any, mongo_db: Any
) -> None:
    """A row written by a future/buggy version must not surface an invalid state."""
    now = _now()
    await _claim(repo, "delivery-a", token="t-1", now=now)
    await mongo_db["email_deliveries"].update_one(
        {"_id": "delivery-a"}, {"$set": {"state": "half-sent"}}
    )

    row = await repo.get("delivery-a")

    assert row is not None
    assert row.state in {"pending", "sending", "accepted", "failed", "unknown"}


async def test_a_stale_sending_attempt_is_taken_over_after_the_stale_window(
    repo: Any,
) -> None:
    now = _now()
    await _claim(repo, "delivery-a", token="t-1", now=now)

    too_soon = await _claim(repo, "delivery-a", token="t-2", now=now + timedelta(seconds=30))
    assert too_soon.refusal is not None

    takeover_at = now + STALE + timedelta(seconds=1)
    taken_over = await _claim(repo, "delivery-a", token="t-3", now=takeover_at)
    assert taken_over.refusal is None
    row = await repo.get("delivery-a")
    assert row is not None
    assert row.attempt_token == "t-3"
    assert row.attempts == 2


async def test_outcomes_are_fenced_by_the_attempt_token(repo: Any) -> None:
    """A slow execution must not overwrite the winner's outcome."""
    now = _now()
    await _claim(repo, "delivery-a", token="t-1", now=now)
    await _claim(repo, "delivery-a", token="t-2", now=now + STALE + timedelta(seconds=1))
    assert await repo.mark_accepted("delivery-a", "t-2", "msg-2", now=now)

    # The original, now-stale execution tries to report its own outcome.
    assert not await repo.mark_accepted("delivery-a", "t-1", "msg-1", now=now)
    assert not await repo.mark_failed("delivery-a", "t-1", "h5", now=now)
    assert not await repo.mark_unknown("delivery-a", "t-1", now=now)

    row = await repo.get("delivery-a")
    assert row is not None
    assert row.state == "accepted"
    assert row.provider_message_id == "msg-2"


async def test_the_delivery_id_is_the_primary_key(repo: Any, mongo_db: Any) -> None:
    """Uniqueness is structural, not an index somebody has to remember.

    Asserted by behaviour rather than by reading ``index_information``: a second
    insert of the same delivery id must be rejected by the database itself.
    """
    now = _now()
    await _claim(repo, "delivery-a", token="t-1", now=now)

    indexes = await mongo_db["email_deliveries"].index_information()
    assert "_id_" in indexes

    from pymongo.errors import DuplicateKeyError

    with pytest.raises(DuplicateKeyError):
        await mongo_db["email_deliveries"].insert_one({"_id": "delivery-a", "state": "pending"})
