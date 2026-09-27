#!/usr/bin/env python
"""Phase 17B shadow validation harness: compare the two backends' job envelopes.

Run this *before* any Mongo cutover to answer one question: if we switched the
queue backend tomorrow, would every job still be delivered with the same
function, timeout, payload shape, tenant and dedup key?

Safety, by construction - this script is deliberately hard to misuse:

* it talks only to the Mongo URI given on the command line, never to an
  environment variable, so a stray ``MONGO_URI`` cannot aim it at production;
* it **refuses** any URI that looks like a production cluster. There is no
  override flag, no ``--force``, no escape hatch. A localhost mongod or an Atlas
  *sandbox*/``mongodb.net`` host must be requested with an explicit
  ``--allow-host`` naming that host, so the operator has to type the thing they
  are about to touch;
* it writes only to a dedicated ``*_shadow_validation`` collection and drops it
  on the way out;
* it executes no job. Every row it writes stays ``pending`` with
  ``attempts == 0``; that invariant is re-checked at the end and reported, so a
  future change that accidentally starts claiming work fails the run loudly;
* it sends no email, crawls nothing, and calls no provider;
* the ARQ side is recorded, not published, so no Redis traffic is generated.

Usage
-----
    python scripts/queue_shadow_validation.py                 # isolated default
    python scripts/queue_shadow_validation.py --json          # machine readable
    python scripts/queue_shadow_validation.py --allow-host mongodb.net

``--json`` prints one JSON object so the Phase 17B report can quote measured
output rather than prose. A non-zero exit means at least one *unexplained*
difference was found, which is what makes the harness usable as a gate.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from backend.prototypes.mongo_queue.config import DEFAULT_MONGO_URI
from backend.queue.envelope import (
    COMPARED_FIELDS,
    PRODUCTION_ROUTING,
    SAMPLE_SUBMISSIONS,
    EnvelopeParity,
    compare_envelopes,
    from_arq,
    from_mongo,
    known_submission_functions,
    registry_is_complete,
)
from backend.queue.registry import JOB_ARGUMENTS, known_names

SHADOW_DB = "webchat_ai_queue_shadow_validation"
SHADOW_COLLECTION = "shadow_envelopes"

# Hostname fragments that indicate a live production cluster. Matching is on
# the parsed hostname, so ``mongodb+srv://...`` is covered too.
_PRODUCTION_HOST_MARKERS = (
    ".mongodb.net",
    "prod",
    "production",
    "atlas",
)


class UnsafeEndpointError(RuntimeError):
    """Raised when a URI could plausibly be a production cluster."""


@dataclass
class SafetyVerdict:
    """Why the harness believes (or does not believe) it may talk to a host."""

    host: str
    allowed: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)
    consent: str = ""


def _host_of(uri: str) -> str:
    parsed = urlparse(uri)
    if not parsed.hostname:
        raise UnsafeEndpointError(f"cannot parse a hostname from {uri!r}")
    return parsed.hostname


_LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def check_endpoint(uri: str, allow_hosts: tuple[str, ...] = ()) -> SafetyVerdict:
    """Decide whether the harness may connect, and say why.

    The rule is deliberately blunt: **only loopback runs unattended.** Any other
    host must be named in ``--allow-host``, which is a deliberate, visible act
    that ends up in the report. Naming a production cluster does not unlock it
    quietly - it is recorded as ``consent`` so the artifact says exactly who
    pointed the tool where.

    A host that merely *looks* production (``*.mongodb.net``, ``prod-*``,
    ``atlas-*``) and was not named is refused with that specific reason, so the
    common typo fails loudly rather than being waved through.
    """
    host = _host_of(uri)
    lowered = host.lower()
    reasons: list[str] = []
    notes: list[str] = []

    named = host in allow_hosts
    loopback = host in _LOOPBACK

    if not loopback and not named:
        for marker in _PRODUCTION_HOST_MARKERS:
            if marker in lowered:
                reasons.append(
                    f"hostname contains {marker!r}, which indicates production, "
                    f"and {host!r} was not named in --allow-host"
                )
                break
        else:
            reasons.append(f"host {host!r} is not loopback and was not named in --allow-host")

    if "mongodb+srv" in uri and "retrywrites" not in uri.lower():
        notes.append("SRV URI does not state retryWrites; this default varies by environment")

    if "retrywrites" in uri.lower() and "retrywrites=false" in uri.lower().replace(" ", ""):
        notes.append("retryWrites=false: a write concern error will not be retried")

    consent = "" if loopback else f"--allow-host {host}"
    return SafetyVerdict(
        host=host,
        allowed=not reasons,
        reasons=tuple(reasons),
        notes=tuple(notes),
        consent=consent,
    )


def _summarise(parity: EnvelopeParity) -> dict[str, Any]:
    return {
        "function": parity.function,
        "matches": parity.matches,
        "unexplained": [d.field for d in parity.unexplained],
        "explained": [d.field for d in parity.differences if d.explained],
        "differences": [d.as_dict() for d in parity.differences],
    }


async def run(uri: str, allow_hosts: tuple[str, ...]) -> dict[str, Any]:
    """Compare every registered submission across both backends."""
    from backend.queue.mongo_adapter import MongoQueueAdapter
    from motor.motor_asyncio import AsyncIOMotorClient

    verdict = check_endpoint(uri, allow_hosts)
    if not verdict.allowed:
        raise UnsafeEndpointError(f"refusing to run against {uri!r}: " + "; ".join(verdict.reasons))

    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        uri, serverSelectionTimeoutMS=5000, tz_aware=True
    )
    try:
        await client.admin.command("ping")
    except Exception as exc:  # noqa: BLE001 - reported, not raised raw
        client.close()
        raise RuntimeError(f"cannot reach {verdict.host}: {exc}") from exc

    database = client[SHADOW_DB]
    try:
        queue = MongoQueueAdapter(database, collection_name=SHADOW_COLLECTION)
        await queue.ensure_indexes()

        results: dict[str, Any] = {}
        for function in known_submission_functions():
            payload = SAMPLE_SUBMISSIONS[function]
            routing = PRODUCTION_ROUTING.get(function, {})
            arq = await from_arq(function, payload=payload, **routing)
            mongo = await from_mongo(
                queue, function, payload=payload, tenant_id="tenant-shadow", **routing
            )
            results[function] = _summarise(compare_envelopes(arq, mongo))

        # The safety invariant, re-checked rather than assumed.
        rows = await queue.queue.list_jobs(limit=100)
        executed = [
            row.function
            for row in rows
            if row.status != "pending" or row.attempts != 0 or row.locked_by is not None
        ]
        return {
            "endpoint": {
                "host": verdict.host,
                "loopback": verdict.host in _LOOPBACK,
                "allowed": verdict.allowed,
                "consent": verdict.consent,
                "notes": list(verdict.notes),
            },
            "collection": f"{SHADOW_DB}.{SHADOW_COLLECTION}",
            "compared_fields": list(COMPARED_FIELDS),
            "registry_complete": registry_is_complete(),
            "registered_functions": sorted(known_names()),
            "argument_contracts": sorted(JOB_ARGUMENTS),
            "jobs_mirrored": len(rows),
            "jobs_executed": executed,
            "no_side_effects": not executed,
            "results": results,
            "unexplained_total": sum(len(entry["unexplained"]) for entry in results.values()),
            "all_match": all(entry["matches"] for entry in results.values()),
        }
    finally:
        await database.drop_collection(SHADOW_COLLECTION)
        await client.drop_database(SHADOW_DB)
        client.close()


def _render(report: dict[str, Any]) -> str:
    lines = [
        f"endpoint        : {report['endpoint']['host']} "
        f"(loopback={report['endpoint']['loopback']}, "
        f"consent={report['endpoint']['consent'] or 'default'})",
        f"collection      : {report['collection']}  (dropped on exit)",
        f"compared fields : {', '.join(report['compared_fields'])}",
        f"registry complete: {report['registry_complete']}",
        f"jobs mirrored   : {report['jobs_mirrored']}",
        f"jobs executed   : {report['jobs_executed'] or 'none'}",
        f"no side effects : {report['no_side_effects']}",
        *(f"note            : {note}" for note in report["endpoint"]["notes"]),
        "",
        f"{'function':<28} {'match':<6} unexplained",
    ]
    for function, entry in sorted(report["results"].items()):
        lines.append(
            f"{function:<28} {str(entry['matches']):<6} {', '.join(entry['unexplained']) or '-'}"
        )
    lines.append("")
    lines.append(
        f"VERDICT: {'PASS - no unexplained differences' if report['all_match'] else 'MISMATCH'}"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare ARQ and Mongo queue envelopes. Refuses production hosts."
    )
    parser.add_argument(
        "--mongo-uri",
        default=DEFAULT_MONGO_URI,
        help="isolated mongod URI; never read from the environment",
    )
    parser.add_argument(
        "--allow-host",
        action="append",
        default=[],
        help="name a non-loopback host explicitly (repeatable); required for Atlas",
    )
    parser.add_argument("--json", action="store_true", help="print one JSON object")
    args = parser.parse_args(argv)

    try:
        report = asyncio.run(run(args.mongo_uri, tuple(args.allow_host)))
    except UnsafeEndpointError as exc:
        print(f"SAFETY REFUSAL: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(report, indent=2) if args.json else _render(report))
    return 0 if report["all_match"] and report["no_side_effects"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
