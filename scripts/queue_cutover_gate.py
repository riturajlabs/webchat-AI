#!/usr/bin/env python
"""Read-only pre-cutover gate for the ARQ <-> Mongo queue backend switch.

The Phase 18B rollback drill measured a hard blocker: flipping ``QUEUE_BACKEND``
while the *other* backend still holds work strands it, and the ARQ->Mongo queue
already had a pending Mongo job that never got picked up after the flip. There
is no migration tooling, so the only safe cutover is a quiesced one - both
sides empty of non-terminal work - proven **before** anyone touches the
environment.

This gate answers, and nothing else:

1. Which backend is the source of truth now, and which is the target?
2. How many Mongo jobs are in each status?
3. How many jobs are non-terminal (blocking) on each side?
4. Is it safe to flip?  ``GO`` / ``NO-GO`` / ``UNKNOWN``.
5. What was read to prove it? (an explicit read-only attestation)

Safety properties, by construction:

* **Read-only.** The only Redis commands issued are ``ZCARD``/``ZCOUNT``/``HLEN``/
  ``SCARD``/``PING`` and the only Mongo command is ``ping`` plus
  ``count_documents``. There is no enqueue, claim, lease, delete, repair, retry
  or migration anywhere in this file. It cannot change queue state even if it
  crashes.
* **No hardcoded endpoint.** Mongo/Redis locations are read from the *same*
  environment variables the worker uses, so the gate inspects exactly what a
  deployed worker would use.
* **No silent localhost fallback.** A missing or blank URI is a hard error
  (``UNKNOWN``, exit 2). This script never substitutes a default host. Note the
  application itself *does* default ``MONGODB_URI``/``REDIS_URL`` to localhost;
  the gate deliberately does not inherit that default, so an unset variable
  can never quietly point the check at a throwaway instance and report ``GO``.
* **Credentials redacted.** Output carries ``scheme://***@host:port/db`` only;
  passwords in the userinfo or query string are never printed.
* **No auto-migration, ever.** The gate reports; a human changes the environment.
* **Fail closed.** ``NO-GO`` and ``UNKNOWN`` both exit non-zero. Only a proven
  quiesced pair exits 0.

Usage
-----
    python scripts/queue_cutover_gate.py --from arq --to mongo
    python scripts/queue_cutover_gate.py --from mongo --to arq --json

Exit codes: ``0`` = GO, ``1`` = NO-GO, ``2`` = UNKNOWN (or usage/config error).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections.abc import Coroutine
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit, urlunsplit

# --- Gate vocabulary -------------------------------------------------------

VERDICT_GO = "GO"
VERDICT_NO_GO = "NO-GO"
VERDICT_UNKNOWN = "UNKNOWN"

EXIT_GO = 0
EXIT_NO_GO = 1
EXIT_UNKNOWN = 2

BACKEND_ARQ = "arq"
BACKEND_MONGO = "mongo"
BACKENDS = (BACKEND_ARQ, BACKEND_MONGO)

#: Mirrors backend/queue/mongo/models.py. The first three are non-terminal:
#: the only states a cutover can strand.
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_RETRY_PENDING = "retry_pending"
STATUS_COMPLETED = "completed"
STATUS_DEAD = "dead"

MONGO_STATUSES = (
    STATUS_PENDING,
    STATUS_RUNNING,
    STATUS_RETRY_PENDING,
    STATUS_COMPLETED,
    STATUS_DEAD,
)
NON_TERMINAL_STATUSES = (STATUS_PENDING, STATUS_RUNNING, STATUS_RETRY_PENDING)

#: ARQ's own key names (arq/constants.py + ArqRedis default queue name).
#: A deferred ARQ job is not a separate key - it is an entry in the queue zset
#: whose score is still in the future - which is why the split is done by score.
ARQ_QUEUE_KEY = "arq:queue"
ARQ_IN_PROGRESS_KEY = "arq:in-progress:arq:queue"
ARQ_ABORT_KEY = "arq:abort"

#: Bound every probe so an unreachable (rather than refused) broker produces a
#: verdict instead of hanging the operator's terminal.
PROBE_TIMEOUT_SECONDS = 15.0

#: ``None`` means "this backend does not track that state". It is deliberately
#: not ``0``: reporting an untracked state as zero is how a gate lies.
NOT_TRACKED = None


class GateConfigError(Exception):
    """A required input is missing or contradictory - verdict is UNKNOWN."""


# --- Reporting -------------------------------------------------------------


@dataclass(frozen=True)
class SideCounts:
    """One backend's unresolved-work picture, plus how it was obtained."""

    backend: str
    #: status -> count, or None where the backend has no such concept.
    counts: dict[str, int | None]
    #: Sum over the non-terminal statuses. Unused (None) if not reachable.
    blocking: int | None
    #: False when the broker could not be inspected at all.
    reachable: bool
    #: Human-readable failure reason when ``reachable`` is False.
    error: str | None = None
    #: Where these numbers came from, for the read-only attestation.
    endpoint: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "endpoint": self.endpoint,
            "reachable": self.reachable,
            "counts": self.counts,
            "blocking": self.blocking,
            "error": self.error,
        }


