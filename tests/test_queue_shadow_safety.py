"""Safety invariants of the shadow-comparison path.

``backend/queue/shadow.py`` and ``backend/queue/telemetry.py`` are the two
production modules that decide whether a shadow comparison is *observational or
blocking*. Two properties matter more than any counter value:

1. A comparison problem must never break the enqueue the caller actually asked
   for. The ARQ write proceeds regardless of what the Mongo shadow copy thought,
   so the default path swallows and counts; only an explicit strict run raises.
2. Nothing on this path may retain payload plaintext. ``send_email`` payloads
   are rendered message bodies and crawl payloads are page metadata, so both
   modules record structure and bounded labels only.

The failure mode these tests exist to catch is a harness that silently compares
nothing: ``_differences`` returning ``()`` unconditionally, or a snapshot that
quietly grew a payload value, would both leave every other assertion here green
while making shadow mode useless.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest
from backend.queue.envelope import (
    ABSENT,
    ARQ_RETRY_POLICY,
    EnvelopeParity,
    NormalizedJobEnvelope,
    compare_envelopes,
    payload_shape,
)
from backend.queue.errors import InvalidPayloadError, UnknownFunctionError
from backend.queue.registry import known_names
from backend.queue.shadow import (
    COMPARED_FIELDS,
    ShadowRecord,
    _differences,
    compare,
    describe,
    shadow_plan,
)
from backend.queue.telemetry import (
    COUNTER_FIELDS,
    ShadowParityError,
    ShadowTelemetry,
    default_telemetry,
    render_summary,
    reset_default_telemetry,
    shadow_compare,
)

# A message body that must never survive into a snapshot, record or report.
_SECRET = "SUPER-SECRET-BODY-a41f9c2e7b"

_EMAIL_PAYLOAD: dict[str, Any] = {
    "to": "tenant-a@example.invalid",
    "subject": "quarterly report",
    "text": _SECRET,
    "html": f"<p>{_SECRET}</p>",
}


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------


def _envelope(
    backend: str,
    *,
    function: str = "send_email",
    tenant_id: str = ABSENT,
    request_id: str = ABSENT,
    logical_job_id: str = ABSENT,
    timeout_seconds: int = 300,
    max_tries: int = 3,
    defer_seconds: float = 0.0,
) -> NormalizedJobEnvelope:
    return NormalizedJobEnvelope(
        backend=backend,
        function=function,
        payload_keys=tuple(sorted(_EMAIL_PAYLOAD)),
        payload_shape=payload_shape(_EMAIL_PAYLOAD),
        tenant_id=tenant_id,
        request_id=request_id,
        logical_job_id=logical_job_id,
        timeout_seconds=timeout_seconds,
        max_tries=max_tries,
        defer_seconds=defer_seconds,
        retry_class=dict(ARQ_RETRY_POLICY),
    )


def _parity(*, drift: str | None = None) -> EnvelopeParity:
    """A real comparison of two envelopes, optionally with a real drift.

    ``tenant_id`` is documented in ``EXPLAINED_DIVERGENCES`` (ARQ carries no
    tenant by design); ``max_tries`` is not, so it is a genuine unexplained
    mismatch.
    """
    arq = _envelope("arq")
    if drift == "tenant_id":
        mongo = _envelope("mongo", tenant_id="tenant-a")
    elif drift == "max_tries":
        mongo = _envelope("mongo", max_tries=5)
    else:
        mongo = _envelope("mongo")
    return compare_envelopes(arq, mongo)


class _StubQueue:
    """A WorkerQueue stand-in that fails loudly on any real operation.

    ``shadow.compare()`` must only read ``queue_name``. If it ever claims,
    completes or enqueues, ``__getattr__`` turns that into a hard failure rather
    than a silent side effect.
    """

    def __init__(self, queue_name: str) -> None:
        self.queue_name = queue_name

    def __getattr__(self, name: str) -> Any:  # pragma: no cover - tripwire
        raise AssertionError(f"shadow.compare touched the queue: {name}")


# ----------------------------------------------------------------------
# 1. the observational guarantee: a broken comparison cannot break production
# ----------------------------------------------------------------------


async def test_a_failing_comparison_is_swallowed_and_counted() -> None:
    """A comparator bug must not become a production enqueue failure."""
    telemetry = ShadowTelemetry()

    async def boom() -> EnvelopeParity:
        raise RuntimeError("comparator exploded")

    assert await shadow_compare(telemetry, boom, "send_email") is None
    assert telemetry.counters["shadow_comparison_errors"] == 1
    # An error is not a mismatch and must not be laundered into one, or the
    # parity gate would read a broken comparator as adapter drift.
    assert telemetry.counters["shadow_envelopes_compared"] == 0
    assert telemetry.counters["shadow_envelope_mismatch"] == 0


async def test_a_failing_comparison_logs_only_the_exception_type(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The warning must stay log-safe: a type name, never the payload."""
    telemetry = ShadowTelemetry()

    async def boom() -> EnvelopeParity:
        raise RuntimeError(_SECRET)

    with caplog.at_level(logging.WARNING, logger="webchat_ai.mongo_queue"):
        await shadow_compare(telemetry, boom, "send_email")

    text = "\n".join(record.getMessage() for record in caplog.records)
    assert _SECRET not in text
    assert "RuntimeError" in text


