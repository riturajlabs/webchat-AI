"""Normalized ARQ/Mongo job envelopes and a field-level comparator (Phase 17B).

Why this module exists
----------------------
Phase 17A's ``shadow.py`` asked the *same* registry to describe the same
submission twice and compared the results. That cannot fail by construction, so
it cannot detect adapter-specific drift - the exact class of bug shadow mode
exists to catch. This module derives each envelope from a genuinely independent
source:

``from_arq``
    Calls the **real** :class:`~backend.queue.arq_adapter.ArqQueueAdapter`
    ``enqueue`` and intercepts the ``ArqRedis.enqueue_job`` call at the SDK
    boundary. The recorded function name, positional args, ``_job_id`` and
    ``_defer_by`` are therefore exactly what ARQ would have written to Redis -
    produced by production code, with no Redis contact and no side effect.

``from_mongo``
    Calls the **real** :class:`~backend.queue.mongo_adapter.MongoQueueAdapter`
    ``enqueue`` and reads the persisted row back out. ``dedup_key``,
    ``max_tries``, ``run_at`` and the stored payload are therefore what the
    store actually wrote.

Because the two sides are produced by two different code paths, a divergence
between them is a real finding rather than a tautology.

Explained divergences
---------------------
Some differences are intentional and already documented by the Phase 17A design
(ARQ deliberately does not carry a tenant; the two backends express
deduplication differently). Those are registered in :data:`EXPLAINED_DIVERGENCES`
with the reason, so a *documented* difference is reported as ``EXPLAINED`` and
only an *unknown* difference counts as an unexplained mismatch. A silently new
divergence is therefore a test failure.

Payload handling
----------------
Payload values are never retained. ``send_email`` payloads are rendered message
bodies and crawl payloads are page metadata, so an envelope records the payload
*key set* plus a per-value shape descriptor (type, length, salted digest) and
keeps no plaintext. That is enough to prove two backends carry the same payload
while remaining safe to log.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final

from backend.queue.protocol import WorkerQueue

if TYPE_CHECKING:  # pragma: no cover - typing only
    from backend.queue.mongo_adapter import MongoQueueAdapter
from backend.queue.registry import (
    JOB_ARGUMENTS,
    args_from_payload,
    arq_job_timeouts,
    validate_function,
    validate_payload,
)

#: Fields the comparator checks, in report order.
COMPARED_FIELDS: Final[tuple[str, ...]] = (
    "function",
    "payload_keys",
    "payload_shape",
    "tenant_id",
    "request_id",
    "logical_job_id",
    "timeout_seconds",
    "max_tries",
    "defer_seconds",
    "retry_class",
)

#: Digest salt so a leaked shape descriptor cannot be dictionary-attacked back
#: into an email body or a URL. Two envelopes are only ever compared with each
#: other, never against an attacker's guess.
_SHAPE_SALT: Final[bytes] = b"webchat-ai-queue-shadow-v1"

#: Sentinel for "this backend does not carry this concept at all".
ABSENT: Final[str] = "<absent>"


# ----------------------------------------------------------------------
# payload redaction
# ----------------------------------------------------------------------


def shape_value(value: Any) -> str:
    """Return a log-safe structural descriptor for one payload value.

    Strings become ``str(len=N,sha=abcd1234)``: the length is already visible
    in any redacted email trace and the digest is salted, so neither the body
    nor a guessable token is recoverable. Containers recurse into their key set
    only, never their values.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return f"bool({str(value).lower()})"
    if isinstance(value, str):
        return f"str(len={len(value)},sha={_digest(value)[:8]})"
    if isinstance(value, (int, float)):
        return f"{type(value).__name__}({value})"
    if isinstance(value, Mapping):
        return f"map(keys={sorted(map(str, value))})"
    if isinstance(value, (list, tuple)):
        return f"{type(value).__name__}(len={len(value)})"
    if isinstance(value, datetime):
        return "datetime"
    return f"opaque({type(value).__name__})"


def _digest(value: str) -> str:
    return hashlib.sha256(_SHAPE_SALT + value.encode("utf-8")).hexdigest()