#: The complete set of operations this gate is allowed to perform. Kept as a
#: module constant (rather than built inside the runner) so the read-only
#: attestation is a property of the tool, present on every report.
READ_ONLY_OPERATIONS = (
    "mongo: ping, count_documents({status})",
    f"redis: PING, ZCARD {ARQ_QUEUE_KEY}, "
    f"ZCOUNT {ARQ_QUEUE_KEY} (now,+inf], "
    f"HLEN {ARQ_IN_PROGRESS_KEY}, SCARD {ARQ_ABORT_KEY}",
)


@dataclass
class GateReport:
    source: str
    target: str
    configured_backend: str | None
    sides: dict[str, SideCounts] = field(default_factory=dict)
    verdict: str = VERDICT_UNKNOWN
    reasons: list[str] = field(default_factory=list)
    reads: list[str] = field(default_factory=lambda: list(READ_ONLY_OPERATIONS))

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "configured_backend": self.configured_backend,
            "verdict": self.verdict,
            "reasons": self.reasons,
            "read_only_operations": self.reads,
            "sides": {name: side.as_dict() for name, side in self.sides.items()},
        }


def redact_uri(uri: str) -> str:
    """Return a URI safe to print: no password in the userinfo or the query.

    Credentials appear in both places in the wild (``mongodb+srv://u:p@host``
    and ``redis://host?sslPassword=p``), so both are stripped rather than just
    the userinfo.
    """
    if not uri:
        return "<empty>"
    try:
        parts = urlsplit(uri)
    except ValueError:
        return "<unparseable>"
    if not parts.scheme:
        return "<unparseable>"
    host = parts.hostname or ""
    port = f":{parts.port}" if parts.port else ""
    userinfo = "***@" if parts.username or parts.password else ""
    return urlunsplit((parts.scheme, f"{userinfo}{host}{port}", parts.path, "", ""))


# --- Probes (read-only) ----------------------------------------------------


async def probe_mongo(
    uri: str,
    database: str,
    collection: str,
) -> SideCounts:
    """Count Mongo queue jobs per status. Reads only; never claims or writes."""
    from motor.motor_asyncio import AsyncIOMotorClient

    counts: dict[str, int | None] = dict.fromkeys(MONGO_STATUSES, NOT_TRACKED)
    endpoint = f"{redact_uri(uri)} :: {database}.{collection}"
    client: AsyncIOMotorClient[Any] | None = None
    try:
        # A short server-selection timeout is safe *here* and only here: this
        # client is created and closed inside this function, in a short-lived
        # process, and is never shared with the application.
        client = AsyncIOMotorClient(
            uri,
            serverSelectionTimeoutMS=int(PROBE_TIMEOUT_SECONDS * 1000),
            connectTimeoutMS=int(PROBE_TIMEOUT_SECONDS * 1000),
        )
        await client.admin.command("ping")
        jobs = client[database][collection]
        for status in MONGO_STATUSES:
            counts[status] = await jobs.count_documents({"status": status})
    except Exception as exc:  # noqa: BLE001 - any failure is UNKNOWN, never GO
        return SideCounts(
            backend=BACKEND_MONGO,
            counts=counts,
            blocking=None,
            reachable=False,
            error=f"{type(exc).__name__}: {exc}".replace(uri, redact_uri(uri))[:200],
            endpoint=endpoint,
        )
    finally:
        if client is not None:
            client.close()
    blocking = sum(int(counts[s] or 0) for s in NON_TERMINAL_STATUSES)
    return SideCounts(
        backend=BACKEND_MONGO,
        counts=counts,
        blocking=blocking,
        reachable=True,
        endpoint=endpoint,
    )


