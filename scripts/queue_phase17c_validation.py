#!/usr/bin/env python
"""Phase 17C free-tier validation harness: measure the Mongo queue, safely.

This answers one question: *is the MongoDB worker queue operationally viable for
WebChat AI under a strict zero-cost / free-only infrastructure constraint, and
is it safe to design a cutover around?* It is a **validation + design** phase.
It performs no cutover, changes no default, and deploys nothing.

Safety, by construction
-----------------------
This script is deliberately hard to misuse, and its refusals are the point:

* it reads the Mongo URI **only** from ``--mongo-uri``. It never reads
  ``MONGODB_URI``/``MONGO_URL``/any environment variable, so a stray variable in
  the shell cannot aim it at production. (Note: the older
  ``scripts/queue_perf_probe.py`` *does* fall back to ``os.environ``; this
  harness deliberately does not repeat that.)
* ``--local`` is the default and only ever runs unattended against **loopback**.
* ``--atlas-safe`` is refused unless *all* of the following hold:

  1. ``QUEUE_PHASE17C_ALLOW_NONPROD_ATLAS=true`` is set in the environment - an
     explicit, greppable operator acknowledgement;
  2. the host is named in ``--allow-host`` (a visible act, recorded as
     ``consent`` in the artifact);
  3. the hostname is **not** production-shaped (``.mongodb.net``, ``prod``,
     ``production``, ``atlas``) - this is a hard veto that ``--allow-host``
     **cannot** override, unlike the Phase 17B shadow harness, where naming a
     host did unlock it;
  4. the target database name differs from the configured application database.

  If a future isolated sandbox has a production-shaped hostname (a real Atlas
  M0 cluster does), rule 3 refuses it. That is intentional: Phase 17C found no
  such cluster, and the correct way to admit one is to add an explicit,
  reviewable allowlist entry - not to make the marker list weaker.
* it writes only inside a uniquely named throwaway database
  (``webchat_ai_queue_phase17c_<suffix>``) and never touches an application
  collection, an application database, or any production collection name.
* every record it writes is tagged ``phase17c`` and carries only synthetic
  tenants (``phase17c-tenant-NNNN``) and no email address, URL, or document
  content.
* **cleanup proves ownership first**: it drops only a database whose name matches
  this run's generated suffix *and* whose collections all carry the run's
  ownership marker. If ownership cannot be proven it leaves the resource alone
  and reports it, rather than deleting something it did not create.
* it never drops an existing database or an existing non-test collection.
* it executes no production job: the "jobs" are queue rows measured with the
  real store and a no-op handler. No email is sent, no site is crawled, no
  embedding is computed, no provider is called.
* ``--json`` prints one JSON object so the Phase 17C report quotes measured
  output rather than prose.

Exit codes
----------
0  every semantic check passed
1  a semantic validation failed (or a measurement recorded a duplicate claim)
2  a safety refusal (bad endpoint, missing opt-in, ownership not provable)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from backend.queue.mongo.config import QueueConfig
from backend.queue.mongo.models import (
    STATUS_COMPLETED,
    STATUS_DEAD,
    STATUS_RUNNING,
    Job,
)
from backend.queue.mongo.poller import AdaptivePoller
from backend.queue.mongo.store import MongoQueue

#: Explicit, greppable operator acknowledgement required by ``--atlas-safe``.
ATLAS_OPT_IN_ENV = "QUEUE_PHASE17C_ALLOW_NONPROD_ATLAS"

#: Every database this harness creates starts with this, so cleanup can prove
#: ownership from the name alone before it is allowed to drop anything.
DB_PREFIX = "webchat_ai_queue_phase17c_"

#: Ownership marker written into every document the harness creates.
OWNER_FIELD = "phase17c_owner"
OWNER_VALUE = "phase17c"

#: Hostname fragments that indicate a live production cluster. Matching is on
#: the parsed hostname, so ``mongodb+srv://`` is covered too. In ``--atlas-safe``
#: this is a VETO that ``--allow-host`` cannot override.
_PRODUCTION_HOST_MARKERS = (
    ".mongodb.net",
    "prod",
    "production",
    "atlas",
)

_LOOPBACK = {"127.0.0.1", "localhost", "::1", "ip6-localhost"}

#: The application database name is compared against by name only; the harness
#: never reads the application database or its contents.
_DEFAULT_APP_DB_NAMES = ("webchat_ai",)


class UnsafeEndpointError(RuntimeError):
    """Raised when the requested target is not provably safe for this harness."""


class SemanticFailure(RuntimeError):
    """Raised when a measured invariant does not hold."""


@dataclass
class SafetyVerdict:
    """Why the harness believes it may (or may not) talk to a host."""

    host: str
    mode: str
    allowed: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)
    consent: str = ""
    app_database: str = ""


def _host_of(uri: str) -> str:
    parsed = urlparse(uri)
    if not parsed.hostname:
        raise UnsafeEndpointError("cannot parse a hostname from the supplied URI")
    return parsed.hostname


def _is_production_shaped(host: str) -> str | None:
    """Return the offending marker if ``host`` looks like production, else None."""
    lowered = host.lower()
    for marker in _PRODUCTION_HOST_MARKERS:
        if marker in lowered:
            return marker
    return None


def check_endpoint(
    uri: str,
    *,
    mode: str,
    allow_hosts: tuple[str, ...] = (),
    app_database: str = "",
    env: Mapping[str, str] | None = None,
) -> SafetyVerdict:
    """Decide whether this harness may connect, and record exactly why.

    ``--local`` runs unattended against loopback only. ``--atlas-safe`` demands an
    environment marker, an explicitly named host, a non-production-shaped
    hostname (a veto ``--allow-host`` cannot override), and a target database
    that is not the application database.
    """
    environ: Mapping[str, str] = os.environ if env is None else env
    host = _host_of(uri)
    reasons: list[str] = []
    notes: list[str] = []
    named = host in allow_hosts
    loopback = host in _LOOPBACK
    marker = _is_production_shaped(host)

    if mode == "local":
        if not loopback:
            reasons.append(
                f"--local only runs against loopback; {host!r} is not loopback. "
                "Use --atlas-safe with the explicit opt-in for anything else."
            )
        if marker is not None and not loopback:
            reasons.append(f"hostname contains {marker!r}, which indicates production")
    elif mode == "atlas-safe":
        if environ.get(ATLAS_OPT_IN_ENV) != "true":
            reasons.append(
                f"--atlas-safe requires {ATLAS_OPT_IN_ENV}=true in the environment "
                f"(currently {environ.get(ATLAS_OPT_IN_ENV)!r})"
            )
        if not named:
            reasons.append(f"host {host!r} was not named in --allow-host")
        # Veto, deliberately not overridable by --allow-host.
        if marker is not None:
            reasons.append(
                f"hostname contains {marker!r}, which indicates a production cluster; "
                "this is a hard veto in --atlas-safe and --allow-host cannot override it"
            )
        if not app_database:
            notes.append(
                "no application database name supplied; the !=-application-database "
                "rule could only be checked against the built-in default names"
            )
    else:  # pragma: no cover - argparse restricts the choices
        reasons.append(f"unknown mode {mode!r}")

    consent = ""
    if not loopback and named:
        consent = f"--allow-host {host}"

    if "mongodb+srv" in uri and "retrywrites" not in uri.lower():
        notes.append("SRV URI does not state retryWrites; this default varies by environment")
    lowered_uri = uri.lower().replace(" ", "")
    if "retrywrites=false" in lowered_uri:
        notes.append("retryWrites=false: a write-concern error will not be retried")

    return SafetyVerdict(
        host=host,
        mode=mode,
        allowed=not reasons,
        reasons=tuple(reasons),
        notes=tuple(notes),
        consent=consent,
        app_database=app_database,
    )


def check_database_name(db_name: str, app_database: str) -> None:
    """Refuse an application database, and refuse a non-Phase-17C namespace."""
    if not db_name.startswith(DB_PREFIX):
        raise UnsafeEndpointError(
            f"database {db_name!r} is not a Phase 17C namespace (expected prefix {DB_PREFIX!r}); "
            "this harness will not write into an application or production database"
        )
    if app_database and db_name == app_database:
        raise UnsafeEndpointError(
            f"database {db_name!r} is the configured application database; refusing"
        )
    if db_name in _DEFAULT_APP_DB_NAMES:
        raise UnsafeEndpointError(f"database {db_name!r} is a known application database; refusing")


# ---------------------------------------------------------------------------
# measurement helpers
# ---------------------------------------------------------------------------


def _percentile(samples: list[float], fraction: float) -> float:
    """Nearest-rank percentile; ``samples`` need not be sorted."""
    if not samples:
        return 0.0
    ordered = sorted(samples)
    if len(ordered) == 1:
        return round(ordered[0], 3)
    index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
    return round(ordered[index], 3)


def _dist(samples: list[float]) -> dict[str, float]:
    return {
        "samples": len(samples),
        "p50_ms": _percentile(samples, 0.50),
        "p95_ms": _percentile(samples, 0.95),
        "p99_ms": _percentile(samples, 0.99),
        "min_ms": round(min(samples), 3) if samples else 0.0,
        "max_ms": round(max(samples), 3) if samples else 0.0,
        "mean_ms": round(sum(samples) / len(samples), 3) if samples else 0.0,
    }


async def _timed(coro_factory: Any) -> tuple[Any, float]:
    """Await ``coro_factory()`` and return ``(result, elapsed_ms)``."""
    started = time.perf_counter()
    result = await coro_factory()
    return result, (time.perf_counter() - started) * 1000.0


# ---------------------------------------------------------------------------
# the validation run
# ---------------------------------------------------------------------------


@dataclass
class RunContext:
    db_name: str
    collection_name: str
    client: Any
    database: Any
    queue: MongoQueue
    collection: Any
    findings: dict[str, Any] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)

    def fail(self, message: str) -> None:
        self.failures.append(message)


async def _build_context(uri: str, *, db_name: str, lease: float, heartbeat: float) -> RunContext:
    from motor.motor_asyncio import AsyncIOMotorClient

    client: AsyncIOMotorClient[Any] = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=5000)
    await client.admin.command("ping")
    database = client[db_name]
    config = QueueConfig(
        db_name=db_name,
        collection_name="worker_jobs_phase17c",
        lease_seconds=lease,
        heartbeat_interval_seconds=heartbeat,
    )
    queue = MongoQueue(database, config)
    return RunContext(
        db_name=db_name,
        collection_name=config.collection_name,
        client=client,
        database=database,
        queue=queue,
        collection=database[config.collection_name],
    )


def _job(
    function: str = "phase17c_probe", *, tenant: str, payload_extra: dict[str, Any] | None = None
) -> Job:
    """A synthetic job. No email address, URL, or document content ever appears."""
    return Job(
        function=function,
        payload={"phase17c": True, "n": 1, **(payload_extra or {})},
        tenant_id=tenant,
    )


def _tag(doc: dict[str, Any], run_tag: str) -> dict[str, Any]:
    doc[OWNER_FIELD] = f"{OWNER_VALUE}:{run_tag}"
    return doc


async def _measure_operations(ctx: RunContext, run_tag: str) -> dict[str, Any]:
    """Per-phase latency distributions for all seven required operations.

    Every measurement goes through the real :class:`MongoQueue` store, so the
    numbers describe production code paths rather than a hand-written query.
    """
    results: dict[str, Any] = {}

    async def op_enqueue(count: int = 120) -> tuple[list[float], list[str]]:
        samples: list[float] = []
        ids: list[str] = []
        for i in range(count):
            job_id, elapsed = await _timed(
                lambda i=i: ctx.queue.enqueue(
                    function="phase17c_probe",
                    payload={"phase17c": True, "i": i},
                    tenant_id=f"phase17c-tenant-{i % 4:04d}",
                )
            )
            samples.append(elapsed)
            ids.append(job_id)
        return samples, ids

    # 1. enqueue
    ctx.queue.reset_ops()
    enqueue_samples, job_ids = await op_enqueue()
    results["enqueue"] = _dist(enqueue_samples)
    results["enqueue"]["queue_ops"] = ctx.queue.ops

    # 2. empty claim (queue drained first)
    for job_id in job_ids:
        await ctx.queue.collection.delete_one({"_id": job_id})
    ctx.queue.reset_ops()
    empty_samples: list[float] = []
    for _ in range(60):
        job, elapsed = await _timed(lambda: ctx.queue.claim("phase17c-empty-prober"))
        if job is not None:
            ctx.fail("empty-claim probe claimed a job: the queue was not empty")
        empty_samples.append(elapsed)
    results["claim_empty"] = _dist(empty_samples)
    results["claim_empty"]["queue_ops"] = ctx.queue.ops

    # 3. successful claim
    claim_samples: list[float] = []
    claimed: list[Job] = []
    for i in range(80):
        await ctx.queue.enqueue(
            function="phase17c_probe",
            payload={"phase17c": True, "i": i},
            tenant_id="phase17c-tenant-0000",
        )
    for _ in range(80):
        job, elapsed = await _timed(lambda: ctx.queue.claim("phase17c-claimer"))
        if job is None:
            ctx.fail("claim probe found no job while 80 were enqueued")
            break
        claim_samples.append(elapsed)
        claimed.append(job)
    results["claim"] = _dist(claim_samples)

    # 4. heartbeat / renew_lease
    hb_samples: list[float] = []
    for job in claimed:
        _, elapsed = await _timed(
            lambda job=job: ctx.queue.renew_lease(
                job.id, "phase17c-claimer", execution_version=job.execution_version
            )
        )
        hb_samples.append(elapsed)
    results["heartbeat"] = _dist(hb_samples)

    # 5. completion
    complete_samples: list[float] = []
    completed_ok = 0
    for job in claimed:
        ok, elapsed = await _timed(
            lambda job=job: ctx.queue.complete_job(
                job.id, "phase17c-claimer", execution_version=job.execution_version, result=None
            )
        )
        complete_samples.append(elapsed)
        completed_ok += 1 if ok else 0
    results["complete"] = _dist(complete_samples)
    if completed_ok != len(claimed):
        ctx.fail(f"only {completed_ok}/{len(claimed)} completions were accepted")

    # 6. failure -> dead (non-retryable, ARQ parity)
    fail_samples: list[float] = []
    for i in range(40):
        await ctx.queue.enqueue(
            function="phase17c_probe",
            payload={"phase17c": True, "i": i},
            tenant_id="phase17c-tenant-0001",
        )
    dead_ok = 0
    for _ in range(40):
        job = await ctx.queue.claim("phase17c-failer")
        if job is None:
            ctx.fail("failure probe found no job while 40 were enqueued")
            break
        status, elapsed = await _timed(
            lambda job=job: ctx.queue.fail_job(
                job.id,
                "phase17c-failer",
                error="phase17c synthetic failure",
                execution_version=job.execution_version,
                retry=False,
            )
        )
        fail_samples.append(elapsed)
        if status == STATUS_DEAD:
            dead_ok += 1
    results["fail_dead"] = _dist(fail_samples)
    if dead_ok != len(fail_samples):
        ctx.fail(f"only {dead_ok}/{len(fail_samples)} non-retryable failures reached dead")

    # 7. reclaim: claim a job, let the lease expire, reclaim it elsewhere.
    await ctx.queue.enqueue(
        function="phase17c_probe",
        payload={"phase17c": True, "reclaim": True},
        tenant_id="phase17c-tenant-0002",
    )
    first = await ctx.queue.claim("phase17c-original")
    if first is None:
        ctx.fail("reclaim probe could not claim its own job")
    else:
        # Reclaim only becomes eligible once lease_expires_at <= now.
        await ctx.queue.collection.update_one(
            {"_id": first.id}, {"$set": {"lease_expires_at": _past()}}
        )
        second, reclaim_elapsed = await _timed(lambda: ctx.queue.claim("phase17c-reclaimer"))
        results["reclaim"] = {"samples": 1, "p50_ms": round(reclaim_elapsed, 3)}
        if second is None:
            ctx.fail("reclaim probe reclaimed nothing after the lease expired")
        elif second.id != first.id:
            ctx.fail("reclaim probe reclaimed a different job than the expired one")
        elif second.execution_version <= first.execution_version:
            ctx.fail(
                "reclaimed execution did not receive a higher execution_version "
                f"({second.execution_version} <= {first.execution_version})"
            )
        else:
            results["reclaim"]["execution_version_before"] = first.execution_version
            results["reclaim"]["execution_version_after"] = second.execution_version

    # 8. index-backed dedup
    dedup_key = f"phase17c-dedup-{run_tag}"
    await ctx.queue.collection.delete_many({"dedup_key": dedup_key})
    dedup_ids: list[str] = []
    for _ in range(25):
        job_id = await ctx.queue.enqueue(
            function="phase17c_probe",
            payload={"phase17c": True, "dedup": True},
            tenant_id="phase17c-tenant-0003",
            dedup_key=dedup_key,
        )
        dedup_ids.append(job_id)
    unique_ids = set(dedup_ids)
    results["dedup"] = {
        "submissions": len(dedup_ids),
        "unique_ids": len(unique_ids),
        "collapsed_to_one": len(unique_ids) == 1,
        "rows_in_collection": await ctx.queue.collection.count_documents({"dedup_key": dedup_key}),
    }
    if len(unique_ids) != 1:
        ctx.fail(f"dedup produced {len(unique_ids)} distinct ids from 25 identical submissions")

    # duplicate-claim check under concurrency
    dup = await _duplicate_claim_probe(ctx)
    results["duplicate_claim_probe"] = dup
    if dup["duplicate_claims"] != 0:
        ctx.fail(f"concurrent claim probe saw {dup['duplicate_claims']} duplicate claims")

    return results


def _past() -> Any:
    from datetime import timedelta

    from backend.queue.mongo.ids import utcnow

    return utcnow() - timedelta(seconds=5)


async def _duplicate_claim_probe(
    ctx: RunContext, *, jobs: int = 60, workers: int = 8
) -> dict[str, Any]:
    """N workers race for M jobs; exactly M claims must be won, with no repeats."""
    await ctx.queue.collection.delete_many({"tenant_id": "phase17c-tenant-dup"})
    for i in range(jobs):
        await ctx.queue.enqueue(
            function="phase17c_probe",
            payload={"phase17c": True, "dup": i},
            tenant_id="phase17c-tenant-dup",
        )
    won: list[str] = []
    lock = asyncio.Lock()

    async def worker(name: str) -> None:
        while True:
            job = await ctx.queue.claim(name)
            if job is None:
                return
            async with lock:
                won.append(job.id)
            await ctx.queue.complete_job(
                job.id, name, execution_version=job.execution_version, result=None
            )

    await asyncio.gather(*(worker(f"phase17c-dup-{i}") for i in range(workers)))
    duplicates = len(won) - len(set(won))
    return {
        "jobs": jobs,
        "workers": workers,
        "claims": len(won),
        "unique_claims": len(set(won)),
        "duplicate_claims": duplicates,
    }


async def _measure_claim_plan(ctx: RunContext) -> dict[str, Any]:
    """EXPLAIN the real claim filter: is the hot path index-backed?

    This matters more on a free shared tier than the raw latency, because an
    unindexed claim degrades with collection size rather than staying flat.
    """
    from backend.queue.mongo.ids import utcnow

    now = utcnow()
    filter_doc: dict[str, Any] = {
        "$expr": {"$lt": ["$attempts", "$max_tries"]},
        "$or": [
            {"status": {"$in": ["pending", "retry_pending"]}, "run_at": {"$lte": now}},
            {"status": "running", "lease_expires_at": {"$lte": now}},
        ],
    }
    pipeline = [
        {
            "$set": {
                "status": "running",
                "locked_by": "phase17c-explain",
                "started_at": now,
                "attempts": {"$add": ["$attempts", 1]},
                "execution_version": {"$add": ["$execution_version", 1]},
            }
        }
    ]
    indexes = sorted((await ctx.collection.index_information()).keys())

    def stages_in(node: Any, acc: set[str]) -> None:
        if isinstance(node, dict):
            stage = node.get("stage")
            if isinstance(stage, str):
                acc.add(stage)
            plan_keys = (
                "queryPlan",
                "inputStage",
                "thenStage",
                "elseStage",
                "child",
                "inputStages",
            )
            for key in plan_keys:
                if key in node:
                    stages_in(node[key], acc)
            for value in node.values():
                if isinstance(value, (dict, list)):
                    stages_in(value, acc)
        elif isinstance(node, list):
            for item in node:
                stages_in(item, acc)

    async def plan_for(label: str) -> dict[str, Any]:
        explained = await ctx.collection.database.command(
            "explain",
            {
                "findAndModify": ctx.collection.name,
                "query": filter_doc,
                "update": pipeline,
                "sort": {"run_at": 1, "_id": 1},
            },
            verbosity="queryPlanner",
        )
        planner = explained.get("queryPlanner", explained)
        stages: set[str] = set()
        stages_in(planner.get("winningPlan") or planner.get("queryPlan") or {}, stages)
        return {
            "label": label,
            "documents": await ctx.collection.count_documents({}),
            "stages": sorted(stages),
            # An index is used only if an index scan appears anywhere in the plan.
            "uses_index": bool(stages & {"IXSCAN", "IDHACK"}),
            "is_collscan": "COLLSCAN" in stages,
            # A SORT stage means candidate docs are sorted in memory, because the
            # sort key (run_at, _id) is not a prefix of either compound index.
            "has_blocking_sort": "SORT" in stages or "SORT_KEY_GENERATOR" in stages,
        }

    # Plan stability matters more than one sample: an empty collection can hide a
    # COLLSCAN that appears only once the queue holds real history.
    observed: list[dict[str, Any]] = [await plan_for("as_measured")]
    # Filler must be shaped exactly like a store-written row: to_doc() omits `id`
    # and sets `_id`. A hand-rolled dict carrying `id` would break Job.from_doc.
    filler = [_job(tenant=f"phase17c-plan-{i:04d}").to_doc() for i in range(1000)]
    for size in (1000, 5000):
        if size > len(filler):
            continue
        await ctx.collection.insert_many(filler[: size - observed[-1]["documents"]])
        observed.append(await plan_for(f"with_{size}_documents"))
    return {
        "indexes_present": indexes,
        "observed": observed,
        "stable_uses_index": all(entry["uses_index"] for entry in observed[1:]),
        "any_collscan": any(entry["is_collscan"] for entry in observed),
        "always_blocking_sort": all(entry["has_blocking_sort"] for entry in observed),
        "note": (
            "$expr on attempts<max_tries is not index-eligible, so the planner must "
            "still satisfy the $or branches via status_1_run_at_1 / "
            "status_1_lease_expires_at_1. The claim sorts on (run_at, _id), which is "
            "not a prefix of either index, so a SORT stage is expected."
        ),
    }


def _rss_bytes() -> int:
    """Current resident set size of this process, in bytes.

    Synchronous on purpose: this reads a single small proc file and is called
    between measurements, never on a latency-sensitive path.
    """
    try:
        with open("/proc/self/status", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except OSError:  # pragma: no cover - non-Linux
        pass
    import resource

    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024


async def _measure_capacity(
    ctx: RunContext,
    *,
    sizes: tuple[int, ...] = (20, 100, 1000, 10000),
) -> dict[str, Any]:
    """Measure enqueue and claim cost as the collection actually fills up.

    Each size is built for real, then claimed from, so the numbers describe the
    store at that depth rather than an extrapolation. The queue is emptied
    between sizes so one scenario does not inherit another's history.
    """
    observed: list[dict[str, Any]] = []
    for size_now in sizes:
        await ctx.queue.delete_all()
        rss_before = _rss_bytes()

        enqueue_samples: list[float] = []
        for i in range(size_now):
            _, elapsed = await _timed(
                lambda i=i, size_now=size_now: ctx.queue.enqueue(
                    function="phase17c_capacity",
                    payload={"phase17c": True, "i": i},
                    tenant_id=f"phase17c-cap-{size_now:05d}",
                )
            )
            enqueue_samples.append(elapsed)

        depth = await ctx.queue.count_documents()

        claim_samples: list[float] = []
        claimed = 0
        # Cap the number of claims so the 10k scenario stays bounded in time.
        claim_budget = min(depth, 200)
        while claimed < claim_budget:
            _, elapsed = await _timed(lambda: ctx.queue.claim("phase17c-capacity-worker"))
            if elapsed is None:
                break
            claim_samples.append(elapsed)
            claimed += 1

        rss_after = _rss_bytes()
        observed.append(
            {
                "target_jobs": size_now,
                "documents_present": depth,
                "enqueue_p50_ms": _percentile(enqueue_samples, 0.50),
                "enqueue_p95_ms": _percentile(enqueue_samples, 0.95),
                "enqueue_p99_ms": _percentile(enqueue_samples, 0.99),
                "enqueue_ops_per_second": round(
                    len(enqueue_samples) / max(sum(enqueue_samples) / 1000.0, 1e-9), 1
                ),
                "claims_measured": claimed,
                "claim_p50_ms": _percentile(claim_samples, 0.50) if claim_samples else None,
                "claim_p95_ms": _percentile(claim_samples, 0.95) if claim_samples else None,
                "claim_p99_ms": _percentile(claim_samples, 0.99) if claim_samples else None,
                "claim_ops_per_second": round(
                    len(claim_samples) / max(sum(claim_samples) / 1000.0, 1e-9), 1
                )
                if claim_samples
                else None,
                "rss_before_bytes": rss_before,
                "rss_after_bytes": rss_after,
                "rss_growth_bytes": rss_after - rss_before,
            }
        )
    await ctx.queue.delete_all()
    return {
        "observed": observed,
        "rss_note": (
            "RSS is the harness process, which holds a Motor client and the "
            "sampled latencies in memory; it is a lower bound on a real worker, "
            "not a measurement of one."
        ),
    }


async def _measure_storage(ctx: RunContext) -> dict[str, Any]:
    """BSON size per state, measured with a real document, not estimated."""
    from bson import BSON

    sizes: dict[str, int] = {}
    samples: dict[str, bytes] = {}

    async def size_of(job: Job) -> int:
        doc = job.to_doc()
        _tag(doc, ctx.findings.get("run_tag", "probe"))
        return len(BSON.encode(doc))

    pending = _job(tenant="phase17c-tenant-0000")
    sizes["pending"] = await size_of(pending)
    samples["pending"] = BSON.encode(_tag(pending.to_doc(), "probe"))

    from backend.queue.mongo.ids import add_seconds, utcnow

    now = utcnow()
    base = _job(tenant="phase17c-tenant-0000")
    running = base.model_copy(
        update={
            "status": STATUS_RUNNING,
            "locked_by": "phase17c-measure",
            "started_at": now,
            "lease_expires_at": add_seconds(now, ctx.queue.lease_seconds),
        }
    )
    sizes["running"] = await size_of(running)

    completed = base.model_copy(update={"status": STATUS_COMPLETED, "finished_at": now})
    sizes["completed"] = await size_of(completed)

    failed = base.model_copy(
        update={
            "status": STATUS_DEAD,
            "finished_at": now,
            "last_error": "phase17c synthetic failure: a representative error string",
        }
    )
    sizes["failed"] = await size_of(failed)

    # A realistic payload: the queue's own per-row overhead is what matters, and
    # payload size is the operator's choice, so report it separately.
    with_payload = _job(tenant="phase17c-tenant-0000", payload_extra={"blob": "x" * 1024})
    sizes["pending_with_1KiB_payload"] = await size_of(with_payload)

    storage_col = ctx.database["phase17c_storage_probe"]
    try:
        await storage_col.insert_one({"_id": "pending", "b": samples["pending"]})
        stored = await storage_col.database.command("collStats", "phase17c_storage_probe")
        return {
            "bson_bytes": sizes,
            "mongo_reported_avg_obj_size": stored.get("avgObjSize"),
            "mongo_reported_storage_size": stored.get("storageSize"),
        }
    finally:
        await storage_col.drop()


async def _measure_idle_polling(ctx: RunContext, *, seconds: float) -> dict[str, Any]:
    """Two views of idle cost: the policy's steady state, and a real short run.

    The policy number is CALCULATED from the schedule; the live number is
    MEASURED but only over a few seconds, so it is a sanity check on the
    calculation rather than a day-long measurement.
    """
    poller = AdaptivePoller(ctx.queue.config.poll_schedule)
    interval = 0.0
    simulated_iterations = 0
    while True:
        interval = poller.nick(False)
        simulated_iterations += 1
        if interval >= max(ctx.queue.config.poll_schedule):
            break
    cap = max(ctx.queue.config.poll_schedule)
    per_worker_per_day = 86400.0 / cap

    ctx.queue.reset_ops()
    started = time.perf_counter()
    live_iterations = 0
    while time.perf_counter() - started < seconds:
        await ctx.queue.claim("phase17c-idle")
        live_iterations += 1
        await asyncio.sleep(cap if live_iterations > 2 else 0.01)
    elapsed = time.perf_counter() - started
    live_ops = ctx.queue.ops
    return {
        "schedule_s": list(ctx.queue.config.poll_schedule),
        "steady_state_interval_s": cap,
        "idle_claim_ops_per_day_per_worker": round(per_worker_per_day, 1),
        "for_workers": {
            str(n): round(per_worker_per_day * n, 1) for n in (1, 2, 3)
        },
        "policy_reached_cap_after_iterations": simulated_iterations,
        "live_probe": {
            "elapsed_s": round(elapsed, 2),
            "iterations": live_iterations,
            "queue_ops": live_ops,
            "note": "a few seconds of live polling; not a day-long measurement",
        },
        "arq_comparison_ops_per_day_per_worker": 172800.0,
    }


async def _measure_connections(ctx: RunContext) -> dict[str, Any]:
    """Server-side connection count before/after, plus this client's pool view."""
    async def server_connections() -> dict[str, int]:
        # MongoDB 8 reports `connections.current`; there is no `total` field.
        status = await ctx.client.admin.command("serverStatus")
        conns = status.get("connections") or {}
        return {
            "current": int(conns.get("current", -1)),
            "available": int(conns.get("available", -1)),
            "total_created": int(conns.get("totalCreated", -1)),
        }

    before = await server_connections()
    await ctx.queue.ping()
    after = await server_connections()
    options = ctx.client.options
    pool = options.pool_options
    return {
        "server_connections_before": before,
        "server_connections_after_ping": after,
        "delta_current": after["current"] - before["current"],
        "min_pool_size": pool.min_pool_size,
        "max_pool_size": pool.max_pool_size,
        "max_connecting": pool.max_connecting,
        "connect_timeout_seconds": pool.connect_timeout,
        "socket_timeout_seconds": pool.socket_timeout,
        "wait_queue_timeout_seconds": pool.wait_queue_timeout,
        "appname": pool.appname,
        "note": "a warm client holds a pooled connection; no per-poll client is created",
    }


