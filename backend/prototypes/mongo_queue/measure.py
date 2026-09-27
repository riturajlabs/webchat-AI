"""Latency + resource measurement harness (Phase 15 §24–§26).

Runs against the isolated prototype mongod, never Atlas. Produces the
p50/p95/p99 tables consumed by the report. Local-dev measurements are
labelled as such everywhere; not claimed to be Atlas M0 numbers.
"""

from __future__ import annotations

import json
import os
import statistics
import time
from collections.abc import Awaitable, Callable
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient

from backend.prototypes.mongo_queue.config import (
    DEFAULT_MONGO_URI,
    QueueConfig,
)
from backend.prototypes.mongo_queue.queue import MongoQueue


def percentile(sorted_samples: list[float], pct: float) -> float:
    if not sorted_samples:
        return 0.0
    quantiles = statistics.quantiles(sorted_samples, n=100, method="exclusive")
    return float(quantiles[max(0, int(pct) - 1)])


async def run_latency_measurements(
    rounds: int = 300,
    uri: str = DEFAULT_MONGO_URI,
    config: QueueConfig | None = None,
) -> dict[str, Any]:
    """Issue ``rounds`` of each operation and report p50/p95/p99 in ms."""
    config = config or QueueConfig()
    client = AsyncIOMotorClient[Any](uri, serverSelectionTimeoutMS=5000, tz_aware=True)
    try:
        queue = MongoQueue(client[config.db_name], config)
        await queue.delete_all()
        await queue.ensure_indexes()

        async def measure(op: Callable[[], Awaitable[Any]]) -> list[float]:
            samples: list[float] = []
            for _round in range(rounds):
                start = time.perf_counter()
                await op()
                samples.append((time.perf_counter() - start) * 1000.0)
            return samples

        async def enqueue_op() -> None:
            await queue.enqueue(function="measure", payload={"round": 0})

        async def claim_op() -> None:
            await queue.claim("measure-worker")

        async def complete_op() -> None:
            job = await queue.claim("measure-worker")
            if job is not None:
                await queue.complete_job(
                    job.id, "measure-worker", execution_version=job.execution_version
                )

        async def renew_op() -> None:
            job = await queue.claim("measure-worker-2")
            if job is not None:
                await queue.renew_lease(job.id, "measure-worker-2")

        async def fail_op() -> None:
            job = await queue.claim("measure-worker-3")
            if job is not None:
                await queue.fail_job(
                    job.id, "measure-worker-3", "boom", execution_version=job.execution_version
                )

        tables: dict[str, dict[str, float]] = {}
        for label, op in (
            ("enqueue", enqueue_op),
            ("claim_empty", claim_op),
            ("claim+complete", complete_op),
            ("claim+renew", renew_op),
            ("claim+fail(retry)", fail_op),
        ):
            samples = sorted(await measure(op))
            tables[label] = {
                "p50_ms": round(percentile(samples, 50), 3),
                "p95_ms": round(percentile(samples, 95), 3),
                "p99_ms": round(percentile(samples, 99), 3),
                "samples": rounds,
            }
        return tables
    finally:
        client.close()


def current_process_memory_mb() -> dict[str, float]:
    """RSS + peak HWM of the current process from /proc (Linux)."""
    out: dict[str, float] = {}
    try:
        with open(f"/proc/{os.getpid()}/status") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    out["rss_mb"] = int(line.split()[1]) * 1024 / 1048576
                elif line.startswith("VmHWM:"):
                    out["peak_hwm_mb"] = int(line.split()[1]) * 1024 / 1048576
    except OSError:
        pass
    return out


if __name__ == "__main__":
    import asyncio

    results = asyncio.run(run_latency_measurements(rounds=500))
    print(json.dumps(results, indent=2))