def payload_shape(payload: Mapping[str, Any]) -> dict[str, str]:
    """Return ``{key: shape descriptor}`` for a payload, sorted by key."""
    return {key: shape_value(payload[key]) for key in sorted(map(str, payload))}


# ----------------------------------------------------------------------
# the normalized envelope
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class NormalizedJobEnvelope:
    """One backend's description of a single logical job submission.

    Every field is derived from that backend's own enqueue path. No field is
    copied from the other backend, and no payload plaintext is retained.
    """

    backend: str
    function: str
    payload_keys: tuple[str, ...]
    payload_shape: dict[str, str]
    tenant_id: str
    request_id: str
    logical_job_id: str
    timeout_seconds: int
    max_tries: int
    defer_seconds: float
    retry_class: dict[str, Any]

    def field_value(self, name: str) -> Any:
        """Return one compared field by name, in a log-safe form."""
        if name == "payload_shape":
            return dict(self.payload_shape)
        if name == "retry_class":
            return dict(self.retry_class)
        return getattr(self, name)

    def as_dict(self) -> dict[str, Any]:
        """Log-safe rendering: no payload values, no secrets, no URI."""
        return {
            "backend": self.backend,
            **{name: self.field_value(name) for name in COMPARED_FIELDS},
        }


@dataclass(frozen=True)
class FieldDifference:
    """One structured mismatch reason."""

    field: str
    arq: Any
    mongo: Any
    explained: bool
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"field": self.field, "arq": self.arq, "mongo": self.mongo}
        out["status"] = "EXPLAINED" if self.explained else "UNEXPLAINED"
        if self.reason:
            out["reason"] = self.reason
        return out


@dataclass(frozen=True)
class EnvelopeParity:
    """The outcome of comparing one submission across the two backends."""

    function: str
    arq: NormalizedJobEnvelope
    mongo: NormalizedJobEnvelope
    differences: tuple[FieldDifference, ...] = field(default_factory=tuple)

    @property
    def matches(self) -> bool:
        """True when every difference is a documented, expected divergence."""
        return not any(not difference.explained for difference in self.differences)

    @property
    def unexplained(self) -> tuple[FieldDifference, ...]:
        return tuple(d for d in self.differences if not d.explained)

    def as_dict(self) -> dict[str, Any]:
        return {
            "function": self.function,
            "status": "MATCH" if self.matches else "MISMATCH",
            "arq": self.arq.as_dict(),
            "mongo": self.mongo.as_dict(),
            "differences": [difference.as_dict() for difference in self.differences],
            "unexplained_count": len(self.unexplained),
        }


# ----------------------------------------------------------------------
# retry-class policies (per backend, as measured / as designed)
# ----------------------------------------------------------------------

#: ARQ 0.28 as MEASURED by running a real worker (Phase 17A section 8, and
#: re-measured by scripts/queue_arq_probe.py in Phase 17B): an ordinary
#: exception and a job timeout are dead-lettered on the first attempt and never
#: consume the max_tries budget; a job-raised CancelledError is retried up to
#: max_tries. ARQ applies NO backoff to those retry paths - the job becomes
#: runnable again immediately.
ARQ_RETRY_POLICY: Final[dict[str, Any]] = {
    "terminal_on": ("ordinary_exception", "timeout"),
    "retry_on": ("cancelled",),
    "backoff_seconds": None,
    "source": "measured-arq-0.28",
}

#: The Mongo worker maps the same measured ARQ outcomes, but the store applies
#: the knowledge-domain backoff schedule (QueueConfig.backoff_seconds) to a
#: retried job. This is a REAL behavioural divergence from ARQ and is one of the
#: reasons this comparator exists; see ENTRY "backoff_seconds".
MONGO_RETRY_POLICY: Final[dict[str, Any]] = {
    "terminal_on": ("ordinary_exception", "timeout"),
    "retry_on": ("cancelled",),
    "backoff_seconds": "queue_config",
    "source": "phase17a-mapping",
}


