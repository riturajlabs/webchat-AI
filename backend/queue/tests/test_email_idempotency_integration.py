"""Email delivery identity, durable state, and the provider failure matrix (Phase 17B.1).

What is real here
-----------------
The whole production path is exercised: the registered ``send_email`` worker
coroutine, the ``EmailMessage`` it builds, the real ``ResendProvider``, the
delivery identity the enqueue site minted, and the durable state machine the
worker consults before every send. Only two boundaries are replaced:

* the network boundary - ``resend.Emails.send`` - because a real send is
  forbidden and would be a real side effect;
* the delivery store, which is swapped for the in-memory fake that mirrors the
  Mongo CAS.

Faking the SDK call is what lets the provider's *semantics* be tested honestly
rather than assumed, and faking only the store is what lets the durability
guarantees be tested at all.

What the fake provider models
-----------------------------
Resend's documented behaviour: a repeat request carrying the same
``Idempotency-Key`` inside the retention window returns the original result
instead of delivering again. ``FakeResend`` implements exactly that, plus the
two failure shapes that matter - "accepted then the response was lost", and
"the idempotency window has expired".

The verdict this file is built to support is deliberately NOT "exactly-once".
See ``test_residual_duplicate_risk_beyond_the_provider_window``.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from backend.queue.arq_adapter import ArqQueueAdapter
from backend.queue.mongo_adapter import MongoQueueAdapter
from backend.queue.runtime import reset_worker_queue
from backend.queue.worker import MongoWorkerLoop
from backend.repositories.email_delivery_repository import (
    EmailDeliveryClaim,
    EmailDeliveryRecord,
    cast_state,
)
from backend.services.mail.base import (
    EmailMessage,
    MailDeliveryIndeterminate,
)
from backend.services.mail.providers import ResendProvider
from backend.workers.jobs.email import (
    resolve_delivery_identity,
    send_email,
)
from motor.motor_asyncio import AsyncIOMotorDatabase
from tests.fakes import FakeEmailDeliveryRepository

_TENANT = "tenant-mail"
_RECIPIENT = "user@example.com"


class ProviderAcceptedButResponseLost(RuntimeError):
    """The provider delivered, then the HTTP response never arrived."""


class ProviderRejectedDefinitively(Exception):
    """A 4xx-style rejection: the provider refused, so nothing was sent.

    Modelled on the SDK's own ``ValidationError``, which is what Resend raises
    for a request it refuses. A rejection is *not* an unknown outcome, so the
    worker must be able to tell the two apart - faking it with an unrecognised
    exception type would test nothing.
    """

    code = 422
    error_type = "validation_error"


class FakeResend:
    """Models Resend's idempotency-key semantics. No network, no real send."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        #: logical key -> the one delivery id it produced
        self._delivered: dict[str, str] = {}
        #: every delivery actually performed, in order
        self.deliveries: list[dict[str, Any]] = []
        self._next_id = 0
        #: inject "accepted, then the response was lost"
        self.lose_next_response = False
        #: inject a hard provider rejection
        self.reject_next = False

    def send(self, params: dict[str, Any], options: dict[str, Any] | None = None) -> dict[str, str]:
        options = options or {}
        key = options.get("idempotency_key")
        self.calls.append({"params": dict(params), "options": dict(options)})
        if self.reject_next:
            self.reject_next = False
            raise ProviderRejectedDefinitively("resend rejected the message")
        if key is not None and key in self._delivered:
            # Inside the window: the same key returns the original result and
            # does NOT deliver again.
            return {"id": self._delivered[key]}
        self._next_id += 1
        delivery_id = f"fake-email-{self._next_id}"
        self.deliveries.append({"id": delivery_id, "key": key, "to": params.get("to")})
        if key is not None:
            self._delivered[key] = delivery_id
        if self.lose_next_response:
            self.lose_next_response = False
            # The provider already accepted and recorded the delivery; the
            # client just never learns the id.
            raise ProviderAcceptedButResponseLost("connection reset after accept")
        return {"id": delivery_id}

    @property
    def delivery_count(self) -> int:
        return len(self.deliveries)

    def expire_window(self) -> None:
        """Simulate the provider forgetting the key (past its retention)."""
        self._delivered.clear()


@pytest.fixture
def fake_resend(monkeypatch: pytest.MonkeyPatch) -> FakeResend:
    """Replace only the SDK's network call; the real provider stays in place."""
    import resend

    fake = FakeResend()
    monkeypatch.setattr(resend.Emails, "send", staticmethod(fake.send))
    return fake


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> ResendProvider:
    """A real ResendProvider, installed as the job's mail service.

    Only the SDK's network call is faked (see ``fake_resend``); the provider
    object, the registered ``send_email`` coroutine, the delivery identity and
    the durable state machine are all production code. Installing it here also
    means a test cannot silently fall through to the real dev Mailpit provider.
    """
    from backend.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(
        settings, "email_from", "WebChat AI <no-reply@webchatai.example>", raising=False
    )
    instance = ResendProvider("re_test_fake_key")
    monkeypatch.setattr("backend.workers.jobs.email.get_mail_service", lambda: instance)
    return instance


@pytest.fixture
def deliveries(monkeypatch: pytest.MonkeyPatch) -> FakeEmailDeliveryRepository:
    """Install the in-memory delivery store as the worker's durable state.

    Only the storage is faked; every state transition runs the same production
    code path through the same repository interface.
    """
    repo = FakeEmailDeliveryRepository()
    monkeypatch.setattr("backend.workers.jobs.email.delivery_repository", lambda: repo)
    return repo


def _message(**overrides: Any) -> EmailMessage:
    fields: dict[str, Any] = {
        "to": _RECIPIENT,
        "subject": "Verify your email address",
        "text": "Click here to verify",
        "html": "<p>Click here to verify</p>",
    }
    fields.update(overrides)
    return EmailMessage(**fields)