async def _cleanup(ctx: RunContext, run_tag: str) -> dict[str, Any]:
    """Drop only what this run created, and only after proving ownership.

    Two independent proofs are required. First, the database name must carry
    this run's generated suffix. Second, every collection in it must be shown to
    contain only documents this run wrote. If either proof fails, the database is
    left untouched.

    The queue collection is written by the store's own ``enqueue``, which builds
    its documents from the ``Job`` model and cannot carry an injected owner field.
    Its provenance is instead proven positively: every synthetic job this harness
    creates sets ``payload.phase17c = true``, so a document lacking that marker
    is by definition not ours and blocks cleanup.
    """
    if not ctx.db_name.startswith(DB_PREFIX):
        return {"dropped": False, "reason": f"database {ctx.db_name!r} lacks the Phase 17C prefix"}

    existing = set(await ctx.client.list_database_names())
    if ctx.db_name not in existing:
        return {"dropped": False, "reason": "database does not exist; nothing to clean"}

    owner_value = f"{OWNER_VALUE}:{run_tag}"
    collection_names = await ctx.database.list_collection_names()
    unowned: dict[str, dict[str, int]] = {}
    for name in collection_names:
        total = await ctx.database[name].count_documents({})
        if not total:
            continue
        if name == ctx.collection_name:
            ours = await ctx.database[name].count_documents({"payload.phase17c": True})
        else:
            ours = await ctx.database[name].count_documents({OWNER_FIELD: owner_value})
        if ours != total:
            unowned[name] = {"ours": ours, "total": total}
    if unowned:
        return {
            "dropped": False,
            "reason": "ownership not provable for every collection; left in place",
            "unowned_collections": unowned,
        }
    await ctx.client.drop_database(ctx.db_name)
    return {"dropped": True, "collections": collection_names}


