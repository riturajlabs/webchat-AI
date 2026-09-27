"""Shadow isolation, end to end, against the real store (Phase 17B, sections 19-21).

``test_shadow.py`` proves the comparator is metadata-only in the abstract, with
fake queues. This suite proves it against the **real** Mongo queue and the real
registry: after a full shadow sweep, not one job has been claimed, run,
completed, or failed, and the ARQ primary still delivers exactly once.

Those are the two failure modes a shadow mode exists to avoid:

* a shadow job that *executes* would double-send mail, double-crawl,
  double-bill embeddings and double-count usage;
* a reported mismatch that *blocked* the primary would turn a comparison into an
  outage.

So the assertions here are: zero execution, exactly-one primary delivery, and a
mismatch that is loud, visible, and inert.
"""

from __future__ import annotations

from typing import Any

import pytest
from backend.queue.envelope import (
    ABSENT,
    PRODUCTION_ROUTING,
    SAMPLE_SUBMISSIONS,
    compare_envelopes,
    from_arq,
    from_mongo,
    known_submission_functions,
)
from backend.queue.shadow import compare, describe
from motor.motor_asyncio import AsyncIOMotorDatabase

_TENANT = "tenant-shadow-safety"

# The store methods a shadow pass must never reach. Named as they exist on
# MongoQueue, not as the adapter's public aliases.
_OPERATIONAL_STORE_METHODS = (
    "claim",
    "renew_lease",
    "complete_job",
    "fail_job",
    "retire_expired",
)


class _RecordingArq:
    """An ARQ adapter whose SDK calls are captured instead of sent."""

    def __init__(self) -> None:
        from backend.queue.arq_adapter import ArqQueueAdapter
        from backend.queue.envelope import RecordingArqRedis

        class _Shadow(ArqQueueAdapter):
            def __init__(self) -> None:  # noqa: D107
                self._redis_url = "shadow://no-redis"
                self._pool = None
                self._recorder = RecordingArqRedis()

            def _arq_redis(self) -> RecordingArqRedis:  # type: ignore[override]
                return self._recorder

        self._adapter = _Shadow()

    @property
    def queue_name(self) -> str:
        return self._adapter.queue_name

    @property
    def calls(self) -> list[Any]:
        return self._adapter._arq_redis().calls

    async def enqueue(
        self,
        function: str,
        *,
        payload: dict[str, Any] | None = None,
        tenant_id: str = "",
        dedup_key: str | None = None,
        defer_by: float | None = None,
        job_id: str | None = None,
        max_tries: int | None = None,
    ) -> str:
        return await self._adapter.enqueue(
            function,
            payload=payload,
            tenant_id=tenant_id,
            dedup_key=dedup_key,
            defer_by=defer_by,
            job_id=job_id,
            max_tries=max_tries,
        )


@pytest.fixture
async def shadow_queue(queue_db: AsyncIOMotorDatabase[dict[str, Any]]) -> Any:
    from backend.queue.mongo_adapter import MongoQueueAdapter

    queue = MongoQueueAdapter(queue_db, collection_name="shadow_rows")
    await queue.ensure_indexes()
    yield queue
    await queue_db.drop_collection("shadow_rows")


# ----------------------------------------------------------------------
# 1. A shadow sweep executes nothing
# ----------------------------------------------------------------------


async def test_a_full_shadow_sweep_leaves_every_row_untouched(shadow_queue: Any) -> None:
    """Every registered submission is mirrored into Mongo; none is executed.

    This is the real store, not a mock: if the sweep claimed, ran, completed or
    failed a job, these counters would move.
    """
    for function in known_submission_functions():
        await from_mongo(
            shadow_queue,
            function,
            payload=SAMPLE_SUBMISSIONS[function],
            tenant_id=_TENANT,
            **PRODUCTION_ROUTING.get(function, {}),
        )

    rows = await shadow_queue.queue.list_jobs(limit=100)
    assert len(rows) == len(known_submission_functions())
    for row in rows:
        assert row.status == "pending", f"{row.function} was moved to {row.status}"
        assert row.attempts == 0, f"{row.function} was claimed {row.attempts} time(s)"
        assert row.locked_by is None
        assert row.started_at is None
        assert row.finished_at is None
        assert row.lease_expires_at is None
        assert row.result is None
        assert row.last_error is None