#: Divergences that are intentional and already reasoned about. Each entry maps
#: ``(function, field)`` to the reason it is expected. A difference that is not
#: in this table is UNEXPLAINED and fails the parity gate.
EXPLAINED_DIVERGENCES: Final[dict[tuple[str, str], str]] = {
    ("*", "tenant_id"): (
        "ARQ never receives a tenant argument: its job signatures are fixed "
        "positional args, and production jobs read the authoritative tenant from "
        "the domain row. Mongo stores the tenant on the queue row so the row is "
        "attributable and tenant-scoped reads are possible."
    ),
    ("*", "request_id"): (
        "request_id is not an enqueue-time field in either backend. Production "
        "jobs derive their own execution-time value (crawl_website sets "
        "job:<crawl_job_id>; RequestIDMiddleware sets the API-side one), so no "
        "envelope carries it and both sides report it absent."
    ),
    ("crawl_website", "logical_job_id"): (
        "ARQ uses the JOB-scoped _job_id 'crawl:<crawl_job_id>' (FIND-02); Mongo "
        "uses the store's unique dedup_key with the same caller-supplied value. "
        "Same identity, different namespace and different duplicate signalling."
    ),
    ("*", "logical_job_id"): (
        "The two backends express idempotency with different primitives: ARQ "
        "suppresses a duplicate and signals None, Mongo collapses a duplicate "
        "dedup_key to the existing job id. A row that has never been enqueued "
        "has no logical id in either backend."
    ),
    ("*", "retry_class"): (
        "Both backends map the same MEASURED ARQ outcomes (ordinary exception and "
        "timeout terminal, CancelledError retried). They differ in when a retried "
        "job becomes runnable: ARQ makes it runnable again immediately, while the "
        "Mongo store applies the knowledge-domain 5/30/180 s backoff schedule. A "
        "real behavioural difference, reported here so a cutover is not surprised "
        "by it."
    ),
    ("*", "defer_seconds"): (
        "ARQ records _defer_by and the worker re-schedules with it; Mongo stores "
        "an absolute run_at computed from defer_by. The delay itself is "
        "identical; only the representation differs, and only when a deferral "
        "was requested."
    ),
}


def _explain(
    function: str, field_name: str, arq_value: Any, mongo_value: Any
) -> str | None:
    """Return the reason a difference on ``field_name`` is expected, if any.

    A written reason is necessary but not sufficient: it must also apply to the
    *values* actually observed. Otherwise a broad entry would excuse a genuine
    bug - the ``tenant_id`` entry in particular must not explain "Mongo carries
    a *different* tenant than expected", only "ARQ carries none at all".
    """
    reason = EXPLAINED_DIVERGENCES.get((function, field_name)) or EXPLAINED_DIVERGENCES.get(
        ("*", field_name)
    )
    if reason is None:
        return None
    if field_name in _ARQ_ABSENT_FIELDS and arq_value != ABSENT:
        # The documented divergence is that ARQ has no such field. If the ARQ
        # side does hold a value, the two sides genuinely disagree.
        return None
    return reason


# ----------------------------------------------------------------------
# ARQ side: the real adapter, intercepted at the SDK boundary
# ----------------------------------------------------------------------


class _RecordedJob:
    """Stand-in for ``arq.jobs.Job`` as returned by ``ArqRedis.enqueue_job``."""

    def __init__(self, job_id: str) -> None:
        self.job_id = job_id


@dataclass
class RecordedEnqueue:
    """Exactly what the ARQ adapter asked the SDK to do."""

    function: str
    args: tuple[Any, ...]
    job_id: str | None
    defer_by: float | None


class RecordingArqRedis:
    """An ``ArqRedis`` stand-in that records instead of contacting Redis.

    This is the boundary where production code decides the ARQ envelope, so
    recording here observes the real decision without a network call, a
    production write, or a job ever becoming runnable.
    """

    def __init__(self) -> None:
        self.calls: list[RecordedEnqueue] = []

    async def enqueue_job(
        self, function: str, *args: Any, **kwargs: Any
    ) -> _RecordedJob:
        job_id = kwargs.get("_job_id")
        defer_by = kwargs.get("_defer_by")
        self.calls.append(
            RecordedEnqueue(
                function=function,
                args=args,
                job_id=job_id,
                defer_by=defer_by,
            )
        )
        return _RecordedJob(job_id or f"shadow-{function}")

    async def ping(self) -> bool:
        return True