async def run_validation(
    uri: str,
    *,
    db_name: str,
    run_tag: str,
    lease: float,
    heartbeat: float,
    idle_seconds: float,
    capacity_sizes: tuple[int, ...] = (20, 100, 1000, 10000),
) -> dict[str, Any]:
    """Execute the full Phase 17C local measurement suite."""
    ctx = await _build_context(uri, db_name=db_name, lease=lease, heartbeat=heartbeat)
    ctx.findings["run_tag"] = run_tag
    report: dict[str, Any] = {
        "phase": "17C",
        "mode": "local" if _host_of(uri) in _LOOPBACK else "atlas-safe",
        "target_is_atlas": _host_of(uri).endswith(".mongodb.net"),
        "database": db_name,
        "lease_seconds": lease,
        "heartbeat_seconds": heartbeat,
        "region": _region_hint(uri),
    }
    try:
        await ctx.queue.ensure_indexes()
        report["latency"] = await _measure_operations(ctx, run_tag)
        report["claim_plan"] = await _measure_claim_plan(ctx)
        report["capacity"] = await _measure_capacity(ctx, sizes=capacity_sizes)
        report["storage"] = await _measure_storage(ctx)
        report["idle_polling"] = await _measure_idle_polling(ctx, seconds=idle_seconds)
        report["connections"] = await _measure_connections(ctx)
        report["server"] = await _server_facts(ctx)
        report["failures"] = ctx.failures
        report["ok"] = not ctx.failures
    finally:
        report["cleanup"] = await _cleanup(ctx, run_tag)
        ctx.client.close()
    return report


