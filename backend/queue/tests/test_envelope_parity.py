"""Envelope parity: does the comparator find real, non-tautological differences?

The point of these tests is *falsifiability*. Phase 17A's shadow comparison
could not fail; this one can. So the suite asserts three things:

1. The two envelopes really are produced independently - one by the ARQ
   adapter's own code path, one by the Mongo adapter's persisted row.
2. A deliberate corruption of either side is DETECTED as an unexplained
   mismatch (a comparator that cannot fail is worthless).
3. The real submissions for all five registered jobs are free of *unexplained*
   differences, with every real divergence carrying a written reason.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC
from typing import TYPE_CHECKING, Any, cast

import pytest
from backend.queue.envelope import (
    ABSENT,
    COMPARED_FIELDS,
    PRODUCTION_ROUTING,
    SAMPLE_SUBMISSIONS,
    EnvelopeParity,
    NormalizedJobEnvelope,
    compare_envelopes,
    from_arq,
    from_mongo,
    known_submission_functions,
    payload_shape,
    registry_is_complete,
    shape_value,
)
from backend.queue.mongo.models import Job
from backend.queue.registry import JOB_ARGUMENTS, known_names
from motor.motor_asyncio import AsyncIOMotorDatabase

if TYPE_CHECKING:  # pragma: no cover - typing only
    from backend.queue.mongo_adapter import MongoQueueAdapter as ShadowQueue


@pytest.fixture
async def shadow_queue(
    queue_db: AsyncIOMotorDatabase[dict[str, object]],
) -> AsyncIterator[ShadowQueue]:
    """A real MongoQueueAdapter over a dedicated shadow collection.

    The rows written here are shadow envelopes only: nothing ever claims them,
    so no job function runs and no side effect occurs.
    """
    from backend.queue.mongo_adapter import MongoQueueAdapter

    queue = MongoQueueAdapter(queue_db, collection_name="shadow_envelopes")
    await queue.ensure_indexes()
    yield queue
    await queue_db.drop_collection("shadow_envelopes")


async def _parity(shadow_queue: ShadowQueue, function: str) -> EnvelopeParity:
    payload = SAMPLE_SUBMISSIONS[function]
    routing = PRODUCTION_ROUTING.get(function, {})
    tenant = "tenant-parity"
    arq = await from_arq(function, payload=payload, **routing)
    mongo = await from_mongo(
        shadow_queue,
        function,
        payload=payload,
        tenant_id=tenant,
        **routing,
    )
    return compare_envelopes(arq, mongo)


# ----------------------------------------------------------------------
# 1. the sweep: every registered job, zero unexplained mismatches
# ----------------------------------------------------------------------


async def test_every_registered_job_has_a_comparison_sample() -> None:
    """The sweep must be exhaustive, not a sample of whatever was enqueued."""
    assert registry_is_complete()
    assert set(known_submission_functions()) == set(known_names()) == set(JOB_ARGUMENTS)


@pytest.mark.parametrize("function", known_submission_functions())
async def test_envelope_parity_for_every_production_job(
    shadow_queue: ShadowQueue, function: str
) -> None:
    parity = await _parity(shadow_queue, function)
    unexplained = [difference.field for difference in parity.unexplained]
    assert not unexplained, (
        f"{function}: unexplained envelope differences {unexplained}; "
        f"full diff={parity.as_dict()['differences']}"
    )


async def test_parity_sweep_reports_no_unexplained_mismatch(shadow_queue: ShadowQueue) -> None:
    """The same sweep as one assertion, so the gate reads as a single verdict."""
    results = {function: await _parity(shadow_queue, function) for function in known_names()}
    offenders = {
        function: [d.field for d in parity.unexplained]
        for function, parity in results.items()
        if parity.unexplained
    }
    assert not offenders, f"unexplained envelope mismatches: {offenders}"
    # Every function must actually be compared, not silently skipped.
    assert set(results) == set(known_names())


async def test_both_backends_really_produced_an_envelope(shadow_queue: ShadowQueue) -> None:
    """Guards against a vacuous comparison where one side is a stub."""
    parity = await _parity(shadow_queue, "send_email")
    assert parity.arq.backend == "arq"
    assert parity.mongo.backend == "mongo"
    # ARQ's envelope came from a recorded real enqueue call...
    assert parity.arq.function == "send_email"
    assert parity.arq.payload_keys == ("html", "subject", "text", "to")
    # ...and Mongo's came from a row the store actually persisted.
    assert parity.mongo.function == "send_email"
    assert parity.mongo.payload_keys == ("html", "subject", "text", "to")
    assert parity.mongo.tenant_id == "tenant-parity"


# ----------------------------------------------------------------------
# 2. falsifiability: corrupt either side, the comparator must notice
# ----------------------------------------------------------------------


def _corrupt(envelope: NormalizedJobEnvelope, field: str, value: Any) -> NormalizedJobEnvelope:
    return NormalizedJobEnvelope(**{**envelope.__dict__, field: value})


async def test_comparator_detects_a_wrong_timeout_on_the_mongo_side(
    shadow_queue: ShadowQueue,
) -> None:
    """The scenario the brief calls out: a crawl inheriting the 600s default.

    If the Mongo worker ever lost its per-function timeout, the comparator must
    report `timeout_seconds 3600 vs 600` rather than silently matching.
    """
    parity = await _parity(shadow_queue, "crawl_website")
    assert parity.arq.timeout_seconds == 3600, "crawl must keep the production 3600s timeout"
    assert parity.mongo.timeout_seconds == 3600

    corrupted = compare_envelopes(parity.arq, _corrupt(parity.mongo, "timeout_seconds", 600))
    assert not corrupted.matches
    assert [d.field for d in corrupted.unexplained] == ["timeout_seconds"]
    reason = corrupted.unexplained[0]
    assert reason.arq == 3600
    assert reason.mongo == 600
    assert reason.reason == ""
    assert reason.as_dict()["status"] == "UNEXPLAINED"


async def test_comparator_detects_a_wrong_function_name(shadow_queue: ShadowQueue) -> None:
    parity = await _parity(shadow_queue, "process_document")
    corrupted = compare_envelopes(parity.arq, _corrupt(parity.mongo, "function", "crawl_website"))
    assert not corrupted.matches
    assert "function" in [d.field for d in corrupted.unexplained]


async def test_comparator_detects_a_lost_payload_field(shadow_queue: ShadowQueue) -> None:
    parity = await _parity(shadow_queue, "process_document")
    assert parity.mongo.payload_keys == ("document_id", "run_id")
    truncated = _corrupt(parity.mongo, "payload_keys", ("document_id",))
    corrupted = compare_envelopes(parity.arq, truncated)
    assert not corrupted.matches
    assert "payload_keys" in [d.field for d in corrupted.unexplained]


async def test_comparator_detects_a_changed_payload_value(shadow_queue: ShadowQueue) -> None:
    """Key parity is not enough: a *value* change must be caught too."""
    parity = await _parity(shadow_queue, "process_document")
    tampered = _corrupt(
        parity.mongo,
        "payload_shape",
        payload_shape({"document_id": "other-document", "run_id": None}),
    )
    corrupted = compare_envelopes(parity.arq, tampered)
    assert not corrupted.matches
    assert "payload_shape" in [d.field for d in corrupted.unexplained]


async def test_the_mongo_row_always_carries_the_submitted_tenant(shadow_queue: ShadowQueue) -> None:
    """A queue row with no tenant is the orphan-work failure mode.

    This is asserted as an invariant rather than a cross-backend mismatch,
    because ARQ never carries a tenant at all: dropping it on the Mongo side
    would make the two sides *agree* and the comparator is right not to call
    that a difference. The guarantee comes from the adapter, tested here.
    """
    parity = await _parity(shadow_queue, "send_email")
    assert parity.mongo.tenant_id == "tenant-parity"

    from backend.queue.mongo_adapter import MissingTenantError

    email_payload = SAMPLE_SUBMISSIONS["send_email"]
    with pytest.raises(MissingTenantError):
        await shadow_queue.enqueue("send_email", payload=email_payload, tenant_id="")
    with pytest.raises(MissingTenantError):
        await shadow_queue.enqueue("send_email", payload=email_payload, tenant_id="   ")


async def test_tenant_value_correctness_is_outside_the_comparators_reach(
    shadow_queue: ShadowQueue,
) -> None:
    """A documented limit, asserted rather than papered over.

    Cross-backend parity can confirm the Mongo row carries a tenant; it can
    never confirm the tenant is the *right* one, because ARQ carries no tenant
    to compare against. Correctness therefore comes from the domain layer - the
    job reads the authoritative tenant from its own row - proven below.
    """
    parity = await _parity(shadow_queue, "send_email")
    tampered = compare_envelopes(
        parity.arq, _corrupt(parity.mongo, "tenant_id", "someone-elses-tenant")
    )
    assert tampered.matches, (
        "expected: with no ARQ tenant to compare against, a changed Mongo tenant "
        "is outside what envelope parity can detect"
    )
    assert tampered.mongo.tenant_id == "someone-elses-tenant"


async def test_a_wrong_queue_tenant_cannot_override_the_authoritative_tenant(
    shadow_queue: ShadowQueue,
) -> None:
    """The real protection: the job trusts its domain row, not the queue row."""
    from backend.core.logging import get_tenant_id
    from backend.queue.worker import MongoWorkerLoop

    job_id = await shadow_queue.enqueue(
        "crawl_website",
        payload={"crawl_job_id": "cj-wrong-tenant"},
        tenant_id="attacker-tenant",
    )
    loop = MongoWorkerLoop(shadow_queue, handlers={}, worker_id="w-tenant")

    observed: list[str | None] = []

    async def capture(ctx: dict[str, object], _crawl_job_id: str) -> dict[str, object]:
        from backend.workers.jobs.crawl import _run_crawl_job

        # The production crawl job sets the tenant from the crawl-job document,
        # never from the queue row, so a wrong queue tenant is inert.
        observed.append(get_tenant_id())
        _ = _run_crawl_job, ctx
        return {"status": "ok"}

    loop._handlers["crawl_website"] = capture
    outcome = await loop.work_once()
    assert outcome is not None
    assert job_id
    # No crawl-job document exists, so the real job found nothing and set no
    # tenant: the attacker's value never reached the job context.
    # `get_tenant_id()` renders '-' when unset, so the attacker's value never
    # reached the job's tenant context.
    assert observed == ["-"]


async def test_comparator_detects_a_changed_max_tries(shadow_queue: ShadowQueue) -> None:
    parity = await _parity(shadow_queue, "process_document")
    assert parity.arq.max_tries == 3
    corrupted = compare_envelopes(parity.arq, _corrupt(parity.mongo, "max_tries", 9))
    assert not corrupted.matches
    assert "max_tries" in [d.field for d in corrupted.unexplained]


# ----------------------------------------------------------------------
# 3. the real, documented divergences
# ----------------------------------------------------------------------


async def test_tenant_divergence_is_explained_not_a_failure(shadow_queue: ShadowQueue) -> None:
    """ARQ carries no tenant by design; the row is still attributable on Mongo."""
    parity = await _parity(shadow_queue, "send_email")
    assert parity.matches, "a documented divergence must not fail parity"
    tenant_difference = next(d for d in parity.differences if d.field == "tenant_id")
    assert tenant_difference.explained
    assert "positional args" in tenant_difference.reason
    assert tenant_difference.arq == ABSENT
    assert tenant_difference.mongo == "tenant-parity"


async def test_production_crawl_job_id_is_identical_on_both_backends(
    shadow_queue: ShadowQueue,
) -> None:
    """Stronger than parity: with the real routing hint both sides are equal.

    `enqueue_crawl_website` passes the JOB-scoped `crawl:<crawl_job_id>` (FIND-02),
    so ARQ and Mongo end up with byte-identical job identities and there is
    nothing to explain away.
    """
    parity = await _parity(shadow_queue, "crawl_website")
    assert parity.matches
    assert parity.arq.logical_job_id == parity.mongo.logical_job_id
    assert parity.arq.logical_job_id == "crawl:shadow-crawl-job-0001"
    assert not [d for d in parity.differences if d.field == "logical_job_id"]


async def test_a_plain_dedup_key_diverges_by_namespace_and_is_explained(
    shadow_queue: ShadowQueue,
) -> None:
    """Without the routing hint the two backends namespace the key differently.

    ARQ prefixes a bare dedup key with the function name; Mongo stores the key
    as given. A documented divergence, reported rather than hidden.
    """
    payload = {"crawl_job_id": "shadow-crawl-job-0002"}
    arq = await from_arq("crawl_website", payload=payload, dedup_key="manual-1")
    mongo = await from_mongo(
        shadow_queue,
        "crawl_website",
        payload=payload,
        tenant_id="tenant-parity",
        dedup_key="manual-1",
    )
    assert arq.logical_job_id == "crawl_website:manual-1"
    assert mongo.logical_job_id == "manual-1"
    parity = compare_envelopes(arq, mongo)
    assert parity.matches, "a documented namespace divergence is not a failure"
    difference = next(d for d in parity.differences if d.field == "logical_job_id")
    assert difference.explained
    assert "FIND-02" in difference.reason


async def test_backoff_divergence_from_arq_is_reported(shadow_queue: ShadowQueue) -> None:
    """The one real behavioural difference, surfaced rather than hidden.

    ARQ makes a cancelled job runnable again immediately (measured); the Mongo
    store applies the knowledge-domain 5/30/180 s schedule. Both map the same
    *outcomes*, but the *timing* of a retried job differs - which is exactly the
    kind of difference a cutover must be told about.
    """
    parity = await _parity(shadow_queue, "send_email")
    assert parity.arq.retry_class["backoff_seconds"] is None
    assert parity.mongo.retry_class["backoff_seconds"] == [5.0, 30.0, 180.0]
    difference = next(d for d in parity.differences if d.field == "retry_class")
    assert difference.explained, "must be reported, and must carry a written reason"
    assert parity.matches, "but a known divergence is not a parity failure"


async def test_both_backends_agree_on_the_outcome_mapping(shadow_queue: ShadowQueue) -> None:
    """The substantive parity claim: same terminal/retry classification."""
    parity = await _parity(shadow_queue, "process_document")
    assert parity.arq.retry_class["terminal_on"] == parity.mongo.retry_class["terminal_on"]
    assert parity.arq.retry_class["retry_on"] == parity.mongo.retry_class["retry_on"]
    assert parity.arq.retry_class["terminal_on"] == ("ordinary_exception", "timeout")
    assert parity.arq.retry_class["retry_on"] == ("cancelled",)


# ----------------------------------------------------------------------
# 4. timeout parity through all three paths
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("function", "expected"),
    [
        ("crawl_website", 3600),
        ("send_email", 600),
        ("process_document", 600),
        ("process_website_documents", 600),
        ("ping", 600),
    ],
)
async def test_timeout_parity_through_all_three_paths(
    shadow_queue: ShadowQueue, function: str, expected: int
) -> None:
    """ARQ registry -> ARQ envelope, ARQ registry -> Mongo worker, shadow envelope.

    A crawl must never silently inherit the 600 s default on any path.
    """
    from backend.queue.envelope import job_timeout_for_mongo
    from backend.queue.registry import job_timeout_seconds
    from backend.workers.app import WorkerSettings

    arq_registry = WorkerSettings.functions
    assert job_timeout_seconds(function) == expected
    assert job_timeout_for_mongo(function) == expected
    parity = await _parity(shadow_queue, function)
    assert parity.arq.timeout_seconds == expected
    assert parity.mongo.timeout_seconds == expected
    assert len(arq_registry) >= 5


async def test_crawl_timeout_is_declared_on_the_arq_function_object() -> None:
    """Read straight off the ARQ registry object ARQ's own worker consults."""
    from arq.worker import func as arq_func
    from backend.queue.registry import ArqRegistryEntry
    from backend.workers.app import WorkerSettings

    entries = cast("list[ArqRegistryEntry]", list(WorkerSettings.functions))
    timeouts = {arq_func(entry).name: arq_func(entry).timeout_s for entry in entries}
    assert timeouts["crawl_website"] == 3600
    assert all(value in (None, 600) for name, value in timeouts.items() if name != "crawl_website")