class RecordingArqQueueAdapter:
    """``ArqQueueAdapter`` with its Redis client swapped for the recorder.

    Subclassing (rather than mutating a production instance) keeps the shadow
    path incapable of touching Redis even if a future caller forgets to pass a
    Redis URL: the only client this object can build is the recorder.
    """

    def __init__(self) -> None:  # noqa: D107 - deliberately no Redis URL
        from backend.queue.arq_adapter import ArqQueueAdapter

        class _Shadow(ArqQueueAdapter):
            def __init__(self) -> None:  # noqa: D107
                self._redis_url = "shadow://no-redis"
                self._pool = None
                self._recorder = RecordingArqRedis()

            def _arq_redis(self) -> RecordingArqRedis:  # type: ignore[override]
                return self._recorder

        self._adapter = _Shadow()

    @property
    def recorder(self) -> RecordingArqRedis:
        return self._adapter._arq_redis()

    @property
    def queue_name(self) -> str:
        return self._adapter.queue_name

    async def enqueue(
        self,
        function: str,
        *,
        payload: Mapping[str, Any] | None = None,
        tenant_id: str = "",
        dedup_key: str | None = None,
        defer_by: float | None = None,
        job_id: str | None = None,
        max_tries: int | None = None,
    ) -> str:
        _ = (tenant_id, max_tries)
        return await self._adapter.enqueue(
            function,
            payload=dict(payload or {}),
            tenant_id=tenant_id,
            dedup_key=dedup_key,
            defer_by=defer_by,
            job_id=job_id,
            max_tries=max_tries,
        )

    async def close(self) -> None:
        return None


async def from_arq(
    function: str,
    *,
    payload: Mapping[str, Any] | None = None,
    dedup_key: str | None = None,
    job_id: str | None = None,
    defer_by: float | None = None,
) -> NormalizedJobEnvelope:
    """Build the ARQ envelope by running the real adapter's enqueue path.

    ``timeout_seconds`` is read from the production ARQ registry objects
    themselves (``arq.worker.Function.timeout_s``, falling back to
    ``WorkerSettings.job_timeout``) - the same source ARQ's own worker uses.
    """
    validate_function(function)
    validate_payload(function, dict(payload or {}))
    body = dict(payload or {})
    # Fail here, at the boundary, if the two backends could not even agree on
    # the argument shape - otherwise a payload round-trip bug would look like a
    # clean comparison.
    args_from_payload(function, body)

    shadow = RecordingArqQueueAdapter()
    await shadow.enqueue(
        function,
        payload=body,
        dedup_key=dedup_key,
        job_id=job_id,
        defer_by=defer_by,
    )
    calls = shadow.recorder.calls
    if len(calls) != 1:  # pragma: no cover - defensive: the adapter enqueues once
        raise AssertionError(f"expected exactly one ARQ enqueue, got {len(calls)}")
    recorded = calls[0]
    if recorded.function != function:  # pragma: no cover - adapter maps 1:1
        raise AssertionError("ARQ adapter rewrote the function name")

    from backend.workers.app import WorkerSettings

    timeouts = arq_job_timeouts(WorkerSettings.functions, int(WorkerSettings.job_timeout))
    return NormalizedJobEnvelope(
        backend="arq",
        function=recorded.function,
        payload_keys=_arq_payload_keys(function, recorded.args),
        payload_shape=payload_shape(_arq_payload(function, recorded.args)),
        tenant_id=ABSENT,
        request_id=ABSENT,
        logical_job_id=recorded.job_id or ABSENT,
        timeout_seconds=int(timeouts.get(function, 0)),
        max_tries=int(WorkerSettings.max_tries),
        defer_seconds=float(recorded.defer_by or 0.0),
        retry_class=dict(ARQ_RETRY_POLICY),
    )


def _arq_payload(function: str, args: Sequence[Any]) -> dict[str, Any]:
    """Reconstruct the queue payload from ARQ's positional args."""
    from backend.queue.registry import payload_from_args

    return payload_from_args(function, tuple(args))