async def probe_arq(redis_url: str) -> SideCounts:
    """Count ARQ unresolved work. Size reads only; never pops or edits a job."""
    from redis.asyncio import Redis

    # ARQ has no dead-letter state: a job that exhausts its retries raises
    # inside the worker and leaves no record. ARQ also TTLs results, so
    # "completed" cannot be counted. Both are reported as untracked rather
    # than zero.
    counts: dict[str, int | None] = {
        STATUS_PENDING: NOT_TRACKED,
        STATUS_RUNNING: NOT_TRACKED,
        STATUS_RETRY_PENDING: NOT_TRACKED,
        STATUS_COMPLETED: NOT_TRACKED,
        STATUS_DEAD: NOT_TRACKED,
    }
    endpoint = redact_uri(redis_url)
    redis = Redis.from_url(
        redis_url,
        socket_timeout=PROBE_TIMEOUT_SECONDS,
        socket_connect_timeout=PROBE_TIMEOUT_SECONDS,
        decode_responses=True,
    )
    try:
        await redis.ping()
        total = int(await redis.zcard(ARQ_QUEUE_KEY))
        # Deferred jobs are future-scored entries in the same zset.
        deferred = int(await redis.zcount(ARQ_QUEUE_KEY, f"({int(time.time() * 1000)}", "+inf"))
        in_progress = int(await redis.hlen(ARQ_IN_PROGRESS_KEY))
        abort = int(await redis.scard(ARQ_ABORT_KEY))
        counts[STATUS_PENDING] = total - deferred
        counts[STATUS_RETRY_PENDING] = deferred
        counts[STATUS_RUNNING] = in_progress + abort
    except Exception as exc:  # noqa: BLE001 - any failure is UNKNOWN, never GO
        return SideCounts(
            backend=BACKEND_ARQ,
            counts=counts,
            blocking=None,
            reachable=False,
            error=f"{type(exc).__name__}: {exc}".replace(redis_url, endpoint)[:200],
            endpoint=endpoint,
        )
    finally:
        await redis.aclose()
    blocking = sum(int(counts[s] or 0) for s in NON_TERMINAL_STATUSES)
    return SideCounts(
        backend=BACKEND_ARQ,
        counts=counts,
        blocking=blocking,
        reachable=True,
        endpoint=endpoint,
    )


# --- Verdict ---------------------------------------------------------------


def decide(
    source: str,
    target: str,
    configured_backend: str | None,
    sides: dict[str, SideCounts],
) -> tuple[str, list[str]]:
    """Apply the cutover invariant. Returns ``(verdict, reasons)``."""
    reasons: list[str] = []

    if source not in BACKENDS or target not in BACKENDS:
        return VERDICT_UNKNOWN, [f"unknown backend name: {source!r} -> {target!r}"]
    if source == target:
        reasons.append(
            f"source and target are both {source!r}: there is no cutover to gate, "
            "and a same-backend run must never report GO"
        )
        return VERDICT_NO_GO, reasons
    if configured_backend is not None and configured_backend != source:
        reasons.append(
            f"QUEUE_BACKEND={configured_backend!r} does not match the declared "
            f"source {source!r}: the gate is pointed at the wrong pair"
        )
        return VERDICT_UNKNOWN, reasons

    # An uninspectable side is UNKNOWN, never "empty". This is the single most
    # important line in the file.
    for name in (source, target):
        side = sides.get(name)
        if side is None or not side.reachable or side.blocking is None:
            detail = "not probed" if side is None else (side.error or "unreachable")
            reasons.append(f"{name} state could not be inspected ({detail})")
            return VERDICT_UNKNOWN, reasons

    blockers = {name: sides[name].blocking for name in (source, target)}
    for name in (source, target):
        if int(blockers[name] or 0) > 0:
            reasons.append(
                f"{name} still holds {blockers[name]} non-terminal job(s); "
                "flipping now would strand them"
            )
    if reasons:
        return VERDICT_NO_GO, reasons

    return (
        VERDICT_GO,
        [
            f"{source} has no non-terminal work",
            f"{target} has no non-terminal work",
            "both sides were successfully inspected",
        ],
    )


# --- Configuration ---------------------------------------------------------


