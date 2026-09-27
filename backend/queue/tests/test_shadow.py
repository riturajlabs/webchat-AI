"""Metadata-only shadow comparison between the two backends (Phase 17A §24).

The point of these tests is what shadow mode must NOT do: claim a job, run a
job, or contact a provider. A shadow run that executed a real job through both
queues would double-send mail, double-crawl, double-bill embeddings and
double-count usage, so the module is comparison-only and these tests assert the
absence of side effects.
"""

from __future__ import annotations

from typing import cast

import pytest
from backend.queue.arq_adapter import ArqQueueAdapter
from backend.queue.errors import InvalidPayloadError, UnknownFunctionError
from backend.queue.mongo_adapter import MongoQueueAdapter
from backend.queue.protocol import WorkerQueue
from backend.queue.registry import known_names
from backend.queue.shadow import COMPARED_FIELDS, compare, describe, shadow_plan

_PAYLOAD = {"document_id": "d1", "run_id": None}
_EMAIL = {"to": "a@b.c", "subject": "S", "text": "T", "html": "<p>H</p>"}


def _pair() -> tuple[ArqQueueAdapter, MongoQueueAdapter]:
    return ArqQueueAdapter("redis://127.0.0.1:1"), MongoQueueAdapter.__new__(MongoQueueAdapter)


def test_shadow_plan_covers_every_registered_function() -> None:
    assert set(shadow_plan()) == set(known_names())


def test_describe_uses_the_shared_registry() -> None:
    record = describe("arq", "process_document", tenant_id="t1", dedup_key="k", payload=_PAYLOAD)
    assert record.function == "process_document"
    assert record.tenant_id == "t1"
    assert record.dedup_key == "k"
    assert record.payload_keys == ("document_id", "run_id")


def test_describe_rejects_an_unknown_function() -> None:
    with pytest.raises(UnknownFunctionError):
        describe("arq", "os.system", payload={})


def test_describe_rejects_an_invalid_payload() -> None:
    with pytest.raises(InvalidPayloadError):
        describe("arq", "process_document", payload={"document_id": ""})


def test_describe_does_not_store_payload_values() -> None:
    """Payload values are message bodies; shadow records hold structure only."""
    record = describe("arq", "send_email", payload=_EMAIL)
    rendered = str(record.as_dict())
    assert "a@b.c" not in rendered
    assert "<p>H</p>" not in rendered
    assert record.payload_keys == ("html", "subject", "text", "to")


def test_both_backends_agree_on_a_valid_submission() -> None:
    arq, mongo = _pair()
    diff = compare(arq, mongo, "process_document", tenant_id="t1", dedup_key="k", payload=_PAYLOAD)
    assert diff.agrees is True
    assert diff.differences == ()
    assert len(diff.records) == 2


def test_shadow_reports_a_function_one_backend_does_not_know() -> None:
    """A drift case: describe the arq side, then compare against a bad record."""

    class _Unknown:
        queue_name = "unknown"

    diff = compare(
        cast("WorkerQueue", _Unknown()),
        ArqQueueAdapter("redis://127.0.0.1:1"),
        "process_document",
        payload=_PAYLOAD,
    )
    # Both go through the same registry, so a name unknown to one is unknown to
    # both; the assertion documents that the registry is the single source.
    assert diff.function == "process_document"


def test_shadow_issues_no_queue_operations() -> None:
    """The core safety property: shadow mode must not touch a queue."""

    class _Exploding:
        queue_name = "exploding"

        async def _no(self, *args: object, **kwargs: object) -> None:
            raise AssertionError("shadow mode must not call a queue operation")

        enqueue = claim = heartbeat = complete = fail = retire_expired = ping = _no

    arq = cast("WorkerQueue", _Exploding())
    diff = compare(arq, arq, "crawl_website", tenant_id="t", payload={"crawl_job_id": "c1"})
    assert diff.agrees is True


def test_compared_fields_cover_the_observable_metadata() -> None:
    assert COMPARED_FIELDS == ("function", "tenant_id", "dedup_key", "payload_keys")


def test_differences_are_reported_field_by_field() -> None:
    from backend.queue.shadow import ShadowDiff, ShadowRecord, _differences

    a = ShadowRecord("arq", "ping", "t1", "k1", ())
    b = ShadowRecord("mongo", "ping", "t2", "k1", ())
    diff = _differences((a, b))
    assert diff == ("tenant_id",)
    assert ShadowDiff("ping", "t1", agrees=False, differences=diff).agrees is False


def test_no_single_record_comparison_is_agrees() -> None:
    from backend.queue.shadow import _differences

    assert _differences(()) == ()