async def test_strict_mode_raises_a_shadow_parity_error() -> None:
    """A gate run must fail loudly instead of reporting a clean comparison."""
    telemetry = ShadowTelemetry(strict=True)

    async def boom() -> EnvelopeParity:
        raise RuntimeError("comparator exploded")

    with pytest.raises(ShadowParityError):
        await shadow_compare(telemetry, boom, "send_email")


def test_strict_mode_raises_on_an_unexplained_mismatch() -> None:
    telemetry = ShadowTelemetry(strict=True)
    with pytest.raises(ShadowParityError) as excinfo:
        telemetry.record(_parity(drift="max_tries"))
    assert "max_tries" in str(excinfo.value)
    # Counted before raising: a strict gate that dies must still leave a trace.
    assert telemetry.counters["shadow_envelope_mismatch"] == 1
    assert telemetry.counters["shadow_envelope_mismatch_unexplained"] == 1


def test_non_strict_mode_records_an_unexplained_mismatch_instead_of_raising() -> None:
    telemetry = ShadowTelemetry()
    parity = telemetry.record(_parity(drift="max_tries"))
    assert parity.matches is False
    assert telemetry.counters["shadow_envelope_mismatch_unexplained"] == 1
    assert telemetry.mismatch_fields == {"max_tries": 1}
    assert telemetry.has_unexplained is True


def test_a_documented_divergence_is_not_treated_as_a_mismatch() -> None:
    """ARQ carries no tenant by design; that must not fail the parity gate."""
    telemetry = ShadowTelemetry()
    parity = telemetry.record(_parity(drift="tenant_id"))
    assert parity.matches is True
    assert parity.differences, "the divergence should still be reported"
    assert telemetry.counters["shadow_envelope_mismatch"] == 0
    assert telemetry.counters["shadow_envelope_mismatch_unexplained"] == 0
    assert telemetry.has_unexplained is False


def test_a_clean_comparison_counts_a_match() -> None:
    telemetry = ShadowTelemetry()
    assert telemetry.record(_parity()).matches is True
    assert telemetry.counters["shadow_envelopes_compared"] == 1
    assert telemetry.counters["shadow_envelope_match"] == 1
    assert telemetry.by_function["send_email"]["compared"] == 1
    assert telemetry.by_function["send_email"]["match"] == 1


async def test_a_successful_comparison_is_recorded_on_the_shared_collector() -> None:
    """The ordinary path: record on the operator's collector, return the parity."""
    telemetry = ShadowTelemetry()

    async def build() -> EnvelopeParity:
        return _parity()

    parity = await shadow_compare(telemetry, build, "send_email")
    assert parity is not None
    assert parity.matches is True
    assert telemetry.counters["shadow_envelopes_compared"] == 1
    assert telemetry.by_function["send_email"]["compared"] == 1


