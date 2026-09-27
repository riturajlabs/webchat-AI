#!/usr/bin/env python
"""Measure the Mongo queue's cost and latency against the ARQ baseline.

Phase 17A claims two things that must be measured, not asserted:

1. **Idle cost.** ARQ 0.28 polls Redis every 0.5 s regardless of load
   (~172,800 commands/day/worker). The Mongo queue's adaptive poller ratchets
   to a configurable cap, so an idle worker's claim rate should be far lower.
2. **Per-operation latency.** A Mongo claim is a single ``find_one_and_update``
   with an update pipeline, versus ARQ's Lua script over a ZSET plus string
   keys. Mongo pays a network round-trip to a (potentially remote) server, so
   the numbers decide whether the adaptive poll schedule is the right default.

Isolation: every figure comes from a throwaway database on the isolated mongod
passed on the command line (default port 27019). No production job, provider,
crawl or email is involved - the queue documents are written and read, and the
handler is a no-op coroutine.

Usage
-----
    python scripts/queue_perf_probe.py [--mongo-uri URI] [--json]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from typing import Any

DEFAULT_MONGO_URI = os.environ.get("PROTOTYPE_MONGO_URI", "mongodb://127.0.0.1:27019")

#: Production worker shape, kept identical to backend/workers/app.py.
ARQ_POLL_DELAY_SECONDS = 0.5
MAX_TRIES = 3


def _percentile(samples: list[float], fraction: float) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return ordered[index]


async def _measure_claim_latency(adapter: Any, count: int) -> dict[str, float]:
    """Latency of a single claim operation, one job at a time."""
    samples: list[float] = []
    for _ in range(count):
        await adapter.enqueue(
            "process_document",
            payload={"document_id": "perf-doc", "run_id": None},
            tenant_id="perf-tenant",
        )
        start = time.perf_counter()
        job = await adapter.claim("perf-worker")
        samples.append((time.perf_counter() - start) * 1000)
        assert job is not None
        await adapter.complete(job.id, "perf-worker", execution_version=job.execution_version)
    return {
        "samples": len(samples),
        "p50_ms": round(_percentile(samples, 0.50), 3),
        "p95_ms": round(_percentile(samples, 0.95), 3),
        "p99_ms": round(_percentile(samples, 0.99), 3),
        "max_ms": round(max(samples), 3),
    }


async def _measure_claim_concurrency(adapter: Any, total: int, workers: int) -> dict[str, Any]:
    """Throughput and duplicate-claim rate with N concurrent workers.

    The duplicate count is the safety number: under an atomic claim it must be
    zero, otherwise two workers would run the same job.
    """
    for index in range(total):
        await adapter.enqueue(
            "process_document",
            payload={"document_id": f"conc-{index}", "run_id": None},
            tenant_id="perf-tenant",
        )

    claimed: list[str] = []
    duplicates = {"n": 0}
    lock = asyncio.Lock()

    async def worker(name: str) -> None:
        while True:
            job = await adapter.claim(name)
            if job is None:
                return
            async with lock:
                if job.id in claimed:
                    duplicates["n"] += 1
                claimed.append(job.id)
            await adapter.complete(job.id, name, execution_version=job.execution_version)

    start = time.perf_counter()
    await asyncio.gather(*(worker(f"perf-w{i}") for i in range(workers)))
    elapsed = time.perf_counter() - start

    return {
        "jobs": total,
        "workers": workers,
        "elapsed_s": round(elapsed, 3),
        "throughput_jobs_per_s": round(total / elapsed, 1) if elapsed else 0.0,
        "unique_claims": len(set(claimed)),
        "duplicate_claims": duplicates["n"],
    }


async def _measure_idle_cost() -> dict[str, float]:
    """Steady-state idle claim rate: ARQ's fixed poll vs the adaptive poller.

    The adaptive policy is pure, so hours of idle time are computed rather than
    slept through.
    """
    from backend.queue.mongo.poller import ARQ_DEFAULT_POLL_DELAY_SECONDS, AdaptivePoller

    schedule = (1.0, 2.0, 5.0, 10.0, 30.0)
    poller = AdaptivePoller(schedule)
    # Settle into the steady state.
    for _ in range(10):
        poller.nick(False)
    idle_sleep_seconds = 0.0
    iterations = 24 * 60  # one simulated day at the 30 s cap
    for _ in range(iterations):
        idle_sleep_seconds += poller.nick(False)

    arq_per_day = 86_400 / ARQ_DEFAULT_POLL_DELAY_SECONDS
    mongo_per_day = 86_400 / max(schedule)
    return {
        "arq_poll_delay_s": ARQ_DEFAULT_POLL_DELAY_SECONDS,
        "arq_claim_ops_per_day_per_worker": round(arq_per_day),
        "mongo_poll_schedule": list(schedule),
        "mongo_claim_ops_per_day_per_worker": round(mongo_per_day),
        "reduction_factor": round(arq_per_day / mongo_per_day, 1),
        "simulated_idle_waits": iterations,
        "simulated_idle_sleep_s": round(idle_sleep_seconds, 1),
    }


async def _measure_document_size(adapter: Any) -> dict[str, int]:
    """Stored size of a queue document, to keep the storage estimate honest."""
    from bson import BSON

    job_id = await adapter.enqueue(
        "process_document",
        payload={"document_id": "size-doc", "run_id": None},
        tenant_id="perf-tenant",
    )
    raw = await adapter.queue.collection.find_one({"_id": job_id})
    assert raw is not None
    job = await adapter.claim("perf-worker")
    assert job is not None
    running = await adapter.queue.collection.find_one({"_id": job_id})
    assert running is not None
    return {
        "pending_bytes": len(BSON.encode(raw)),
        "running_bytes": len(BSON.encode(running)),
    }


async def run(mongo_uri: str, claims: int, total: int, workers: int) -> dict[str, Any]:
    from backend.queue.mongo_adapter import MongoQueueAdapter
    from motor.motor_asyncio import AsyncIOMotorClient

    client: AsyncIOMotorClient[Any] = AsyncIOMotorClient(mongo_uri, tz_aware=True)
    try:
        await client.admin.command("ping")
        database = client["queue_perf_probe"]
        adapter = MongoQueueAdapter(database, collection_name="worker_jobs", max_tries=MAX_TRIES)
        await adapter.ensure_indexes()
        await adapter.delete_all()
        try:
            return {
                "mongo_uri": mongo_uri,
                "claim_latency": await _measure_claim_latency(adapter, claims),
                "claim_concurrency": await _measure_claim_concurrency(adapter, total, workers),
                "idle_cost": await _measure_idle_cost(),
                "document_size": await _measure_document_size(adapter),
            }
        finally:
            await adapter.delete_all()
            await client.drop_database("queue_perf_probe")
    finally:
        client.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure Mongo queue cost/latency.")
    parser.add_argument("--mongo-uri", default=DEFAULT_MONGO_URI)
    parser.add_argument("--claims", type=int, default=200)
    parser.add_argument("--jobs", type=int, default=200)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--json", action="store_true", help="print JSON only")
    args = parser.parse_args(argv)

    payload = asyncio.run(run(args.mongo_uri, args.claims, args.jobs, args.workers))
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    latency = payload["claim_latency"]
    concurrency = payload["claim_concurrency"]
    idle = payload["idle_cost"]
    size = payload["document_size"]
    print(f"Mongo queue performance probe against {payload['mongo_uri']}")
    print(
        f"  claim latency over {latency['samples']} samples: "
        f"p50={latency['p50_ms']}ms p95={latency['p95_ms']}ms p99={latency['p99_ms']}ms"
    )
    print(
        f"  {concurrency['jobs']} jobs / {concurrency['workers']} workers: "
        f"{concurrency['throughput_jobs_per_s']} jobs/s, "
        f"duplicate claims={concurrency['duplicate_claims']}"
    )
    print(
        f"  idle cost/worker/day: ARQ {idle['arq_claim_ops_per_day_per_worker']} ops "
        f"vs Mongo {idle['mongo_claim_ops_per_day_per_worker']} ops "
        f"({idle['reduction_factor']}x lower)"
    )
    print(f"  stored document: pending={size['pending_bytes']}B running={size['running_bytes']}B")
    return 0


if __name__ == "__main__":
    sys.exit(main())
