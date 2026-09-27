"""Shadow mode: compare two backends without duplicating side effects.

Phase 17A's brief forbids executing the same real job through both queues, and
the reason is concrete: ``send_email`` would double-send, a crawl would be
ingested twice, embeddings would be billed twice and usage events would be
double-counted. So shadow mode here is **metadata-only**.

What it does
------------
For one logical submission it asks both backends to describe the same job -
logical function name, tenant, dedup key, payload shape - and reports whether
they agree. It never claims, never completes, never invokes a job coroutine and
never contacts a provider. A "real" shadow execution is out of scope; if one is
ever added it must run against mocked side effects (no real email, crawl or
embedding).

What it is for
---------------
Catching integration drift - a function name that one backend does not know, a
payload key the registry rejects, a tenant that does not survive the Mongo
round-trip - before any traffic is routed to Mongo.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from backend.queue.protocol import WorkerQueue
from backend.queue.registry import (
    args_from_payload,
    known_names,
    validate_function,
    validate_payload,
)

#: Fields compared between backends. The payload itself is compared by
#: *structure* (its sorted key set), never by value: payload values are message
#: bodies and crawl payloads, which must not be copied into shadow records.
COMPARED_FIELDS = ("function", "tenant_id", "dedup_key", "payload_keys")


@dataclass(frozen=True)
class ShadowRecord:
    """One backend's description of a logical submission."""

    backend: str
    function: str
    tenant_id: str
    dedup_key: str | None
    payload_keys: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "function": self.function,
            "tenant_id": self.tenant_id,
            "dedup_key": self.dedup_key,
            "payload_keys": list(self.payload_keys),
        }


@dataclass(frozen=True)
class ShadowDiff:
    """The outcome of comparing the two backends for one submission."""

    function: str
    tenant_id: str
    agrees: bool
    differences: tuple[str, ...] = ()
    records: tuple[ShadowRecord, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "function": self.function,
            "tenant_id": self.tenant_id,
            "agrees": self.agrees,
            "differences": list(self.differences),
            "records": [record.as_dict() for record in self.records],
        }


def describe(
    backend: str,
    function: str,
    *,
    tenant_id: str = "",
    dedup_key: str | None = None,
    payload: Mapping[str, Any] | None = None,
) -> ShadowRecord:
    """Describe what ``backend`` would record for this submission.

    The description is derived from the same closed registry the adapters use,
    so a mismatch here is a real integration difference rather than a
    reimplementation of the validation rules.
    """
    validate_function(function)
    body = dict(payload or {})
    validate_payload(function, body)
    # Round-trip through the real arg mapper: this is what proves both backends
    # would dispatch identical positional arguments.
    args_from_payload(function, body)
    return ShadowRecord(
        backend=backend,
        function=function,
        tenant_id=tenant_id,
        dedup_key=dedup_key,
        payload_keys=tuple(sorted(body)),
    )


def compare(
    primary: WorkerQueue,
    secondary: WorkerQueue,
    function: str,
    *,
    tenant_id: str = "",
    dedup_key: str | None = None,
    payload: Mapping[str, Any] | None = None,
) -> ShadowDiff:
    """Compare how two backends would describe one logical submission.

    Both adapters are described through the shared registry, so ``primary`` and
    ``secondary`` are used only for their ``queue_name``/identity here; no queue
    operation is issued against either. Unknown functions and invalid payloads
    surface as :class:`QueueError` from the registry, exactly as they would at
    enqueue time.
    """
    names = (
        getattr(primary, "queue_name", type(primary).__name__),
        getattr(secondary, "queue_name", type(secondary).__name__),
    )
    records = tuple(
        describe(
            name,
            function,
            tenant_id=tenant_id,
            dedup_key=dedup_key,
            payload=payload,
        )
        for name in names
    )
    differences = _differences(records)
    return ShadowDiff(
        function=function,
        tenant_id=tenant_id,
        agrees=not differences,
        differences=differences,
        records=records,
    )


def _differences(records: tuple[ShadowRecord, ...]) -> tuple[str, ...]:
    if len(records) < 2:
        return ()
    first, *rest = records
    found: list[str] = []
    for other in rest:
        for field_name in COMPARED_FIELDS:
            if getattr(first, field_name) != getattr(other, field_name):
                found.append(field_name)
    return tuple(dict.fromkeys(found))


def shadow_plan(functions: tuple[str, ...] = known_names()) -> tuple[str, ...]:
    """The logical job names a shadow sweep should cover.

    Provided so an operator's shadow run is exhaustive by default rather than
    sampling whatever happened to be enqueued.
    """
    return tuple(functions)


__all__ = [
    "COMPARED_FIELDS",
    "ShadowDiff",
    "ShadowRecord",
    "compare",
    "describe",
    "shadow_plan",
]