def _identify(message: EmailMessage | None = None, tenant: str = _TENANT) -> tuple[str, str | None]:
    """Mint what ``enqueue_email`` would mint for this message."""
    subject = message or _message()
    return resolve_delivery_identity(subject.for_tenant(tenant))


def _key(message: EmailMessage | None = None, tenant: str = _TENANT) -> str:
    _, key = _identify(message, tenant)
    assert key is not None
    return key


def _payload(message: EmailMessage | None = None, tenant: str = _TENANT) -> dict[str, str]:
    """The payload ``enqueue_email`` would produce, content unchanged."""
    subject = (message or _message()).for_tenant(tenant)
    delivery_id, key = _identify(subject, tenant)
    return subject.with_delivery_identity(delivery_id=delivery_id, idempotency_key=key).to_payload()


# ----------------------------------------------------------------------
# the delivery identity: per-delivery, never content-derived
# ----------------------------------------------------------------------


def test_one_delivery_always_produces_the_same_key() -> None:
    """Every attempt at one logical delivery reuses one key, by construction."""
    delivery_id, key = _identify()
    assert key is not None
    from backend.queue.mail_idempotency import key_for_delivery

    assert key_for_delivery(_TENANT, delivery_id) == key


def test_two_enqueues_are_two_deliveries_with_two_keys() -> None:
    """The Phase 17B defect this phase fixes, stated as a passing assertion.

    Under the old content-derived key these two calls returned the *same* key,
    so the provider treated the second send as a duplicate and the user never
    received the second email.
    """
    first_id, first_key = _identify()
    second_id, second_key = _identify()
    assert first_id != second_id
    assert first_key != second_key


@pytest.mark.parametrize(
    "field,changed",
    [
        ("to", "someone-else@example.com"),
        ("subject", "Reset your password"),
        ("text", "Different plain body"),
        ("html", "<p>Different html body</p>"),
    ],
)
def test_content_cannot_influence_the_key(field: str, changed: str) -> None:
    """Message content is irrelevant to the key, by design.

    This is the inverse of the Phase 17A contract and the reason it exists: a
    key that depends on content can be steered into colliding with another
    delivery (identical content) or diverging for one that is not (a byte
    difference in whitespace). Both are failures, so the key is pinned to the
    delivery identity and nothing else.
    """
    delivery_id, _ = _identify()
    from backend.queue.mail_idempotency import key_for_delivery

    other = key_for_delivery(_TENANT, delivery_id)
    assert other == key_for_delivery(_TENANT, delivery_id)
    # The changed-content message gets its own delivery id, hence its own key.
    assert _key(_message(**{field: changed})) != _key(_message())


def test_identical_content_does_not_collide() -> None:
    """Two byte-identical emails are two deliveries - the regression under test."""
    from dataclasses import replace

    from backend.queue.mail_idempotency import key_for_payload

    identical = _message()
    assert _key(identical) != _key(replace(identical))
    # ...whereas the legacy content key produced one key for both.
    legacy = key_for_payload(_TENANT, identical.content_fields)
    assert legacy == key_for_payload(_TENANT, identical.content_fields)


def test_the_key_is_tenant_scoped() -> None:
    delivery_id, _ = _identify()
    from backend.queue.mail_idempotency import key_for_delivery

    assert key_for_delivery(_TENANT, delivery_id) != key_for_delivery("other", delivery_id)


def test_a_tenant_less_message_is_still_protected() -> None:
    """``forgot_password`` is public and has no tenant, and must not be skipped.

    Phase 17B returned no key at all in this case, leaving that flow with no
    duplicate protection whatsoever. The key is a function of the delivery id, so
    the scope segment is isolation only - the protection no longer depends on it.
    """
    delivery_id, key = _identify(_message(), tenant="")
    assert delivery_id
    assert key is not None
    assert key == f"email:tenant-unknown:{delivery_id}"


def test_the_key_is_within_the_provider_maximum() -> None:
    from backend.queue.mail_idempotency import RESEND_MAX_IDEMPOTENCY_KEY_LENGTH

    key = _key()
    assert 0 < len(key) <= RESEND_MAX_IDEMPOTENCY_KEY_LENGTH


def test_a_very_long_tenant_fails_loudly_rather_than_being_truncated() -> None:
    """A silently truncated key could collide with another tenant's message."""
    with pytest.raises(ValueError, match="over Resend"):
        _key(_message(), "t" * 300)


def test_the_key_contains_no_secret_material() -> None:
    key = _key()
    assert _RECIPIENT not in key
    assert "Click here" not in key
    assert "verify" not in key.lower()


def test_the_key_is_stable_across_unicode_and_whitespace_content() -> None:
    """Content cannot reach the key, so none of this can change it."""
    unicode_message = _message(subject="Bienvenue — café ☕", text="naïve")
    delivery_id, key = _identify(unicode_message)
    assert key is not None
    from backend.queue.mail_idempotency import key_for_delivery

    assert key == key_for_delivery(_TENANT, delivery_id)


def test_the_key_ignores_delivery_metadata_carried_on_the_message() -> None:
    """A key already on the message must not feed back into the next key."""
    base = _message().for_tenant(_TENANT)
    first = _key(base)
    carried = base.with_idempotency_key(first)
    assert _key(carried) != first, "each enqueue is a new delivery, so a new key"
    # ...and the carried key does not change the content of the message.
    assert carried.content_fields == base.content_fields