# ----------------------------------------------------------------------
# 2. the redaction guarantee: no payload plaintext on this path
# ----------------------------------------------------------------------


def test_a_snapshot_never_carries_payload_plaintext() -> None:
    """A snapshot is what an operator prints, so it must be safe to log."""
    telemetry = ShadowTelemetry()
    telemetry.record(_parity(drift="max_tries"))
    assert _SECRET not in json.dumps(telemetry.snapshot())


def test_a_parity_report_carries_shape_not_plaintext() -> None:
    """The other operator-facing surface: the full comparison report."""
    blob = json.dumps(_parity(drift="max_tries").as_dict())
    assert _SECRET not in blob
    # The salted length+digest descriptor stands in for the value.
    assert f"str(len={len(_SECRET)}" in blob


def test_a_shadow_record_never_carries_payload_plaintext() -> None:
    record = describe("arq", "send_email", tenant_id="tenant-a", payload=_EMAIL_PAYLOAD)
    blob = json.dumps(record.as_dict())
    assert _SECRET not in blob
    assert record.payload_keys == ("html", "subject", "text", "to")


def test_a_shadow_diff_never_carries_payload_plaintext() -> None:
    diff = compare(
        _StubQueue("arq"),
        _StubQueue("mongo"),
        "send_email",
        tenant_id="tenant-a",
        payload=_EMAIL_PAYLOAD,
    )
    assert _SECRET not in json.dumps(diff.as_dict())


# ----------------------------------------------------------------------
# 3. the counter namespace is closed
# ----------------------------------------------------------------------


def test_the_counter_namespace_cannot_be_poisoned_by_input() -> None:
    """A hostile function name must not be able to create a new metric."""
    telemetry = ShadowTelemetry()
    hostile = "'; DROP TABLE metrics --"
    telemetry.record(
        EnvelopeParity(
            function=hostile,
            arq=_envelope("arq"),
            mongo=_envelope("mongo"),
            differences=(),
        )
    )
    assert set(telemetry.counters) == set(COUNTER_FIELDS)
    # The arbitrary label is confined to the per-function bucket.
    assert hostile in telemetry.by_function
    assert hostile not in telemetry.counters


def test_a_blocked_side_effect_is_counted() -> None:
    """Shadow must never execute a real job; this counter is the tripwire."""
    telemetry = ShadowTelemetry()
    telemetry.record_blocked_side_effect("send_email")
    assert telemetry.counters["shadow_side_effect_blocked"] == 1


# ----------------------------------------------------------------------
# 4. a strict override still updates the operator's collector
# ----------------------------------------------------------------------


async def test_a_strict_override_still_updates_the_shared_collector() -> None:
    """A scoped strict run must stay visible on the operator's own snapshot."""
    telemetry = ShadowTelemetry(strict=False)

    async def build() -> EnvelopeParity:
        return _parity(drift="max_tries")

    with pytest.raises(ShadowParityError):
        await shadow_compare(telemetry, build, "send_email", strict=True)
    # The scoped collector borrowed the same dicts, so the operator's counters
    # and per-function buckets reflect the strict run.
    assert telemetry.counters["shadow_envelope_mismatch"] == 1
    assert telemetry.by_function["send_email"]["mismatch"] == 1


# ----------------------------------------------------------------------
# 5. snapshot + summary rendering
# ----------------------------------------------------------------------


def test_render_summary_reports_the_counters() -> None:
    telemetry = ShadowTelemetry()
    telemetry.record(_parity())
    telemetry.record(_parity(drift="max_tries"))
    summary = render_summary(telemetry.snapshot())
    for label in ("envelopes compared", "matched", "mismatched", "unexplained"):
        assert label in summary
    assert "send_email" in summary


def test_render_summary_of_an_empty_snapshot_has_no_per_function_block() -> None:
    summary = render_summary(ShadowTelemetry().snapshot())
    assert "per function:" not in summary
    assert "envelopes compared: 0" in summary


