"""Durable per-delivery email state (Phase 17B.1).

Why this collection exists
--------------------------
A provider idempotency key is only useful while the provider honours it, and it
tells you nothing about what already happened. Phase 17B shipped a key but no
record, so the worker could not answer the only question that matters after a
crash: *did this email already go out?* Re-running a job whose send had already
been accepted either duplicated the mail or - just as bad - looked identical to a
job that had never been attempted.

Each record is keyed by ``delivery_id``: the identity minted once at enqueue and
carried in the queue payload. It survives retries, lease reclaims and worker
restarts, and it is unique per logical delivery, which is what makes "one
delivery, one set of state transitions" enforceable.

State machine
-------------
::

    (absent) --claim--> sending --accept--> accepted      (terminal)
                            |            \\-unknown--> unknown
                            |                            |
                            \\-fail----------------------+--> failed
                                                          |
    accepted/failed/unknown --claim--> sending  (re-attempt, see below)

* ``accepted`` - the provider confirmed the send and its message id is recorded.
  **Terminal.** A re-delivery must never call the provider again; the recipient
  has the mail.
* ``failed`` - the provider *definitively* rejected the send (validation, 4xx).
  Nothing was sent, so re-attempting is safe and correct.
* ``unknown`` - the provider's answer was lost. The mail may already be in the
  inbox. A re-attempt is allowed **only** while the provider still honours the
  key, because then the provider collapses it; after that the record stops
  resending and the delivery needs a human. This is the state that makes the
  system honest instead of merely deduplicating: it is recorded as unknown
  rather than guessed at.
* ``sending`` - an attempt holds the record. A second execution may only take it
  over once the attempt looks abandoned, which is what keeps a crashed worker
  from stranding its delivery forever.

What is deliberately *not* stored
---------------------------------
No recipient address, subject or body. The record needs to answer "was this
delivery attempted, and what did the provider say", and none of that requires
message content. ``content_hash`` is a one-way fingerprint kept for debugging
("were these two attempts the same message?"), so the collection can be retained
and inspected without holding customer mail in a new place.

Fencing
-------
``attempt_token`` identifies one concrete attempt. Outcome writes are filtered
on it, so a slow execution whose lease was already taken over cannot overwrite
the result recorded by the execution that won - the same
``execution_version`` discipline the queue itself uses, applied to the delivery.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final, Literal, Protocol, cast

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

EmailDeliveryState = Literal["pending", "sending", "accepted", "failed", "unknown"]

#: Why a claim attempt was refused. Surfaced so the worker logs the real reason
#: instead of a generic "skipped", which is what makes an operator able to tell a
#: correct dedupe from a stuck delivery.
#:
#: - ``accepted``: the recipient already has this mail. Never resend.
#: - ``unknown_expired``: the outcome is unknowable *and* the provider will no
#:   longer collapse a retry, so a resend would be a real duplicate. Escalate.
#: - ``inflight``: another attempt holds it and is still within its window.
EmailDeliveryRefusal = Literal["accepted", "unknown_expired", "inflight"]

EMAIL_DELIVERY_STATES: Final[tuple[str, ...]] = (
    "pending",
    "sending",
    "accepted",
    "failed",
    "unknown",
)

#: States from which a new attempt may be started. ``unknown`` is absent on
#: purpose: it is time-gated separately, by the provider idempotency window,
#: because that - not the record - decides whether another send is safe.
_RETRYABLE_STATES: Final[tuple[str, ...]] = ("pending", "failed")


@dataclass(frozen=True)
class EmailDeliveryRecord:
    """The durable state of one logical email delivery."""

    delivery_id: str
    state: EmailDeliveryState
    tenant_id: str = ""
    provider_key: str = ""
    content_hash: str = ""
    provider_message_id: str | None = None
    attempts: int = 0
    attempt_token: str | None = None
    last_error_hash: str | None = None
    created_at: datetime | None = None
    last_attempt_at: datetime | None = None
    accepted_at: datetime | None = None
    #: When the provider stops honouring ``provider_key``. Past this point a
    #: resend of an ``unknown`` delivery could duplicate a delivered mail, so
    #: the record refuses to resend instead.
    provider_key_expires_at: datetime | None = None

    @property
    def is_delivered(self) -> bool:
        return self.state == "accepted"


@dataclass(frozen=True)
class EmailDeliveryClaim:
    """The outcome of trying to take ownership of a delivery.

    ``refusal`` is set when the claim was denied (and the record is unchanged);
    otherwise the caller owns the delivery for the duration of its attempt and
    must report exactly one outcome with this attempt's token.
    """

    record: EmailDeliveryRecord
    attempt_token: str
    previous_state: EmailDeliveryState
    refusal: EmailDeliveryRefusal | None = None

    @property
    def granted(self) -> bool:
        return self.refusal is None


class EmailDeliveryRepository(Protocol):
    """Durable, tenant-scoped state for logical email deliveries."""

    async def begin_attempt(
        self,
        delivery_id: str,
        *,
        tenant_id: str,
        provider_key: str,
        content_hash: str,
        attempt_token: str,
        now: datetime,
        provider_window: timedelta,
        stale_after: timedelta,
    ) -> EmailDeliveryClaim:
        """Take ownership of a delivery for one attempt, atomically.

        Grants the claim only from a state where another send is safe, so a
        delivered email is never re-sent and an ``unknown`` one is only retried
        while the provider still deduplicates it.
        """
        ...

    async def mark_accepted(
        self,
        delivery_id: str,
        attempt_token: str,
        provider_message_id: str | None,
        *,
        now: datetime,
    ) -> bool:
        """Record durable evidence that the provider accepted the send."""
        ...

    async def mark_failed(
        self, delivery_id: str, attempt_token: str, error_hash: str | None, *, now: datetime
    ) -> bool:
        """Record a definitive rejection. Nothing was sent; retry is safe."""
        ...

    async def mark_unknown(self, delivery_id: str, attempt_token: str, *, now: datetime) -> bool:
        """Record that the provider's answer was lost. The mail may be sent."""
        ...

    async def get(self, delivery_id: str) -> EmailDeliveryRecord | None:
        """Return the record for a delivery, if one exists."""
        ...