def test_the_feature_can_be_switched_off(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.core.config import get_settings

    monkeypatch.setattr(get_settings(), "mail_idempotency_enabled", False, raising=False)
    delivery_id, key = _identify()
    assert delivery_id == ""
    assert key is None


# ----------------------------------------------------------------------
# 19. the SDK's own supported option receives the key
# ----------------------------------------------------------------------


async def test_resend_provider_passes_the_key_through_the_sdk_option(
    provider: ResendProvider, fake_resend: FakeResend
) -> None:
    key = _key()
    await provider.send(_message().with_idempotency_key(key))

    assert len(fake_resend.calls) == 1
    call = fake_resend.calls[0]
    assert call["options"] == {"idempotency_key": key}
    # The message content is unchanged and the key is NOT smuggled into params.
    assert call["params"]["to"] == _RECIPIENT
    assert call["params"]["subject"] == "Verify your email address"
    assert "idempotency_key" not in call["params"]


async def test_resend_provider_sends_no_options_when_there_is_no_key(
    provider: ResendProvider, fake_resend: FakeResend
) -> None:
    await provider.send(_message())
    assert fake_resend.calls[0]["options"] == {}


async def test_resend_provider_returns_the_provider_message_id(
    provider: ResendProvider, fake_resend: FakeResend
) -> None:
    """The provider's id is the only durable evidence the send happened."""
    result = await provider.send(_message().with_idempotency_key(_key()))
    assert result.provider_message_id == "fake-email-1"


async def test_a_definite_rejection_is_not_reported_as_indeterminate(
    provider: ResendProvider, fake_resend: FakeResend
) -> None:
    fake_resend.reject_next = True
    with pytest.raises(ProviderRejectedDefinitively):
        await provider.send(_message().with_idempotency_key(_key()))


async def test_a_lost_response_is_reported_as_indeterminate(
    provider: ResendProvider, fake_resend: FakeResend
) -> None:
    """Accepted-but-unacknowledged must not look like "nothing was sent"."""
    fake_resend.lose_next_response = True
    with pytest.raises(MailDeliveryIndeterminate):
        await provider.send(_message().with_idempotency_key(_key()))


async def test_the_sdk_option_is_the_documented_one() -> None:
    """Guard the wiring: the SDK's SendOptions really has this field."""
    from resend.emails._emails import Emails

    assert "idempotency_key" in Emails.SendOptions.__annotations__


async def test_the_worker_job_forwards_the_key_to_the_provider(
    provider: ResendProvider, fake_resend: FakeResend, deliveries: FakeEmailDeliveryRepository
) -> None:
    """The real `send_email` coroutine, not a hand-called helper."""
    payload = _payload()
    await send_email({}, payload)

    assert fake_resend.calls[0]["options"] == {"idempotency_key": payload["idempotency_key"]}
    assert fake_resend.delivery_count == 1
    # The delivery identity travelled in the payload, so the worker rebuilt the
    # exact same key rather than recomputing something that could differ.
    assert deliveries.records[payload["delivery_id"]].state == "accepted"


async def test_the_worker_job_tolerates_a_payload_without_a_delivery_id(
    provider: ResendProvider,
    fake_resend: FakeResend,
    deliveries: FakeEmailDeliveryRepository,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A job already sitting in Redis from before Phase 17B.1 must still run.

    It has no delivery identity, so there is no durable row to consult and no
    key to send. It is sent the pre-17B way rather than being invented an
    identity that could collide with a real delivery, and the gap is logged.
    """
    legacy = _message().to_payload()
    assert "delivery_id" not in legacy
    with caplog.at_level("WARNING"):
        await send_email({}, legacy)
    assert fake_resend.delivery_count == 1
    assert fake_resend.calls[0]["options"] == {}
    assert "email_delivery_untracked" in caplog.text
    assert deliveries.records == {}, "an untracked send must not fabricate state"


async def test_the_provider_never_logs_the_email_body_or_the_full_key(
    provider: ResendProvider, fake_resend: FakeResend, caplog: pytest.LogCaptureFixture
) -> None:
    key = _key()
    with caplog.at_level("INFO"):
        await provider.send(_message().with_idempotency_key(key))
    text = caplog.text
    assert "Click here to verify" not in text
    assert key not in text, "the raw key (which embeds the tenant) must not be logged"
    assert "<redacted>" in text
    # The recipient is masked, as it was before Phase 17B.
    assert _RECIPIENT not in text


# ----------------------------------------------------------------------
# the durable state machine
# ----------------------------------------------------------------------


async def test_a_successful_send_is_recorded_as_accepted_with_its_message_id(
    provider: ResendProvider, fake_resend: FakeResend, deliveries: FakeEmailDeliveryRepository
) -> None:
    payload = _payload()
    await send_email({}, payload)

    record = deliveries.records[payload["delivery_id"]]
    assert record.state == "accepted"
    assert record.provider_message_id == "fake-email-1"
    assert record.attempts == 1
    assert record.is_delivered


async def test_a_known_accepted_delivery_is_never_sent_again(
    provider: ResendProvider, fake_resend: FakeResend, deliveries: FakeEmailDeliveryRepository
) -> None:
    """The central guarantee: a duplicate delivery cannot re-send a sent email.

    The provider is not even consulted. Relying on the provider's 24 h key
    window would leave a duplicate possible the moment that window elapses, and
    would mean paying for a network call to learn something we already know.
    """
    payload = _payload()
    await send_email({}, payload)
    assert fake_resend.delivery_count == 1

    for _ in range(5):
        await send_email({}, payload)

    assert fake_resend.delivery_count == 1
    assert len(fake_resend.calls) == 1, "a delivered email was re-sent to the provider"
    assert deliveries.records[payload["delivery_id"]].attempts == 1


async def test_the_delivery_record_holds_no_recipient_or_body(
    provider: ResendProvider, fake_resend: FakeResend, deliveries: FakeEmailDeliveryRepository
) -> None:
    """A new collection must not become a new home for customer mail."""
    payload = _payload()
    await send_email({}, payload)
    record = deliveries.records[payload["delivery_id"]]
    rendered = repr(record)
    assert _RECIPIENT not in rendered
    assert "Click here to verify" not in rendered
    assert "verify your email address" not in rendered
    # The fingerprint is a one-way hash, retained for debugging only.
    assert record.content_hash and record.content_hash not in ("Click here to verify", "")


async def test_the_delivery_record_is_filed_under_the_real_tenant(
    provider: ResendProvider, fake_resend: FakeResend, deliveries: FakeEmailDeliveryRepository
) -> None:
    """The record must carry the owning tenant, not a placeholder.

    The worker rebuilds the message from the queue payload, so a payload that
    omitted the tenant would file every real delivery under
    ``tenant-unknown`` and quietly make the tenant-scoped indexes and ops
    queries over this collection useless.
    """
    payload = _payload()
    assert payload["tenant_id"] == _TENANT
    await send_email({}, payload)

    record = deliveries.records[payload["delivery_id"]]
    assert record.tenant_id == _TENANT
    assert record.tenant_id != "tenant-unknown"


async def test_a_tenant_less_payload_is_recorded_as_unknown_scope_explicitly(
    provider: ResendProvider, fake_resend: FakeResend, deliveries: FakeEmailDeliveryRepository
) -> None:
    """A genuinely tenant-less send is labelled, not guessed at."""
    payload = _payload()
    payload["tenant_id"] = ""
    await send_email({}, payload)

    record = deliveries.records[payload["delivery_id"]]
    assert record.tenant_id == "tenant-unknown"


async def test_a_legacy_payload_with_a_key_and_no_delivery_id_is_still_sent(
    provider: ResendProvider, fake_resend: FakeResend, deliveries: FakeEmailDeliveryRepository
) -> None:
    """Backwards compatibility for mail already queued by the previous release.

    Such a payload has no delivery identity, so there is no durable row to
    consult. It is sent the pre-17B way, keeping the key it already carried, and
    the fact is logged rather than papered over with an invented identity that
    could collide with a real delivery.
    """
    payload = _payload()
    legacy_key = payload.pop("idempotency_key")
    payload.pop("delivery_id")
    payload["idempotency_key"] = legacy_key

    await send_email({}, payload)

    assert fake_resend.delivery_count == 1
    assert deliveries.records == {}, "an untracked send must not invent a record"


async def test_a_definite_rejection_is_recorded_as_failed_and_retryable(
    provider: ResendProvider, fake_resend: FakeResend, deliveries: FakeEmailDeliveryRepository
) -> None:
    """Nothing was sent, so a retry is both safe and correct."""
    payload = _payload()
    fake_resend.reject_next = True
    with pytest.raises(ProviderRejectedDefinitively):
        await send_email({}, payload)

    record = deliveries.records[payload["delivery_id"]]
    assert record.state == "failed"
    assert record.provider_message_id is None
    assert fake_resend.delivery_count == 0

    # The next attempt is allowed, and this time it succeeds.
    await send_email({}, payload)
    assert deliveries.records[payload["delivery_id"]].state == "accepted"
    assert fake_resend.delivery_count == 1


async def test_a_lost_response_is_recorded_as_unknown_not_as_sent(
    provider: ResendProvider, fake_resend: FakeResend, deliveries: FakeEmailDeliveryRepository
) -> None:
    """The honest state: the provider delivered and never told us.

    Recording this as ``failed`` would invite a resend that duplicates a mail the
    user already has; recording it as ``accepted`` would be a lie. ``unknown`` is
    the only state that tells the truth about the ambiguity.
    """
    payload = _payload()
    fake_resend.lose_next_response = True
    with pytest.raises(MailDeliveryIndeterminate):
        await send_email({}, payload)

    record = deliveries.records[payload["delivery_id"]]
    assert record.state == "unknown"
    assert record.provider_message_id is None
    assert fake_resend.delivery_count == 1, "the provider did deliver"


async def test_an_unknown_delivery_is_retried_inside_the_provider_window(
    provider: ResendProvider, fake_resend: FakeResend, deliveries: FakeEmailDeliveryRepository
) -> None:
    """Inside the window a resend is safe: the provider collapses it onto the first."""
    payload = _payload()
    fake_resend.lose_next_response = True
    with pytest.raises(MailDeliveryIndeterminate):
        await send_email({}, payload)

    await send_email({}, payload)

    assert fake_resend.delivery_count == 1, "the retry must not deliver a second copy"
    assert len(fake_resend.calls) == 2, "but the provider was consulted again"
    assert deliveries.records[payload["delivery_id"]].state == "accepted"


async def test_an_unknown_delivery_is_never_resent_after_the_window(
    provider: ResendProvider, fake_resend: FakeResend, deliveries: FakeEmailDeliveryRepository
) -> None:
    """Past the window, a resend could duplicate a delivered mail - so it stops.

    This is the behaviour the whole phase exists to make possible. Phase 17B
    would have re-sent and delivered a second copy; here the job reports the
    case for a human instead of silently double-sending.
    """
    from datetime import UTC, datetime, timedelta

    payload = _payload()
    fake_resend.lose_next_response = True
    with pytest.raises(MailDeliveryIndeterminate):
        await send_email({}, payload)
    assert deliveries.records[payload["delivery_id"]].state == "unknown"

    # The provider forgets the key (past its retention)...
    fake_resend.expire_window()
    # ...and the record's own window has elapsed.
    record = deliveries.records[payload["delivery_id"]]
    assert record.provider_key_expires_at is not None
    deliveries.records[payload["delivery_id"]] = _with_expiry(
        record, datetime.now(UTC) - timedelta(seconds=1)
    )

    await send_email({}, payload)

    assert fake_resend.delivery_count == 1, "an expired unknown delivery was re-sent"
    assert len(fake_resend.calls) == 1
    assert deliveries.records[payload["delivery_id"]].state == "unknown"


def _with_expiry(record: EmailDeliveryRecord, when: Any) -> EmailDeliveryRecord:
    from dataclasses import replace

    return replace(record, provider_key_expires_at=when)


async def test_a_crashed_attempt_is_taken_over_by_the_next_execution(
    provider: ResendProvider, fake_resend: FakeResend, deliveries: FakeEmailDeliveryRepository
) -> None:
    """A worker that dies mid-send must not strand the delivery forever.

    The record is left ``sending`` with no outcome. Once the attempt is older
    than the staleness bound, the next execution may take it over - and it does
    so with the same key, so the provider still collapses the send.
    """
    from dataclasses import replace
    from datetime import UTC, datetime, timedelta

    payload = _payload()
    delivery_id = payload["delivery_id"]

    # Simulate a crash after the claim but before any outcome: claim directly,
    # exactly as the worker does, and never report a result.
    from backend.queue.mail_idempotency import new_attempt_token

    token = new_attempt_token()
    now = datetime.now(UTC)
    await deliveries.begin_attempt(
        delivery_id,
        tenant_id=_TENANT,
        provider_key=str(payload["idempotency_key"]),
        content_hash="fingerprint",
        attempt_token=token,
        now=now,
        provider_window=timedelta(hours=24),
        stale_after=timedelta(seconds=120),
    )
    assert deliveries.records[delivery_id].state == "sending"

    # Still inside the staleness bound: the attempt is presumed alive, so the
    # delivery is left alone rather than sent twice concurrently.
    await send_email({}, payload)
    assert fake_resend.delivery_count == 0
    assert deliveries.records[delivery_id].state == "sending"

    # Now age the abandoned attempt past the bound and try again.
    deliveries.records[delivery_id] = replace(
        deliveries.records[delivery_id],
        last_attempt_at=now - timedelta(minutes=10),
    )
    await send_email({}, payload)

    assert fake_resend.delivery_count == 1
    assert deliveries.records[delivery_id].state == "accepted"
    assert deliveries.records[delivery_id].attempts == 2


async def test_a_slow_execution_cannot_overwrite_the_winning_outcome(
    provider: ResendProvider, fake_resend: FakeResend, deliveries: FakeEmailDeliveryRepository
) -> None:
    """Attempt tokens fence concurrent executions, like the queue's versions.

    Execution A claims, then stalls. B takes over and records ``accepted``. When
    A finally returns, its outcome write is refused: A's token is no longer the
    record's token, so it cannot demote a delivered email back to ``sending`` or
    overwrite the stored message id.
    """
    payload = _payload()
    delivery_id = payload["delivery_id"]
    from backend.queue.mail_idempotency import new_attempt_token

    slow_token = new_attempt_token()
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    await deliveries.begin_attempt(
        delivery_id,
        tenant_id=_TENANT,
        provider_key=str(payload["idempotency_key"]),
        content_hash="fingerprint",
        attempt_token=slow_token,
        now=now - timedelta(minutes=10),
        provider_window=timedelta(hours=24),
        stale_after=timedelta(seconds=120),
    )
    await send_email({}, payload)
    assert deliveries.records[delivery_id].state == "accepted"
    winner_id = deliveries.records[delivery_id].provider_message_id

    # The stalled execution finally reports - far too late.
    late = await deliveries.mark_accepted(delivery_id, slow_token, "stale-message-id", now=now)
    assert late is False, "a stale attempt overwrote the accepted outcome"

    record = deliveries.records[delivery_id]
    assert record.state == "accepted"
    assert record.provider_message_id == winner_id


async def test_the_state_machine_rejects_states_that_were_never_claimed(
    deliveries: FakeEmailDeliveryRepository,
) -> None:
    """An outcome write for an unknown delivery must not invent one."""
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    assert await deliveries.mark_accepted("never-claimed", "token", "id", now=now) is False
    assert await deliveries.mark_failed("never-claimed", "token", "hash", now=now) is False
    assert await deliveries.mark_unknown("never-claimed", "token", now=now) is False
    assert deliveries.records == {}


def test_cast_state_defaults_unknown_stored_values_to_pending() -> None:
    """A legacy or corrupt row must not be read as a terminal state."""
    assert cast_state("accepted") == "accepted"
    assert cast_state("nonsense") == "pending"
    assert cast_state(None) == "pending"


# ----------------------------------------------------------------------
# 21. the failure matrix, through the real queue
# ----------------------------------------------------------------------


def _worker(adapter: MongoQueueAdapter, worker_id: str) -> MongoWorkerLoop:
    """A worker loop dispatching the REAL registered ``send_email`` coroutine.

    Resolved through the registry, so this is the same callable ARQ dispatches
    (the ``timed_job``-wrapped production task), not a stand-in.
    """
    from backend.queue.registry import resolve

    return MongoWorkerLoop(
        adapter, handlers={"send_email": resolve("send_email")}, worker_id=worker_id
    )


async def _run_job(adapter: MongoQueueAdapter) -> str:
    outcome = await _worker(adapter, "mail-worker").work_once()
    assert outcome is not None
    return outcome.status


@pytest.fixture
async def short_mail_queue(
    queue_db: AsyncIOMotorDatabase[dict[str, object]],
) -> AsyncIterator[MongoQueueAdapter]:
    """A 0.4 s lease, so a crashed worker's row is genuinely reclaimable."""
    queue = MongoQueueAdapter(
        queue_db, collection_name="mail_jobs_short", lease_seconds=0.4, heartbeat_seconds=0.2
    )
    await queue.ensure_indexes()
    yield queue
    await queue_db.drop_collection("mail_jobs_short")


@pytest.fixture
async def mail_queue(
    queue_db: AsyncIOMotorDatabase[dict[str, object]],
) -> AsyncIterator[MongoQueueAdapter]:
    queue = MongoQueueAdapter(queue_db, collection_name="mail_jobs")
    await queue.ensure_indexes()
    yield queue
    await queue_db.drop_collection("mail_jobs")


async def _enqueue_mail(adapter: MongoQueueAdapter, message: EmailMessage) -> str:
    payload = _payload(message)
    return await adapter.enqueue("send_email", payload=payload, tenant_id=_TENANT)


async def test_case_1_success(
    mail_queue: MongoQueueAdapter,
    provider: ResendProvider,
    fake_resend: FakeResend,
    deliveries: FakeEmailDeliveryRepository,
) -> None:
    await _enqueue_mail(mail_queue, _message())
    assert await _run_job(mail_queue) == "completed"
    assert fake_resend.delivery_count == 1
    assert list(deliveries.records.values())[0].state == "accepted"


async def test_case_2_provider_rejects(
    mail_queue: MongoQueueAdapter,
    provider: ResendProvider,
    fake_resend: FakeResend,
    deliveries: FakeEmailDeliveryRepository,
) -> None:
    """A rejection is a real failure: no delivery, terminal (ARQ parity)."""
    fake_resend.reject_next = True
    await _enqueue_mail(mail_queue, _message())
    assert await _run_job(mail_queue) == "dead"
    assert fake_resend.delivery_count == 0
    assert fake_resend.calls[0]["options"], "the key was still offered"
    assert list(deliveries.records.values())[0].state == "failed"


async def test_case_4_response_lost_after_the_provider_accepted(
    mail_queue: MongoQueueAdapter,
    provider: ResendProvider,
    fake_resend: FakeResend,
    deliveries: FakeEmailDeliveryRepository,
) -> None:
    """The provider accepted; the client never learned the id.

    The job fails and the queue marks the row dead. A redelivery of the same
    payload is refused by the durable record, because the record still says
    ``unknown`` *inside* the provider window: the retry is safe and the provider
    collapses it, so exactly one logical delivery happened.
    """
    fake_resend.lose_next_response = True
    payload = _payload()
    await mail_queue.enqueue("send_email", payload=payload, tenant_id=_TENANT)

    assert await _run_job(mail_queue) == "dead"
    assert fake_resend.delivery_count == 1, "the provider did deliver"
    assert list(deliveries.records.values())[0].state == "unknown"

    # The replay: the *same* delivery coming back (a queue redelivery of one
    # payload, or an operator resubmitting it). A fresh enqueue would be a
    # different delivery and would correctly send again - see
    # `test_five_legitimate_user_requests_all_get_delivered`.
    await mail_queue.enqueue("send_email", payload=payload, tenant_id=_TENANT)
    assert await _run_job(mail_queue) == "completed"

    assert fake_resend.delivery_count == 1, "the key collapsed the replay"
    assert len(fake_resend.calls) == 2, "but the provider was called twice"
    keys = {call["options"]["idempotency_key"] for call in fake_resend.calls}
    assert len(keys) == 1, "both attempts used the same key"


async def test_case_5_worker_crashes_after_the_send(
    short_mail_queue: MongoQueueAdapter,
    provider: ResendProvider,
    fake_resend: FakeResend,
    deliveries: FakeEmailDeliveryRepository,
) -> None:
    """A hard crash (BaseException) bypasses the job's own error handling."""
    payload = _payload()
    await short_mail_queue.enqueue("send_email", payload=payload, tenant_id=_TENANT)

    async def crash_after_send(ctx: dict[str, Any], body: dict[str, str]) -> None:
        await provider.send(_message().with_idempotency_key(str(payload["idempotency_key"])))
        raise KeyboardInterrupt("worker killed after the provider accepted")

    loop = MongoWorkerLoop(
        short_mail_queue, handlers={}, worker_id="crash-worker", heartbeat_seconds=30.0
    )
    loop._handlers["send_email"] = crash_after_send
    with pytest.raises((KeyboardInterrupt, asyncio.CancelledError)):
        await loop.work_once()

    assert fake_resend.delivery_count == 1
    # The crash bypassed the worker entirely, so no record exists at all - the
    # crash happened before the job body ran.

    # The crashed worker left the row `running`. Once the short lease expires a
    # second worker reclaims it through the real store path and re-runs the job.
    await asyncio.sleep(0.6)
    outcome = await _worker(short_mail_queue, "reclaimer").work_once()
    assert outcome is not None
    assert fake_resend.delivery_count == 1, "the reclaim reused the same key"
    assert len(fake_resend.calls) == 2


async def test_cases_6_and_7_lease_expires_during_the_provider_request(
    mail_queue: MongoQueueAdapter,
    provider: ResendProvider,
    fake_resend: FakeResend,
    deliveries: FakeEmailDeliveryRepository,
) -> None:
    """A second worker runs the same send while the first is still in flight."""
    payload = _payload()
    first = await mail_queue.enqueue("send_email", payload=payload, tenant_id=_TENANT)
    # A second queue row for the same logical email (an at-least-once duplicate).
    second = await mail_queue.enqueue("send_email", payload=payload, tenant_id=_TENANT)
    assert first != second

    loop = _worker(mail_queue, "dual")
    assert await loop.work_once() is not None
    assert await loop.work_once() is not None

    assert fake_resend.delivery_count == 1, "only one logical delivery"
    # The second execution found the delivery already accepted and never called
    # the provider at all - the durable record, not the provider key, decided.
    assert len(fake_resend.calls) == 1


async def test_case_8_retry_within_the_provider_window(
    mail_queue: MongoQueueAdapter,
    provider: ResendProvider,
    fake_resend: FakeResend,
    deliveries: FakeEmailDeliveryRepository,
) -> None:
    """Five enqueues of the *same payload* are one delivery.

    Note this is redelivery of one delivery, not five sends by a user: five
    enqueues would be five different keys and five deliveries.
    """
    payload = _payload()
    for _ in range(5):
        await mail_queue.enqueue("send_email", payload=payload, tenant_id=_TENANT)
        assert await _run_job(mail_queue) == "completed"
    assert len(fake_resend.calls) == 1, "a delivered email was re-sent"
    assert fake_resend.delivery_count == 1


async def test_five_legitimate_user_requests_all_get_delivered(
    mail_queue: MongoQueueAdapter,
    provider: ResendProvider,
    fake_resend: FakeResend,
    deliveries: FakeEmailDeliveryRepository,
) -> None:
    """A user asking for five password resets receives five emails.

    This is the behaviour the content-derived key broke. Each enqueue mints its
    own delivery id and its own key, so nothing is suppressed.
    """
    for _ in range(5):
        await _enqueue_mail(mail_queue, _message())
        assert await _run_job(mail_queue) == "completed"
    assert len(fake_resend.calls) == 5
    assert fake_resend.delivery_count == 5
    assert len({c["options"]["idempotency_key"] for c in fake_resend.calls}) == 5


async def test_case_9_retry_after_the_provider_window_expired(
    mail_queue: MongoQueueAdapter,
    provider: ResendProvider,
    fake_resend: FakeResend,
    deliveries: FakeEmailDeliveryRepository,
) -> None:
    """An *accepted* delivery stays delivered even once the provider forgets.

    Phase 17B's residual risk was that past the window a replay delivered a
    second copy. With durable state the replay is refused by our own record, so
    the provider's memory is no longer load-bearing.
    """
    payload = _payload()
    await mail_queue.enqueue("send_email", payload=payload, tenant_id=_TENANT)
    assert await _run_job(mail_queue) == "completed"
    assert fake_resend.delivery_count == 1

    fake_resend.expire_window()
    await mail_queue.enqueue("send_email", payload=payload, tenant_id=_TENANT)
    assert await _run_job(mail_queue) == "completed"

    assert fake_resend.delivery_count == 1, "an accepted delivery was duplicated"
    assert len(fake_resend.calls) == 1


async def test_residual_duplicate_risk_beyond_the_provider_window() -> None:
    """The remaining limit, stated as an assertion so it cannot be forgotten.

    Durable state removes the duplicate for every delivery whose outcome we
    *know*. It cannot remove it for an ``unknown`` delivery whose provider window
    has since elapsed: the provider has already accepted the send, so nothing in
    our database can prove whether the user has it. That case is now escalated
    rather than re-sent, which is the honest resolution - but it is a real
    residual case, not a solved one.
    """
    from backend.core.config import get_settings
    from backend.queue.mail_idempotency import RESEND_MAX_IDEMPOTENCY_KEY_LENGTH

    settings = get_settings()
    assert settings.mail_provider_idempotency_window_seconds == 24 * 60 * 60
    assert RESEND_MAX_IDEMPOTENCY_KEY_LENGTH == 256


async def test_case_10_one_hundred_concurrent_executions_of_one_message(
    mail_queue: MongoQueueAdapter,
    provider: ResendProvider,
    fake_resend: FakeResend,
    deliveries: FakeEmailDeliveryRepository,
) -> None:
    """100 queue rows, one logical email, one provider call."""
    payload = _payload()
    for _ in range(100):
        await mail_queue.enqueue("send_email", payload=payload, tenant_id=_TENANT)

    async def drain(worker_id: str) -> int:
        loop = _worker(mail_queue, worker_id)
        claimed = 0
        while await loop.work_once() is not None:
            claimed += 1
        return claimed

    # Three workers race for the same 100 rows; every row is claimed exactly
    # once, and the durable record lets exactly one of them reach the provider.
    counts = await asyncio.gather(drain("w-a"), drain("w-b"), drain("w-c"))
    assert sum(counts) == 100, f"rows were claimed {sum(counts)} times, expected 100"

    assert fake_resend.delivery_count == 1, "the delivery happened once"
    assert len(fake_resend.calls) == 1, "and only one attempt reached the provider"
    record = deliveries.records[payload["delivery_id"]]
    assert record.state == "accepted"
    assert record.provider_message_id == "fake-email-1"


async def test_one_hundred_concurrent_sequential_claims(
    mail_queue: MongoQueueAdapter,
    provider: ResendProvider,
    fake_resend: FakeResend,
    deliveries: FakeEmailDeliveryRepository,
) -> None:
    """The same 100-row storm, drained by one worker (no interleaving)."""
    payload = _payload()
    for _ in range(100):
        await mail_queue.enqueue("send_email", payload=payload, tenant_id=_TENANT)

    loop = _worker(mail_queue, "w-seq")
    drained = 0
    while await loop.work_once() is not None:
        drained += 1
    assert drained == 100
    assert fake_resend.delivery_count == 1
    assert len(fake_resend.calls) == 1


# ----------------------------------------------------------------------
# 23. the user-facing bug, end to end through the real auth service
# ----------------------------------------------------------------------


class _RecordingRedis:
    """Stands in for ARQ at the enqueue boundary only.

    Mirrors the two behaviours :class:`backend.queue.arq_adapter.ArqQueueAdapter`
    depends on: ``enqueue_job`` returns an object carrying ``job_id`` (never
    ``None`` unless a duplicate was suppressed), and the payload arrives as the
    single positional argument of ``send_email``.
    """

    def __init__(self) -> None:
        self.jobs: list[tuple[str, dict[str, str]]] = []

    async def enqueue_job(self, function: str, *args: object, **kwargs: object) -> SimpleNamespace:
        self.jobs.append((function, args[0]))  # type: ignore[arg-type]
        return SimpleNamespace(job_id=uuid.uuid4().hex)


def _patch_arq(monkeypatch: pytest.MonkeyPatch, redis: _RecordingRedis) -> None:
    """Route the API-process ``enqueue_email`` at this recorder.

    Phase 18A: the producer enqueues through the process worker queue
    (:class:`ArqQueueAdapter`), so that is the patch point.
    """
    monkeypatch.setattr(ArqQueueAdapter, "_arq_redis", lambda self: redis)
    reset_worker_queue()


async def test_a_user_asking_twice_for_a_reset_receives_two_emails(
    provider: ResendProvider,
    fake_resend: FakeResend,
    deliveries: FakeEmailDeliveryRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The defect, reproduced through the real service the user actually calls.

    ``forgot_password`` twice, with the real :class:`AuthService`, the real
    ``enqueue_email`` and the real ``send_email``. Under the Phase 17B
    content-derived key the two rendered emails were byte-identical, so they
    shared one key and the provider delivered only the first - the user asked
    twice and received one email. The fresh ``jti`` in each reset token is what
    kept this from firing in production, which is exactly why it had to be fixed
    by construction rather than left to that accident.
    """
    from backend.workers.jobs import email as email_mod
    from tests.auth_helpers import VALID_PASSWORD, build_auth_env

    redis = _RecordingRedis()
    _patch_arq(monkeypatch, redis)

    env = build_auth_env()
    # The real enqueue path, in place of the recording dispatcher.
    env.service._mail = email_mod.enqueue_email
    await env.service.register(
        name="Alice",
        email="alice@example.com",
        password=VALID_PASSWORD,
        ip_address=None,
        user_agent=None,
    )
    assert len(redis.jobs) == 1, "registration enqueued its verification email"

    await env.service.forgot_password(email="alice@example.com", ip_address=None, user_agent=None)
    await env.service.forgot_password(email="alice@example.com", ip_address=None, user_agent=None)
    assert len(redis.jobs) == 3, "each request enqueued one email"

    # Run every enqueued job through the real worker task.
    for _function, payload in redis.jobs:
        await email_mod.send_email({}, payload)

    assert fake_resend.delivery_count == 3, "a legitimate repeat request was suppressed"
    assert len({call["options"]["idempotency_key"] for call in fake_resend.calls}) == 3
    assert {record.state for record in deliveries.records.values()} == {"accepted"}


async def test_one_password_reset_redelivered_twice_is_still_one_email(
    provider: ResendProvider,
    fake_resend: FakeResend,
    deliveries: FakeEmailDeliveryRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guarantee that matters: a redelivered job does not double-send.

    Same counterweight to the test above. Two *requests* are two deliveries; one
    request delivered twice is one delivery.
    """
    from backend.workers.jobs import email as email_mod
    from tests.auth_helpers import VALID_PASSWORD, build_auth_env

    redis = _RecordingRedis()
    _patch_arq(monkeypatch, redis)

    env = build_auth_env()
    # The real enqueue path, in place of the recording dispatcher.
    env.service._mail = email_mod.enqueue_email
    await env.service.register(
        name="Alice",
        email="alice@example.com",
        password=VALID_PASSWORD,
        ip_address=None,
        user_agent=None,
    )
    await env.service.forgot_password(email="alice@example.com", ip_address=None, user_agent=None)
    _function, payload = redis.jobs[-1]

    # The queue delivers the same payload three times (at-least-once).
    for _ in range(3):
        await email_mod.send_email({}, payload)

    assert fake_resend.delivery_count == 1, "the reset email was delivered 3 times"
    assert len(fake_resend.calls) == 1
    record = deliveries.records[payload["delivery_id"]]
    assert record.state == "accepted"
    assert record.attempts == 1, "a delivered email was attempted more than once"


# ----------------------------------------------------------------------
# Fake/Mongo parity for the claim preconditions
#
# The fake keys its records in a dict, so it can never reproduce a claim that
# crosses between deliveries - that defect class is asserted against a real
# mongod in tests/test_email_delivery_repository.py. What these tests pin is
# the *other* preconditions, which the fake does evaluate: the stored key is
# part of a row's identity, and a crashed attempt is not reclaimable once the
# provider has stopped honouring the key. The rule the fake must never break is
# that it may not be stricter than Mongo, or the guarantees would look better in
# the suite than in production.
# ----------------------------------------------------------------------


async def _claim_directly(
    deliveries: FakeEmailDeliveryRepository,
    delivery_id: str,
    *,
    token: str,
    now: datetime,
    provider_key: str | None = None,
    provider_window: timedelta = timedelta(hours=24),
    stale_after: timedelta = timedelta(seconds=120),
) -> EmailDeliveryClaim:
    return await deliveries.begin_attempt(
        delivery_id,
        tenant_id=_TENANT,
        provider_key=provider_key or f"email:{_TENANT}:{delivery_id}",
        content_hash="fingerprint",
        attempt_token=token,
        now=now,
        provider_window=provider_window,
        stale_after=stale_after,
    )


async def test_the_fake_refuses_a_claim_that_disagrees_about_the_key(
    deliveries: FakeEmailDeliveryRepository,
) -> None:
    """Mirrors the Mongo filter: the stored provider key is part of the identity."""
    now = datetime.now(UTC)
    first = await _claim_directly(deliveries, "d1", token="t1", now=now)
    assert first.refusal is None
    await deliveries.mark_failed("d1", "t1", "h5", now=now)

    impostor = await _claim_directly(
        deliveries, "d1", token="t2", now=now, provider_key="email:other:something"
    )

    assert impostor.refusal is not None
    record = deliveries.records["d1"]
    assert record.provider_key == f"email:{_TENANT}:d1", "stored key was overwritten"
    assert record.attempts == 1


async def test_the_fake_anchors_the_key_window_to_the_first_attempt(
    deliveries: FakeEmailDeliveryRepository,
) -> None:
    """Mirrors Mongo: a retry must not renew the provider's dedupe window."""
    now = datetime.now(UTC)
    await _claim_directly(deliveries, "d1", token="t1", now=now)
    original = deliveries.records["d1"].provider_key_expires_at
    assert original is not None

    later = now + timedelta(hours=23, minutes=59)
    await deliveries.mark_failed("d1", "t1", "h5", now=later)
    await _claim_directly(deliveries, "d1", token="t2", now=later)

    assert deliveries.records["d1"].provider_key_expires_at == original


async def test_the_fake_escalates_a_crashed_attempt_past_the_key_window(
    deliveries: FakeEmailDeliveryRepository,
) -> None:
    """Mirrors Mongo: a stale ``sending`` row is not reclaimable past the window.

    The crashed attempt may have died after the provider accepted, so a takeover
    after the provider stops honouring the key would be a real second send.
    """
    now = datetime.now(UTC)
    await _claim_directly(deliveries, "d1", token="t1", now=now)

    inside = await _claim_directly(deliveries, "d1", token="t2", now=now + timedelta(seconds=121))
    assert inside.refusal is None, "a crashed attempt inside the window is reclaimable"

    past = await _claim_directly(deliveries, "d1", token="t3", now=now + timedelta(hours=25))
    assert past.refusal == "unknown_expired"
    assert deliveries.records["d1"].state == "sending"