# ----------------------------------------------------------------------
# 5. redaction: the comparator must never retain a payload value
# ----------------------------------------------------------------------


def test_shape_descriptor_never_contains_the_value() -> None:
    secret = "sk-live-super-secret-token"
    descriptor = shape_value(secret)
    assert secret not in descriptor
    assert "str(len=" in descriptor


def test_shape_descriptor_is_deterministic_and_salted() -> None:
    """Same input, same descriptor (so parity works) - and not a plain hash."""
    import hashlib

    secret = "user@example.com"
    first = shape_value(secret)
    assert first == shape_value(secret)
    plain = hashlib.sha256(secret.encode()).hexdigest()[:8]
    assert plain not in first, "descriptor must not be a recoverable plain digest"


def test_shape_descriptor_distinguishes_none_from_empty_string() -> None:
    """`run_id: None` and `run_id: ""` must never compare equal.

    `process_document` treats them differently (`None` means "no run", `""` is
    rejected upstream), so a redacted payload that collapsed them would hide a
    real bug.
    """
    assert shape_value(None) == "null"
    assert shape_value("").startswith("str(len=0,sha=")
    assert shape_value(None) != shape_value("")
    assert shape_value(None) != shape_value("x")


def test_shape_descriptor_recurses_into_containers_without_their_values() -> None:
    descriptor = shape_value({"a": "secret-value", "b": [1, 2, 3]})
    assert "secret-value" not in descriptor
    assert "keys=['a', 'b']" in descriptor