class MongoEmailDeliveryRepository:
    """MongoDB implementation of :class:`EmailDeliveryRepository`.

    Every state transition is a single conditional ``update_one`` whose filter
    carries the preconditions, so concurrent executions are serialised by the
    database rather than by an in-process lock. There is deliberately no
    read-then-write anywhere in this class: a check and a write separated by an
    await is exactly the TOCTOU that Phase 17B.1 exists to remove.
    """

    def __init__(
        self, db: AsyncIOMotorDatabase[Any], *, collection_name: str = "email_deliveries"
    ) -> None:
        self._collection = db[collection_name]

    async def ensure_indexes(self) -> None:
        """Create the supporting indexes. ``_id`` is already unique by default."""
        await self._collection.create_index("tenant_id")
        # Ops queries deliveries that never reached a terminal state; the partial
        # filter keeps the index to those few rows.
        await self._collection.create_index(
            [("state", 1), ("last_attempt_at", 1)],
            name="email_deliveries_open_by_state",
            partialFilterExpression={"state": {"$in": ["sending", "unknown"]}},
        )

    async def begin_attempt(
        self,
        delivery_id: str,
        *,
        tenant_id: str,
        provider_key: str,
        content_hash: str,
        attempt_token: str,
        now: datetime,
        provider_window: timedelta,
        stale_after: timedelta,
    ) -> EmailDeliveryClaim:
        # The claim itself is one atomic find-and-update: the pre-image tells us
        # the state we replaced, and no other execution can claim in between.
        #
        # Only the attempt-scoped fields are written here. The delivery identity
        # (tenant, provider key, content hash) and the key-expiry deadline were
        # written when the row was created and are deliberately NOT re-stated:
        # the filter below already requires the stored key to match the one this
        # attempt derived, and re-writing identity on every claim would let a
        # payload that disagrees with the row re-point it.
        previous = await self._collection.find_one_and_update(
            self._claim_filter(
                delivery_id=delivery_id,
                provider_key=provider_key,
                now=now,
                stale_after=stale_after,
            ),
            {
                "$set": {
                    "state": "sending",
                    "attempt_token": attempt_token,
                    "last_attempt_at": now,
                    "updated_at": now,
                },
                "$inc": {"attempts": 1},
            },
            upsert=False,
            return_document=ReturnDocument.BEFORE,
        )
        if previous is not None:
            return await self._granted(delivery_id, attempt_token, previous)

        # No claimable record matched. Either this delivery has never been
        # attempted (create it) or it is in a state that must not be overridden
        # (refuse). A single lookup tells us which.
        existing = await self._collection.find_one({"_id": delivery_id})
        if existing is not None:
            return self._refused(delivery_id, attempt_token, existing, now=now)
        try:
            await self._collection.insert_one(
                {
                    "_id": delivery_id,
                    "state": "sending",
                    "attempt_token": attempt_token,
                    "last_attempt_at": now,
                    "created_at": now,
                    "updated_at": now,
                    "tenant_id": tenant_id,
                    "provider_key": provider_key,
                    "content_hash": content_hash,
                    # Anchored here, at creation, and never renewed: this is how
                    # long the provider will keep collapsing a retry onto this
                    # first send. See `_claim_filter`.
                    "provider_key_expires_at": now + provider_window,
                    "attempts": 1,
                }
            )
        except DuplicateKeyError:
            # Another execution created the record between the lookup and the
            # insert. Its state decides, not ours - re-read and refuse if needed.
            raced = await self._collection.find_one({"_id": delivery_id})
            if raced is None:  # pragma: no cover - deleted underneath us
                return await self._granted(delivery_id, attempt_token, None)
            return self._refused(delivery_id, attempt_token, raced, now=now)
        return await self._granted(delivery_id, attempt_token, None)

    @staticmethod
    def _claim_filter(
        *, delivery_id: str, provider_key: str, now: datetime, stale_after: timedelta
    ) -> dict[str, Any]:
        """The preconditions under which starting an attempt is safe.

        ``delivery_id`` is in the filter, not merely in the update, so a claim is
        scoped to exactly one delivery. This is load-bearing: the ``$or`` below
        matches by *state*, and state alone is not unique - a delivery that was
        never attempted would otherwise match some other delivery's retryable
        row and mutate it, so one delivery's attempt could consume another's
        record and send its mail.

        The provider key is also required to match. The delivery id is the row's
        identity, so a payload that arrives claiming an existing id while
        deriving a *different* key is either corrupt or forged; letting it claim
        would re-point a real delivery at a different send. Refusing leaves the
        row intact.

        All window comparisons are evaluated by the database - never by Python
        that ran before the write.
        """
        return {
            "_id": delivery_id,
            "provider_key": provider_key,
            "$or": [
                {"state": {"$in": list(_RETRYABLE_STATES)}},
                # An `unknown` delivery may be retried only while the provider
                # still collapses the retry onto the original send. The deadline
                # is anchored to the first attempt, so this cannot be renewed.
                {"state": "unknown", "provider_key_expires_at": {"$gt": now}},
                # A `sending` record whose attempt stopped making progress
                # (crashed worker, lost lease) may be taken over - but only while
                # the provider will still collapse the retry onto the original
                # send. The crashed attempt may have died *after* the provider
                # accepted, and once the key window closes the provider stops
                # deduplicating, so a takeover then becomes a real second send.
                # Past the window this is the same dilemma as `unknown` and is
                # escalated instead.
                {
                    "state": "sending",
                    "last_attempt_at": {"$lt": now - stale_after},
                    "provider_key_expires_at": {"$gt": now},
                },
            ],
        }

    async def _granted(
        self, delivery_id: str, attempt_token: str, previous: dict[str, Any] | None
    ) -> EmailDeliveryClaim:
        return EmailDeliveryClaim(
            record=await self._require(delivery_id),
            attempt_token=attempt_token,
            previous_state=cast_state(previous.get("state")) if previous else "pending",
        )

    def _refused(
        self,
        delivery_id: str,
        attempt_token: str,
        existing: dict[str, Any],
        *,
        now: datetime,
    ) -> EmailDeliveryClaim:
        record = _to_record(existing)
        return EmailDeliveryClaim(
            record=record,
            attempt_token=attempt_token,
            previous_state=record.state,
            refusal=self._refusal_for(record, now),
        )

    @staticmethod
    def _refusal_for(record: EmailDeliveryRecord, now: datetime) -> EmailDeliveryRefusal:
        if record.state == "accepted":
            # Terminal: the recipient has this mail. Re-sending is the one
            # outcome that must never happen.
            return "accepted"
        # `unknown` is the explicit "the provider's answer was lost" state. A
        # stale `sending` record is the same dilemma by another route: the
        # attempt died without reporting, so the provider may already have sent.
        # In both cases, once the key window has closed the provider will no
        # longer collapse a retry, so a resend is a real duplicate and the only
        # honest options are escalate or send. We escalate.
        if record.state in ("unknown", "sending") and not key_window_open(record, now):
            return "unknown_expired"
        return "inflight"

    async def mark_accepted(
        self,
        delivery_id: str,
        attempt_token: str,
        provider_message_id: str | None,
        *,
        now: datetime,
    ) -> bool:
        result = await self._collection.update_one(
            {"_id": delivery_id, "state": "sending", "attempt_token": attempt_token},
            {
                "$set": {
                    "state": "accepted",
                    "provider_message_id": provider_message_id,
                    "accepted_at": now,
                    "updated_at": now,
                    "last_error_hash": None,
                }
            },
        )
        return result.matched_count == 1

    async def mark_failed(
        self,
        delivery_id: str,
        attempt_token: str,
        error_hash: str | None,
        *,
        now: datetime,
    ) -> bool:
        result = await self._collection.update_one(
            {"_id": delivery_id, "state": "sending", "attempt_token": attempt_token},
            {
                "$set": {
                    "state": "failed",
                    "last_error_hash": error_hash,
                    "updated_at": now,
                }
            },
        )
        return result.matched_count == 1

    async def mark_unknown(self, delivery_id: str, attempt_token: str, *, now: datetime) -> bool:
        result = await self._collection.update_one(
            {"_id": delivery_id, "state": "sending", "attempt_token": attempt_token},
            {
                "$set": {
                    "state": "unknown",
                    "updated_at": now,
                    "last_error_hash": "indeterminate",
                }
            },
        )
        return result.matched_count == 1

    async def get(self, delivery_id: str) -> EmailDeliveryRecord | None:
        raw = await self._collection.find_one({"_id": delivery_id})
        return _to_record(raw) if raw is not None else None

    async def _require(self, delivery_id: str) -> EmailDeliveryRecord:
        record = await self.get(delivery_id)
        if record is None:  # pragma: no cover - would mean the write vanished
            raise RuntimeError(f"email delivery {delivery_id} vanished after claim")
        return record