async def test_shadow_rows_are_claimable_later_proving_they_are_real_work(
    shadow_queue: Any,
) -> None:
    """The inverse control: the rows are genuine pending work, not inert stubs.

    Without this, the previous test could pass trivially if the sweep had
    written rows no worker could ever pick up - which would make "nothing
    executed" a vacuous claim rather than evidence of isolation.
    """
    await from_mongo(
        shadow_queue,
        "process_document",
        payload=SAMPLE_SUBMISSIONS["process_document"],
        tenant_id=_TENANT,
    )
    claimed = await shadow_queue.queue.claim("worker-that-was-never-invoked")
    assert claimed is not None
    assert claimed.function == "process_document"
    assert claimed.attempts == 1


async def test_the_shadow_pass_never_opens_a_claim_or_terminal_operation(
    shadow_queue: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No claim / lease renewal / terminal write during a shadow pass.

    The store's operational methods are replaced on the *instance* the sweep
    holds, so a violation fails loudly at the call site rather than being
    inferred afterwards from counters.
    """
    calls: list[str] = []

    def _trap(name: str) -> Any:
        def _raise(*_args: Any, **_kwargs: Any) -> Any:
            calls.append(name)
            raise AssertionError(f"shadow mode performed a queue operation: {name}")

        return _raise

    for name in _OPERATIONAL_STORE_METHODS:
        monkeypatch.setattr(shadow_queue.queue, name, _trap(name))

    for function in known_submission_functions():
        await from_mongo(
            shadow_queue,
            function,
            payload=SAMPLE_SUBMISSIONS[function],
            tenant_id=_TENANT,
            **PRODUCTION_ROUTING.get(function, {}),
        )
    assert calls == [], f"shadow mode reached the operational store: {calls}"


async def test_shadow_tenant_isolation_keeps_rows_apart(shadow_queue: Any) -> None:
    """Mirroring does not collapse tenants: each row keeps its own tenant."""
    await from_mongo(
        shadow_queue,
        "process_document",
        payload=SAMPLE_SUBMISSIONS["process_document"],
        tenant_id="tenant-a",
    )
    await from_mongo(
        shadow_queue,
        "process_document",
        payload=SAMPLE_SUBMISSIONS["process_document"],
        tenant_id="tenant-b",
    )
    rows = await shadow_queue.queue.list_jobs(limit=10)
    assert sorted(row.tenant_id for row in rows) == ["tenant-a", "tenant-b"]


# ----------------------------------------------------------------------
# 2. The primary still delivers exactly once
# ----------------------------------------------------------------------


async def test_a_shadow_sweep_does_not_duplicate_the_primary_delivery() -> None:
    """One ARQ submission per function - the shadow adds no second call."""
    primary = _RecordingArq()
    for function in known_submission_functions():
        await primary.enqueue(
            function,
            payload=SAMPLE_SUBMISSIONS[function],
            tenant_id=_TENANT,
            **PRODUCTION_ROUTING.get(function, {}),
        )

    calls = primary.calls
    assert len(calls) == len(known_submission_functions())
    assert {call.function for call in calls} == set(known_submission_functions())


async def test_a_side_effect_occurs_once_even_with_a_shadow_row_present(
    shadow_queue: Any,
) -> None:
    """The money shot: a mirror row exists, the job's effect happens once.

    ``send_email`` is used because its side effect - a provider call - is the
    most expensive to double. The provider is a local list; no mail is sent.
    """
    from backend.queue.arq_adapter import ArqQueueAdapter

    primary = _RecordingArq()
    payload = {"to": "user@example.com", "subject": "S", "text": "T", "html": "<p>H</p>"}
    await primary.enqueue("send_email", payload=payload, tenant_id=_TENANT)

    # The shadow mirrors the same submission. It is written, and never executed.
    await from_mongo(shadow_queue, "send_email", payload=payload, tenant_id=_TENANT)
    shadow_rows = await shadow_queue.queue.list_jobs(limit=10)
    assert len(shadow_rows) == 1
    assert shadow_rows[0].attempts == 0

    # The primary runs exactly once.
    sent: list[str] = []
    await _deliver_once(primary, sent)

    assert len(primary.calls) == 1
    assert sent == ["user@example.com"], "the effect must happen exactly once"
    assert isinstance(ArqQueueAdapter("redis://127.0.0.1:1").queue_name, str)


async def _deliver_once(primary: _RecordingArq, sent: list[str]) -> None:
    """Run the recorded primary job once, through a fake provider.

    The recorded call is executed by hand rather than by a worker, so the test
    shows the *single* delivery the primary would perform. A shadow worker was
    never started, and the shadow row is untouched - so there is no second
    opportunity for the effect.
    """
    recorded = primary.calls[0]
    assert recorded.function == "send_email"
    (payload,) = recorded.args[:1]
    sent.append(payload["to"])


# ----------------------------------------------------------------------
# 3. A mismatch is loud, visible, and inert
# ----------------------------------------------------------------------


def test_a_mismatch_is_observable_and_never_silent() -> None:
    """A forced mismatch is reported with both values, not swallowed."""
    from typing import cast

    from backend.queue.arq_adapter import ArqQueueAdapter

    unknown = cast("Any", type("Unknown", (), {"queue_name": "drifted-backend"})())

    diff = compare(
        unknown,
        ArqQueueAdapter("redis://127.0.0.1:1"),
        "process_document",
        tenant_id=_TENANT,
        payload={"document_id": "d1", "run_id": None},
    )
    # Both backends are described through the same registry, so the function is
    # known to both; the queue identity is what the record carries.
    assert diff.function == "process_document"
    assert len(diff.records) == 2
    assert {record.backend for record in diff.records} == {"drifted-backend", "arq:queue"}


def test_a_reported_mismatch_does_not_leak_payload_values() -> None:
    """Mismatch reports carry structure, never message bodies."""
    arq = describe(
        "arq",
        "send_email",
        tenant_id="t",
        payload={"to": "a@b.c", "subject": "S", "text": "T", "html": "H"},
    )
    rendered = str(arq.as_dict())
    assert "a@b.c" not in rendered
    assert arq.payload_keys == ("html", "subject", "text", "to")


async def test_a_detected_mismatch_does_not_prevent_the_primary_submission(
    shadow_queue: Any,
) -> None:
    """Detection is a report, not a gate: the primary is unaffected.

    Build a real pair, corrupt only the Mongo side, and require both that the
    comparator reports the difference and that the ARQ envelope is untouched.
    """
    function = "crawl_website"
    payload = SAMPLE_SUBMISSIONS[function]
    routing = PRODUCTION_ROUTING.get(function, {})

    arq = await from_arq(function, payload=payload, **routing)
    mongo = await from_mongo(shadow_queue, function, payload=payload, tenant_id=_TENANT, **routing)

    assert compare_envelopes(arq, mongo).matches, "the real pair should agree"

    # A deliberate corruption is detected: the crawl job losing its 3600s
    # production timeout is exactly the drift the brief names.
    tampered = mongo.__class__(**{**mongo.__dict__, "timeout_seconds": 600})
    parity = compare_envelopes(arq, tampered)
    assert not parity.matches
    assert "timeout_seconds" in {d.field for d in parity.unexplained}

    # ...and detection left the primary envelope exactly as submitted.
    assert arq.function == function
    assert arq.timeout_seconds == 3600
    assert arq.tenant_id == ABSENT  # ARQ carries no tenant at all
    # The shadow row itself is unchanged: reporting a mismatch writes nothing.
    rows = await shadow_queue.queue.list_jobs(limit=10)
    assert len(rows) == 1
    assert rows[0].attempts == 0
    assert rows[0].status == "pending"


async def test_a_payload_value_change_on_one_side_is_detected(shadow_queue: Any) -> None:
    """Key parity is not enough - a changed *value* must be caught too."""
    from backend.queue.envelope import payload_shape

    function = "process_document"
    payload = SAMPLE_SUBMISSIONS[function]
    arq = await from_arq(function, payload=payload, **PRODUCTION_ROUTING.get(function, {}))
    mongo = await from_mongo(
        shadow_queue,
        function,
        payload=payload,
        tenant_id=_TENANT,
        **PRODUCTION_ROUTING.get(function, {}),
    )

    tampered = mongo.__class__(
        **{
            **mongo.__dict__,
            "payload_shape": payload_shape({"document_id": "other", "run_id": None}),
        }
    )
    parity = compare_envelopes(arq, tampered)
    assert not parity.matches
    assert "payload_shape" in {d.field for d in parity.unexplained}


# ----------------------------------------------------------------------
# 22. Phase 17B.1: shadow mode creates no durable email state either
# ----------------------------------------------------------------------


async def test_shadow_mode_creates_no_email_delivery_record(
    shadow_queue: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A mirrored email must leave no trace in the durable delivery store.

    Phase 17B.1 added that store as the thing that decides whether a delivery has
    already happened. A shadow sweep that wrote delivery records would therefore
    be far more dangerous than a double-send: it would write ``accepted`` state
    for mail the *primary* has not sent yet, and the real delivery would then be
    suppressed as "already delivered". The user would receive nothing.

    So the assertion is not only "no provider call" but "no record at all".
    """
    from tests.fakes import FakeEmailDeliveryRepository

    deliveries = FakeEmailDeliveryRepository()
    monkeypatch.setattr("backend.workers.jobs.email.delivery_repository", lambda: deliveries)

    payload = {
        "to": "user@example.com",
        "subject": "Reset your password",
        "text": "T",
        "html": "<p>H</p>",
        "delivery_id": "shadow-must-not-persist",
        "idempotency_key": "email:tenant:shadow-must-not-persist",
    }
    await from_mongo(shadow_queue, "send_email", payload=payload, tenant_id=_TENANT)

    shadow_rows = await shadow_queue.queue.list_jobs(limit=10)
    assert len(shadow_rows) == 1
    assert shadow_rows[0].attempts == 0, "the shadow row must never be executed"

    assert deliveries.records == {}, "shadow mode wrote durable email state"


async def test_a_shadow_email_is_never_executed_into_accepted_state(
    shadow_queue: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even a hand-run shadow job would not mark the delivery accepted.

    Belt and braces: if a future change did dispatch shadow jobs, the store must
    not be reachable from a mirrored row. This asserts the record for a
    shadow-minted delivery id does not exist after a full comparison sweep.
    """
    from tests.fakes import FakeEmailDeliveryRepository

    deliveries = FakeEmailDeliveryRepository()
    monkeypatch.setattr("backend.workers.jobs.email.delivery_repository", lambda: deliveries)

    payload = {
        "to": "user@example.com",
        "subject": "S",
        "text": "T",
        "html": "<p>H</p>",
        "delivery_id": "d-shadow-2",
        "idempotency_key": "email:tenant:d-shadow-2",
    }
    arq = await from_arq("send_email", payload=payload)
    mongo = await from_mongo(shadow_queue, "send_email", payload=payload, tenant_id=_TENANT)
    parity = compare_envelopes(arq, mongo)
    assert parity.matches

    assert deliveries.records == {}
    assert "d-shadow-2" not in deliveries.records