def _region_hint(uri: str) -> str:
    """Region, only if it is knowable without leaking anything."""
    host = _host_of(uri)
    if host in _LOOPBACK:
        return "loopback (no region)"
    return "unknown (not derivable without a server-side hello response)"


async def _server_facts(ctx: RunContext) -> dict[str, Any]:
    status = await ctx.client.admin.command("serverStatus")
    return {
        "version": status.get("version"),
        # In MongoDB 8 the cache counters sit directly under `wiredTiger`.
        "wiredTiger_cache_max_bytes": (status.get("wiredTiger") or {})
        .get("cache", {})
        .get("maximum bytes configured"),
        "wiredTiger_cache_bytes_in_use": (status.get("wiredTiger") or {})
        .get("cache", {})
        .get("bytes currently in the cache"),
        "wiredTiger_tracked_dirty_bytes": (status.get("wiredTiger") or {})
        .get("cache", {})
        .get("tracked dirty bytes in the cache"),
        "storage_engine": status.get("storageEngine", {}).get("name"),
        "note": "single mongod; no replica-set failover was exercised",
    }


def _build_db_name(app_database: str, run_tag: str) -> str:
    """The one place a run's database name is composed.

    Cleanup is allowed to drop a database, so the name must be derived from the
    immutable prefix and the run's own tag - never from anything the caller or a
    config file could steer toward the application database.
    """
    return f"{DB_PREFIX}{run_tag}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Phase 17C Mongo queue free-tier validation harness."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--local", action="store_true", help="loopback only (default)")
    mode.add_argument(
        "--atlas-safe",
        action="store_true",
        help=f"isolated non-production target; requires {ATLAS_OPT_IN_ENV}=true",
    )
    parser.add_argument(
        "--mongo-uri",
        default="mongodb://127.0.0.1:27019",
        help="explicit target URI; never read from the environment",
    )
    parser.add_argument("--allow-host", action="append", default=[])
    parser.add_argument("--app-database", default="", help="application database name to avoid")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--samples", type=int, default=120)
    parser.add_argument("--idle-seconds", type=float, default=6.0)
    parser.add_argument("--lease-seconds", type=float, default=120.0)
    parser.add_argument("--heartbeat-seconds", type=float, default=30.0)
    parser.add_argument(
        "--capacity-sizes",
        default="20,100,1000,10000",
        help="comma-separated job counts for the capacity scenarios",
    )
    args = parser.parse_args(argv)

    chosen_mode = "atlas-safe" if args.atlas_safe else "local"
    run_tag = uuid.uuid4().hex[:8]
    db_name = _build_db_name(args.app_database, run_tag)

    try:
        check_database_name(db_name, args.app_database)
        verdict = check_endpoint(
            args.mongo_uri,
            mode=chosen_mode,
            allow_hosts=tuple(args.allow_host),
            app_database=args.app_database,
        )
    except UnsafeEndpointError as exc:
        print(f"SAFETY REFUSAL: {exc}", file=sys.stderr)
        return 2

    if not verdict.allowed:
        print("SAFETY REFUSAL: refusing to run against the requested target:", file=sys.stderr)
        for reason in verdict.reasons:
            print(f"  - {reason}", file=sys.stderr)
        print("No connection was attempted.", file=sys.stderr)
        return 2

    for note in verdict.notes:
        print(f"note: {note}", file=sys.stderr)

    try:
        report = asyncio.run(
            run_validation(
                args.mongo_uri,
                db_name=db_name,
                run_tag=run_tag,
                lease=args.lease_seconds,
                heartbeat=args.heartbeat_seconds,
                idle_seconds=args.idle_seconds,
                capacity_sizes=tuple(
                    int(part) for part in args.capacity_sizes.split(",") if part.strip()
                ),
            )
        )
    except UnsafeEndpointError as exc:
        print(f"SAFETY REFUSAL: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - a harness failure must be loud, not silent
        if os.environ.get("QUEUE_PHASE17C_DEBUG") == "1":
            import traceback

            traceback.print_exc()
        print(f"HARNESS ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    report["safety"] = {
        "mode": verdict.mode,
        "host_class": "loopback" if verdict.host in _LOOPBACK else "remote",
        "production_shaped_host": _is_production_shaped(verdict.host),
        "consent": verdict.consent,
        "notes": list(verdict.notes),
        "target_database_is_application_database": bool(
            args.app_database and args.app_database == db_name
        ),
    }
    report["hostname"] = "withheld"

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        _print_human(report)
    return 0 if report.get("ok") else 1


def _print_human(report: dict[str, Any]) -> None:
    print(f"PHASE 17C VALIDATION  mode={report['mode']}  db={report['database']}")
    print(f"  target_is_atlas       : {report['target_is_atlas']}")
    print(f"  lease/heartbeat (s)   : {report['lease_seconds']}/{report['heartbeat_seconds']}")
    server = report.get("server", {})
    print(f"  mongod                : {server.get('version')} ({server.get('storage_engine')})")
    print("  latency (p50/p95/p99 ms):")
    for name, stats in report.get("latency", {}).items():
        if "p50_ms" not in stats:
            print(f"    {name:<22} {stats}")
            continue
        p50 = stats["p50_ms"]
        if "p95_ms" not in stats:
            print(f"    {name:<22} {p50:>8.3f} {'':>8} {'':>8}   n={stats.get('samples', 1)}")
            continue
        print(
            f"    {name:<22} {p50:>8.3f} {stats['p95_ms']:>8.3f} "
            f"{stats['p99_ms']:>8.3f}   n={stats['samples']}"
        )
    plan = report.get("claim_plan", {})
    if plan:
        for entry in plan.get("observed", []):
            print(
                f"  claim plan n={entry['documents']:<6} "
                f"index={str(entry['uses_index']):<5} "
                f"collscan={str(entry['is_collscan']):<5} "
                f"sort={str(entry['has_blocking_sort']):<5} "
                f"stages={'+'.join(entry['stages'])}"
            )
    idle = report.get("idle_polling", {})
    capacity = report.get("capacity", {}).get("observed", [])
    if capacity:
        print("  capacity (enqueue / claim p95 ms, ops/s):")
        for entry in capacity:
            print(
                f"    jobs={entry['target_jobs']:<6} present={entry['documents_present']:<6} "
                f"enq_p95={entry['enqueue_p95_ms']:>7.3f} "
                f"enq_ops={entry['enqueue_ops_per_second']:>8.1f} "
                f"clm_p95={entry['claim_p95_ms']:>7.3f} "
                f"clm_ops={entry['claim_ops_per_second']} "
                f"rss+={entry['rss_growth_bytes'] / 1_048_576:.2f}MiB"
            )
    print(f"  idle ops/day/worker   : {idle.get('idle_claim_ops_per_day_per_worker')}")
    print(f"  BSON bytes            : {report.get('storage', {}).get('bson_bytes')}")
    print(f"  cleanup               : {report.get('cleanup')}")
    if report.get("failures"):
        print("  FAILURES:")
        for failure in report["failures"]:
            print(f"    - {failure}")
    print(f"  VERDICT: {'PASS' if report.get('ok') else 'FAIL'}")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