def _arq_payload_keys(function: str, args: Sequence[Any]) -> tuple[str, ...]:
    return tuple(sorted(_arq_payload(function, args)))


# ----------------------------------------------------------------------
# Mongo side: the real adapter, row read back out of the database
# ----------------------------------------------------------------------


async def from_mongo(
    queue: MongoQueueAdapter,
    function: str,
    *,
    payload: Mapping[str, Any] | None = None,
    tenant_id: str = "",
    dedup_key: str | None = None,
    job_id: str | None = None,
    defer_by: float | None = None,
    now: datetime | None = None,
) -> NormalizedJobEnvelope:
    """Build the Mongo envelope by really enqueueing and reading the row back.

    The row is written to whatever collection the caller supplied. In staging
    and tests that is a dedicated shadow collection in an isolated database; it
    is never the production queue collection. No worker claims the row, so no job
    function is ever invoked and no side effect occurs.
    """
    validate_function(function)
    validate_payload(function, dict(payload or {}))
    body = dict(payload or {})
    args_from_payload(function, body)

    enqueued_id = await queue.enqueue(
        function,
        payload=body,
        tenant_id=tenant_id,
        dedup_key=dedup_key,
        job_id=job_id,
        defer_by=defer_by,
        now=now,
    )
    row = await _read_row(queue, enqueued_id, function)
    if row is None:  # pragma: no cover - defensive
        raise AssertionError(f"enqueued Mongo shadow row {enqueued_id!r} is not readable")

    stored = dict(row.get("payload") or {})
    return NormalizedJobEnvelope(
        backend="mongo",
        function=str(row.get("function")),
        payload_keys=tuple(sorted(map(str, stored))),
        payload_shape=payload_shape(stored),
        tenant_id=str(row.get("tenant_id") or ABSENT),
        # `request_id` is deliberately NOT read from the row: it is not an
        # enqueue-time field in either backend. Production jobs derive their own
        # execution-time request id (`crawl_website` sets `job:<crawl_job_id>`),
        # so asserting it here would invent a field production does not carry.
        request_id=ABSENT,
        logical_job_id=str(row.get("dedup_key") or ABSENT),
        timeout_seconds=int(job_timeout_for_mongo(function)),
        max_tries=int(row.get("max_tries") or 0),
        # The store persists an absolute run_at, never the requested delay, so
        # the delay is recovered from the row it actually wrote.
        defer_seconds=_defer_from_row(row),
        retry_class={
            **MONGO_RETRY_POLICY,
            "backoff_seconds": list(_config_backoff(queue)),
        },
    )


def _defer_from_row(row: Mapping[str, Any]) -> float:
    """Recover the requested deferral from a persisted ``run_at``."""
    run_at = row.get("run_at")
    created_at = row.get("created_at")
    if not isinstance(run_at, datetime) or not isinstance(created_at, datetime):
        return 0.0
    return max(0.0, round((run_at - created_at).total_seconds(), 3))


def _config_backoff(queue: WorkerQueue) -> tuple[float, ...]:
    """The store's backoff schedule, as configured."""
    store = getattr(queue, "queue", None)
    config = getattr(store, "config", None)
    backoff = getattr(config, "backoff_seconds", None)
    return tuple(float(value) for value in backoff or ())


def job_timeout_for_mongo(function: str) -> int:
    """The timeout the Mongo worker applies, from the worker's own lookup."""
    from backend.queue.registry import job_timeout_seconds

    return job_timeout_seconds(function)


async def _read_row(
    queue: MongoQueueAdapter, job_id: str, function: str
) -> dict[str, Any] | None:
    """Read a persisted queue row back, by the adapter's own accessor."""
    getter = getattr(queue, "get", None)
    if getter is None:  # pragma: no cover - WorkerQueue requires it
        return None
    job = await getter(job_id)
    if job is None:
        return None
    # ``QueueJob`` carries the queue-facing view; the raw document adds the
    # stored-at-rest representation the comparator must report.
    store = getattr(queue, "queue", None)
    if store is not None:
        raw = await store.collection.find_one({"_id": job_id})
        if raw is not None:
            document = dict(raw)
            document.setdefault("function", job.function)
            document.setdefault("payload", dict(job.payload))
            return document
    _ = function
    return {
        "function": job.function,
        "payload": dict(job.payload),
        "tenant_id": job.tenant_id,
        "dedup_key": None,
        "max_tries": job.job_try,
    }