def key_window_open(record: EmailDeliveryRecord, now: datetime) -> bool:
    """Whether the provider still honours this delivery's key at ``now``."""
    if record.provider_key_expires_at is None:
        # No recorded deadline means the key's fate is unknown, so a resend
        # cannot be assumed safe. Refusing is the conservative choice.
        return False
    return record.provider_key_expires_at > now


def cast_state(value: Any) -> EmailDeliveryState:
    """Narrow a raw stored state, defaulting to ``pending`` for legacy rows."""
    return cast("EmailDeliveryState", value) if value in EMAIL_DELIVERY_STATES else "pending"


def _to_record(raw: dict[str, Any]) -> EmailDeliveryRecord:
    return EmailDeliveryRecord(
        delivery_id=str(raw["_id"]),
        # Normalise rather than trust: a row written by a newer or buggy version
        # must not surface a state this class cannot reason about, or an
        # unrecognised value would read as "not terminal" and invite a resend.
        state=cast_state(raw.get("state")),
        tenant_id=raw.get("tenant_id", ""),
        provider_key=raw.get("provider_key", ""),
        content_hash=raw.get("content_hash", ""),
        provider_message_id=raw.get("provider_message_id"),
        attempts=int(raw.get("attempts", 0)),
        attempt_token=raw.get("attempt_token"),
        last_error_hash=raw.get("last_error_hash"),
        created_at=raw.get("created_at"),
        last_attempt_at=raw.get("last_attempt_at"),
        accepted_at=raw.get("accepted_at"),
        provider_key_expires_at=raw.get("provider_key_expires_at"),
    )


__all__ = [
    "EMAIL_DELIVERY_STATES",
    "EmailDeliveryClaim",
    "EmailDeliveryRecord",
    "EmailDeliveryRefusal",
    "EmailDeliveryRepository",
    "EmailDeliveryState",
    "MongoEmailDeliveryRepository",
    "cast_state",
    "key_window_open",
]