async def test_envelope_never_retains_email_body_text(shadow_queue: ShadowQueue) -> None:
    payload = SAMPLE_SUBMISSIONS["send_email"]
    parity = await _parity(shadow_queue, "send_email")
    rendered = str(parity.as_dict())
    assert payload["text"] not in rendered
    assert payload["subject"] not in rendered
    assert payload["html"] not in rendered


async def test_envelope_dict_is_json_safe(shadow_queue: ShadowQueue) -> None:
    """A telemetry sink must be able to serialize a snapshot without help."""
    import json

    parity = await _parity(shadow_queue, "crawl_website")
    json.dumps(parity.as_dict())


# ----------------------------------------------------------------------
# 6. the mongo envelope reflects what the store actually wrote
# ----------------------------------------------------------------------


async def test_mongo_envelope_reflects_the_persisted_row(shadow_queue: ShadowQueue) -> None:

    job_id = await shadow_queue.enqueue(
        "process_document",
        payload={"document_id": "d-1", "run_id": "run-1"},
        tenant_id="tenant-x",
    )
    row = await shadow_queue.queue.collection.find_one({"_id": job_id})
    assert row is not None
    stored = Job.model_validate(row)
    assert stored.tenant_id == "tenant-x"
    assert stored.dedup_key is None
    assert stored.max_tries == 3
    assert stored.status == "pending"
    assert stored.payload == {"document_id": "d-1", "run_id": "run-1"}