# ----------------------------------------------------------------------
# the comparator
# ----------------------------------------------------------------------


#: Fields whose documented divergence is precisely "ARQ does not carry this at
#: all". A difference involving an actual ARQ value is then a real mismatch.
_ARQ_ABSENT_FIELDS: Final[frozenset[str]] = frozenset({"tenant_id", "request_id"})


def compare_envelopes(
    arq: NormalizedJobEnvelope, mongo: NormalizedJobEnvelope
) -> EnvelopeParity:
    """Field-by-field comparison with a reason for every difference.

    A difference that :data:`EXPLAINED_DIVERGENCES` already accounts for is
    reported as ``EXPLAINED``; anything else is ``UNEXPLAINED`` and makes
    :attr:`EnvelopeParity.matches` false.
    """
    differences: list[FieldDifference] = []
    for name in COMPARED_FIELDS:
        left = arq.field_value(name)
        right = mongo.field_value(name)
        if _equal(left, right):
            continue
        reason = _explain(arq.function, name, left, right)
        differences.append(
            FieldDifference(
                field=name,
                arq=left,
                mongo=right,
                explained=reason is not None,
                reason=reason or "",
            )
        )
    return EnvelopeParity(
        function=arq.function,
        arq=arq,
        mongo=mongo,
        differences=tuple(differences),
    )


def _equal(left: Any, right: Any) -> bool:
    if isinstance(left, tuple) and isinstance(right, list):
        left = list(left)
    if isinstance(right, tuple) and isinstance(left, list):
        right = list(right)
    if isinstance(left, dict) and isinstance(right, dict):
        return _canonical(left) == _canonical(right)
    return bool(left == right)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


#: One representative submission per registered job, used by the parity sweep.
#: Values are shape-only: these are never sent anywhere, they only have to
#: survive both adapters' validation so the comparison is reached.
SAMPLE_SUBMISSIONS: Final[dict[str, dict[str, Any]]] = {
    "ping": {},
    "send_email": {
        "to": "shadow@example.invalid",
        "subject": "shadow subject",
        "text": "shadow body",
        "html": "<p>shadow body</p>",
    },
    "crawl_website": {"crawl_job_id": "shadow-crawl-job-0001"},
    "process_document": {"document_id": "shadow-document-0001", "run_id": None},
    "process_website_documents": {"website_id": "shadow-website-0001"},
}

#: The job-id / dedup shape production actually uses, per function. Kept out of
#: the sample payloads because it is a routing knob, not a payload field.
PRODUCTION_ROUTING: Final[dict[str, dict[str, Any]]] = {
    "ping": {},
    "send_email": {},
    "crawl_website": {"job_id": "crawl:shadow-crawl-job-0001"},
    "process_document": {},
    "process_website_documents": {},
}


def known_submission_functions() -> tuple[str, ...]:
    """The job names an envelope-parity sweep must cover, exhaustively."""
    return tuple(SAMPLE_SUBMISSIONS)


def registry_is_complete() -> bool:
    """True when every registered job has a sample submission to compare."""
    return set(SAMPLE_SUBMISSIONS) == set(JOB_ARGUMENTS)


__all__ = [
    "ABSENT",
    "ARQ_RETRY_POLICY",
    "COMPARED_FIELDS",
    "EXPLAINED_DIVERGENCES",
    "EnvelopeParity",
    "FieldDifference",
    "MONGO_RETRY_POLICY",
    "NormalizedJobEnvelope",
    "PRODUCTION_ROUTING",
    "RecordedEnqueue",
    "RecordingArqQueueAdapter",
    "RecordingArqRedis",
    "SAMPLE_SUBMISSIONS",
    "compare_envelopes",
    "from_arq",
    "from_mongo",
    "known_submission_functions",
    "payload_shape",
    "registry_is_complete",
    "shape_value",
]
