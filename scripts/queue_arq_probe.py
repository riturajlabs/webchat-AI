#!/usr/bin/env python
"""Measure ARQ's real retry/timeout semantics against an isolated Redis.

Phase 17A needs the production retry contract as *measured* fact rather than an
assumption, because the Mongo worker loop has to reproduce it. This script
starts a real ``arq.worker.Worker`` with the production ``WorkerSettings`` shape
and counts how many times a job's coroutine executes for each outcome class.

Isolation, by construction:

* it talks only to the Redis URL given on the command line (default: the
  throwaway instance on port 27029) - never to ``REDIS_URL`` from the
  environment, so it cannot reach the configured production broker;
* every job uses an explicit ``_job_id`` prefixed ``queue17a-probe:`` and those
  keys are deleted afterwards;
* it runs no production job, sends no email, crawls nothing and calls no
  provider - the probe coroutines only sleep or raise;
* it runs in its own process and its own event loop, so the measurement can
  neither be perturbed by, nor leak into, the test suite.

Usage
-----
    python scripts/queue_arq_probe.py [--redis-url URL] [--json]

``--json`` prints one JSON object (``arq_version``, the worker shape, and the
execution count per outcome class) so the Phase 17A report can quote measured
output rather than prose.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
import sys
from typing import Any

PROBE_PREFIX = "queue17a-probe:"
DEFAULT_REDIS = os.environ.get("QUEUE_TEST_ARQ_REDIS_URL", "redis://127.0.0.1:27029")

#: Production worker shape (backend/workers/app.py WorkerSettings).
MAX_TRIES = 3
JOB_TIMEOUT = 600
KEEP_RESULT = 3600
POLL_DELAY = 0.1

#: The production timeout is 600 s, which is not worth measuring directly. The
#: question the timeout case answers - is a timed-out job retried? - does not
#: depend on the magnitude of the deadline, so it is measured with a 1 s
#: deadline and the substitution is reported in the output.
TIMEOUT_PROBE_SECONDS = 1
SLEEP_FOREVER_SECONDS = 30

KINDS = ("ordinary", "cancelled", "timeout")


class OrdinaryFailure(Exception):
    """A plain application exception (the overwhelmingly common case)."""


def _make_probe(kind: str, counter: dict[str, int]):
    """Build the probe coroutine for one outcome class."""
    if kind == "ordinary":

        async def probe(ctx: dict[str, Any]) -> None:
            counter["n"] += 1
            raise OrdinaryFailure("ordinary failure")

    elif kind == "cancelled":

        async def probe(ctx: dict[str, Any]) -> None:
            counter["n"] += 1
            raise asyncio.CancelledError()

    elif kind == "timeout":

        async def probe(ctx: dict[str, Any]) -> None:
            counter["n"] += 1
            await asyncio.sleep(SLEEP_FOREVER_SECONDS)

    else:  # pragma: no cover - guarded by KINDS
        raise ValueError(f"unknown probe kind {kind!r}")

    # ARQ registers a function under its `__qualname__` (arq.worker.func), so
    # both dunder names must be set - a nested function's qualname would
    # otherwise be `_make_probe.<locals>.probe` and never match the enqueued
    # function name.
    probe.__name__ = f"probe_{kind}"
    probe.__qualname__ = probe.__name__
    return probe


async def _measure(kind: str, redis_url: str) -> int:
    """Run one job of the given outcome class; return its execution count."""
    from arq.connections import ArqRedis, RedisSettings
    from arq.worker import Worker
    from redis.asyncio import ConnectionPool

    counter = {"n": 0}
    probe = _make_probe(kind, counter)

    # The producer pool mirrors production (`decode_responses=True`, used only
    # to enqueue). It is deliberately NOT handed to the worker: ARQ's consumer
    # decodes job ids as bytes, so a decode_responses pool makes `start_jobs`
    # fail. The worker therefore builds its own pool from `redis_settings`,
    # exactly as `arq` does in production.
    pool = ConnectionPool.from_url(redis_url, decode_responses=True)
    arq = ArqRedis(connection_pool=pool)
    settings = RedisSettings.from_dsn(redis_url)
    job_id = f"{PROBE_PREFIX}{kind}-{os.getpid()}"
    try:
        await arq.enqueue_job(probe.__name__, _job_id=job_id)

        # Burst mode drains the queue - including the zero-defer retries ARQ
        # re-queues - and returns on its own, so there is no cancel/teardown
        # race to make the count nondeterministic. `async_run` (not `run`) is
        # the coroutine entry point; `run` is synchronous and calls
        # `run_until_complete`, which cannot be nested in a running loop.
        worker = Worker(
            functions=[probe],
            redis_settings=settings,
            max_tries=MAX_TRIES,
            job_timeout=TIMEOUT_PROBE_SECONDS if kind == "timeout" else JOB_TIMEOUT,
            keep_result=KEEP_RESULT,
            poll_delay=POLL_DELAY,
            burst=True,
            handle_signals=False,
        )
        await asyncio.wait_for(worker.async_run(), timeout=90)
        return counter["n"]
    finally:
        await _cleanup(arq, job_id)
        await arq.aclose()
        with contextlib.suppress(Exception):
            await pool.disconnect()


async def _cleanup(arq: Any, job_id: str) -> None:
    """Delete only the keys this probe created; touch nothing else."""
    with contextlib.suppress(Exception):
        await arq.delete(
            f"arq:queue:{job_id}",
            f"arq:in-progress:{job_id}",
            f"arq:result:{job_id}",
            job_id,
        )


async def _sweep_residue(redis_url: str) -> int:
    """Delete any leftover probe key from an earlier or aborted run.

    Scoped strictly to the probe prefix; the isolated instance is only ever
    used by this script, but the sweep keeps repeated runs self-cleaning.
    """
    from redis.asyncio import Redis

    client = Redis.from_url(redis_url, decode_responses=True)
    removed = 0
    try:
        keys = [key async for key in client.scan_iter(match=f"{PROBE_PREFIX}*")]
        keys += [key async for key in client.scan_iter(match=f"arq:*{PROBE_PREFIX.strip(':')}*")]
        if keys:
            await client.delete(*set(keys))
            removed = len(set(keys))
    finally:
        await client.aclose()
    return removed


async def run(redis_url: str) -> dict[str, Any]:
    import arq

    swept = await _sweep_residue(redis_url)
    results = {kind: await _measure(kind, redis_url) for kind in KINDS}
    return {
        "arq_version": arq.__version__,
        "redis_url": redis_url,
        "max_tries": MAX_TRIES,
        "job_timeout": JOB_TIMEOUT,
        "keep_result": KEEP_RESULT,
        "timeout_probe_seconds": TIMEOUT_PROBE_SECONDS,
        "residue_keys_swept": swept,
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    # ARQ logs every dead-lettered probe job at ERROR with a traceback. That is
    # correct behaviour and exactly what the probe is measuring, but it buries
    # the result, so the arq logger is silenced and the counts speak instead.
    logging.getLogger("arq").setLevel(logging.CRITICAL)
    logging.getLogger("asyncio").setLevel(logging.CRITICAL)

    parser = argparse.ArgumentParser(description="Measure ARQ retry semantics.")
    parser.add_argument("--redis-url", default=DEFAULT_REDIS)
    parser.add_argument("--json", action="store_true", help="print JSON only")
    args = parser.parse_args(argv)

    payload = asyncio.run(run(args.redis_url))
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print(f"arq {payload['arq_version']} against {payload['redis_url']}")
    print(
        f"  worker shape: max_tries={MAX_TRIES} job_timeout={JOB_TIMEOUT}s "
        f"keep_result={KEEP_RESULT}s"
    )
    print("  executions per outcome class:")
    for kind, count in payload["results"].items():
        print(f"    {kind:<10} {count}")
    print(
        f"  (the timeout case used a {TIMEOUT_PROBE_SECONDS}s deadline instead of "
        f"{JOB_TIMEOUT}s; the retry verdict does not depend on the magnitude)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