def test_reset_default_telemetry_gives_a_fresh_collector() -> None:
    reset_default_telemetry()
    try:
        default_telemetry().record_blocked_side_effect("ping")
        assert default_telemetry().counters["shadow_side_effect_blocked"] == 1
    finally:
        reset_default_telemetry()
    assert default_telemetry().counters["shadow_side_effect_blocked"] == 0


# ----------------------------------------------------------------------
# 6. shadow.describe validates through the real registry
# ----------------------------------------------------------------------


def test_describe_rejects_an_unknown_function() -> None:
    with pytest.raises(UnknownFunctionError):
        describe("arq", "not_a_real_job")


def test_describe_rejects_a_payload_the_registry_would_reject() -> None:
    """Proves describe() reuses the adapters' validation, not a copy of it."""
    with pytest.raises(InvalidPayloadError):
        describe("arq", "send_email", payload={"to": "a@b.invalid"})


def test_describe_accepts_a_valid_submission() -> None:
    record = describe("mongo", "crawl_website", tenant_id="t", payload={"crawl_job_id": "c1"})
    assert record.function == "crawl_website"
    assert record.payload_keys == ("crawl_job_id",)


# ----------------------------------------------------------------------
# 7. shadow.compare is metadata-only
# ----------------------------------------------------------------------


def test_compare_agrees_for_the_same_logical_submission() -> None:
    diff = compare(
        _StubQueue("arq"),
        _StubQueue("mongo"),
        "send_email",
        tenant_id="tenant-a",
        payload=_EMAIL_PAYLOAD,
    )
    assert diff.agrees is True
    assert diff.differences == ()
    assert {record.backend for record in diff.records} == {"arq", "mongo"}


def test_compare_issues_no_queue_operation() -> None:
    """The metadata-only guarantee, enforced by the _StubQueue tripwire."""
    diff = compare(_StubQueue("arq"), _StubQueue("mongo"), "ping")
    assert diff.agrees is True
    assert len(diff.records) == 2


def test_a_shadow_diff_is_serialisable() -> None:
    blob = compare(_StubQueue("arq"), _StubQueue("mongo"), "ping", tenant_id="t").as_dict()
    assert blob["agrees"] is True
    assert blob["function"] == "ping"
    assert blob["records"][0]["backend"] in {"arq", "mongo"}


# ----------------------------------------------------------------------
# 8. the drift detector itself
# ----------------------------------------------------------------------


def test_differences_names_exactly_the_fields_that_drifted() -> None:
    """A regression here (always returning ()) would make shadow mode a no-op."""
    base = ShadowRecord(
        backend="arq",
        function="send_email",
        tenant_id="t",
        dedup_key="k",
        payload_keys=("subject", "to"),
    )
    other = ShadowRecord(
        backend="mongo",
        function="send_email",
        tenant_id="DIFFERENT",
        dedup_key="DIFFERENT",
        payload_keys=("subject", "to", "text"),
    )
    diff = _differences((base, other))
    assert set(diff) == {"tenant_id", "dedup_key", "payload_keys"}
    # Deduplicated and order-stable, and every name is a compared field.
    assert len(diff) == len(set(diff))
    assert all(field in COMPARED_FIELDS for field in diff)


def test_differences_of_a_single_record_is_empty() -> None:
    one = ShadowRecord(
        backend="arq", function="ping", tenant_id="", dedup_key=None, payload_keys=()
    )
    assert _differences((one,)) == ()


def test_identical_records_agree() -> None:
    left = ShadowRecord(
        backend="arq", function="ping", tenant_id="t", dedup_key="k", payload_keys=("x",)
    )
    right = ShadowRecord(
        backend="mongo", function="ping", tenant_id="t", dedup_key="k", payload_keys=("x",)
    )
    assert _differences((left, right)) == ()


# ----------------------------------------------------------------------
# 9. the shadow sweep is exhaustive
# ----------------------------------------------------------------------


def test_the_shadow_plan_covers_every_registered_job() -> None:
    assert set(shadow_plan()) == set(known_names())