@dataclass(frozen=True)
class GateConfig:
    mongo_uri: str
    mongo_database: str
    mongo_collection: str
    redis_url: str
    configured_backend: str | None


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def resolve_config(*, require_live: bool = True) -> GateConfig:
    """Read the endpoints from the environment the worker itself uses.

    Raises ``GateConfigError`` rather than defaulting anything, so an unset
    variable can never silently point the gate at a local instance.
    """
    mongo_uri = _env("MONGODB_URI")
    mongo_database = _env("MONGODB_QUEUE_DATABASE")
    redis_url = _env("REDIS_URL")
    configured = _env("QUEUE_BACKEND").lower() or None

    missing = [
        name
        for name, value in (
            ("MONGODB_URI", mongo_uri),
            ("MONGODB_QUEUE_DATABASE", mongo_database),
            ("REDIS_URL", redis_url),
        )
        if not value
    ]
    if missing:
        raise GateConfigError(
            "missing required environment variable(s): "
            + ", ".join(missing)
            + " - refusing to fall back to any default host"
        )
    if require_live and configured is None:
        raise GateConfigError("QUEUE_BACKEND is not set; cannot confirm the live source backend")

    collection = _env("MONGODB_QUEUE_COLLECTION") or "worker_jobs"
    return GateConfig(
        mongo_uri=mongo_uri,
        mongo_database=mongo_database,
        mongo_collection=collection,
        redis_url=redis_url,
        configured_backend=configured,
    )


# --- CLI -------------------------------------------------------------------


async def run_gate(config: GateConfig, source: str, target: str) -> GateReport:
    report = GateReport(
        source=source,
        target=target,
        configured_backend=config.configured_backend,
    )
    mongo, arq = await asyncio.gather(
        _bounded(
            BACKEND_MONGO,
            probe_mongo(config.mongo_uri, config.mongo_database, config.mongo_collection),
        ),
        _bounded(BACKEND_ARQ, probe_arq(config.redis_url)),
    )
    report.sides = {BACKEND_MONGO: mongo, BACKEND_ARQ: arq}
    report.verdict, report.reasons = decide(source, target, config.configured_backend, report.sides)
    return report


async def _bounded(backend: str, coro: Coroutine[Any, Any, SideCounts]) -> SideCounts:
    """Turn an unreachable-into-timeout broker into UNKNOWN, never into a hang."""
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS * 2):
            return await coro
    except TimeoutError:
        return SideCounts(
            backend=backend,
            counts=dict.fromkeys(MONGO_STATUSES, NOT_TRACKED),
            blocking=None,
            reachable=False,
            error="probe exceeded its wall-clock budget",
        )


def render(report: GateReport) -> str:
    lines = [
        "ARQ <-> Mongo queue cutover gate (read-only)",
        "",
        f"  source (live now) : {report.source}",
        f"  target (proposed) : {report.target}",
        f"  QUEUE_BACKEND     : {report.configured_backend or '<unset>'}",
        "",
        "  Unresolved work per side:",
    ]
    for name in (report.source, report.target):
        side = report.sides.get(name)
        if side is None:
            lines.append(f"    {name:<6} NOT PROBED")
            continue
        if not side.reachable:
            lines.append(f"    {name:<6} UNKNOWN - {side.error}")
            continue
        cells = []
        for status in MONGO_STATUSES:
            value = side.counts.get(status, NOT_TRACKED)
            cells.append(f"{status}={'n/a' if value is None else value}")
        lines.append(f"    {name:<6} {side.endpoint}")
        lines.append(f"           {'  '.join(cells)}")
        lines.append(f"           NON-TERMINAL (blocking) = {side.blocking}")
    lines += [
        "",
        f"  VERDICT: {report.verdict}",
    ]
    for reason in report.reasons:
        lines.append(f"    - {reason}")
    lines += [
        "",
        "  Read-only operations used:",
        *[f"    - {read}" for read in report.reads],
        "",
        "  This gate changed nothing. Flipping QUEUE_BACKEND is a human decision.",
    ]
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="queue_cutover_gate.py",
        description="Read-only GO / NO-GO / UNKNOWN gate for the queue backend cutover.",
    )
    parser.add_argument("--from", dest="source", choices=BACKENDS, required=True)
    parser.add_argument("--to", dest="target", choices=BACKENDS, required=True)
    parser.add_argument("--json", action="store_true", help="emit one JSON object")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = resolve_config()
    except GateConfigError as exc:
        # A configuration problem is UNKNOWN, and unknown is non-zero.
        print(f"VERDICT: {VERDICT_UNKNOWN}\n  - {exc}", file=sys.stderr)
        return EXIT_UNKNOWN

    report = asyncio.run(run_gate(config, args.source, args.target))
    if args.json:
        print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    else:
        print(render(report))
    return {
        VERDICT_GO: EXIT_GO,
        VERDICT_NO_GO: EXIT_NO_GO,
        VERDICT_UNKNOWN: EXIT_UNKNOWN,
    }[report.verdict]


if __name__ == "__main__":
    sys.exit(main())