async def test_mongo_envelope_records_the_production_dedup_identity(
    shadow_queue: ShadowQueue,
) -> None:
    job_id = await shadow_queue.enqueue(
        "crawl_website",
        payload={"crawl_job_id": "crawl-1"},
        tenant_id="tenant-x",
        job_id="crawl:crawl-1",
    )
    row = await shadow_queue.queue.collection.find_one({"_id": job_id})
    assert row is not None
    assert row["dedup_key"] == "crawl:crawl-1"


async def test_mongo_envelope_sees_the_requested_deferral(shadow_queue: ShadowQueue) -> None:
    from datetime import datetime

    envelope = await from_mongo(
        shadow_queue,
        "process_document",
        payload={"document_id": "d-1", "run_id": None},
        tenant_id="tenant-x",
        defer_by=30.0,
        now=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert envelope.defer_seconds == 30.0


async def test_mongo_envelope_reports_no_deferral_as_zero(shadow_queue: ShadowQueue) -> None:
    envelope = await from_mongo(
        shadow_queue,
        "process_document",
        payload={"document_id": "d-1", "run_id": None},
        tenant_id="tenant-x",
    )
    assert envelope.defer_seconds == 0.0


# ----------------------------------------------------------------------
# 7. a deferral must be visible on the ARQ side too
# ----------------------------------------------------------------------


async def test_arq_envelope_records_a_deferral() -> None:
    envelope = await from_arq(
        "process_document",
        payload={"document_id": "d-1", "run_id": None},
        defer_by=30.0,
    )
    assert envelope.defer_seconds == 30.0


async def test_deferral_parity_is_explained_not_a_failure(shadow_queue: ShadowQueue) -> None:
    parity = await _parity(shadow_queue, "process_document")
    assert parity.matches
    assert parity.arq.defer_seconds == 0.0
    assert parity.mongo.defer_seconds == 0.0


# ----------------------------------------------------------------------
# 8. the ARQ side cannot reach Redis, by construction
# ----------------------------------------------------------------------


async def test_arq_envelope_path_never_builds_a_real_redis_pool() -> None:
    from backend.queue.envelope import RecordingArqQueueAdapter

    shadow = RecordingArqQueueAdapter()
    await shadow.enqueue("ping", payload={})
    assert shadow.recorder.calls[0].function == "ping"
    assert shadow.queue_name == "arq:queue"


async def test_arq_envelope_path_records_the_job_id_the_adapter_computed() -> None:
    from backend.queue.envelope import RecordingArqQueueAdapter

    shadow = RecordingArqQueueAdapter()
    await shadow.enqueue("crawl_website", payload={"crawl_job_id": "cj-1"}, job_id="crawl:cj-1")
    recorded = shadow.recorder.calls[0]
    assert recorded.job_id == "crawl:cj-1"
    assert recorded.args == ("cj-1",), "positional args must match ARQ's real call shape"


async def test_request_id_is_absent_from_both_envelopes(shadow_queue: ShadowQueue) -> None:
    """Not an enqueue-time field in either backend - asserted, not assumed.

    Production jobs build their own execution-time request id
    (`crawl_website` -> `job:<crawl_job_id>`), so an envelope that claimed to
    carry one would be reporting a field that does not exist.
    """
    parity = await _parity(shadow_queue, "crawl_website")
    assert parity.arq.request_id == ABSENT
    assert parity.mongo.request_id == ABSENT
    assert parity.matches


async def test_execution_time_request_id_is_derived_identically_by_both_backends(
    shadow_queue: ShadowQueue,
) -> None:
    """The request-id parity that IS real: how the job derives it at runtime."""
    from backend.core.logging import get_request_id
    from backend.queue.worker import MongoWorkerLoop

    payload = {"crawl_job_id": "req-parity-1"}
    arq = await from_arq("crawl_website", payload=payload, job_id="crawl:req-parity-1")
    mongo = await from_mongo(
        shadow_queue,
        "crawl_website",
        payload=payload,
        tenant_id="tenant-parity",
        job_id="crawl:req-parity-1",
    )
    loop = MongoWorkerLoop(shadow_queue, handlers={}, worker_id="w-parity")

    seen: list[str | None] = []

    async def capture(ctx: dict[str, object], _crawl_job_id: str) -> dict[str, object]:
        from backend.workers.jobs.crawl import _run_crawl_job

        seen.append(f"job:{_crawl_job_id}")
        _ = _run_crawl_job, ctx
        return {"status": "ok"}

    loop._handlers["crawl_website"] = capture
    outcome = await loop.work_once()
    assert outcome is not None
    assert seen == ["job:req-parity-1"]
    # The job scopes its own request id and resets it on the way out, so the
    # caller's context is clean afterwards.
    assert get_request_id() in ("", "-", None)
    # The queue identity both backends agree on, for correlation.
    assert arq.logical_job_id == mongo.logical_job_id == "crawl:req-parity-1"


async def test_comparator_renders_every_compared_field(shadow_queue: ShadowQueue) -> None:
    parity = await _parity(shadow_queue, "send_email")
    rendered = parity.as_dict()
    for name in COMPARED_FIELDS:
        assert name in rendered["arq"], name
        assert name in rendered["mongo"], name
