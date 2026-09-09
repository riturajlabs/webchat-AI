#!/usr/bin/env python3
"""Micro-benchmark: provider-health Redis read latency, BEFORE vs AFTER.

RAG-PERF-04. Times only the adaptive provider-health read path against the
real Redis (no providers, no embedding, no generation):

  BEFORE (original): 3 providers x (get_health + is_available) = 6 sequential GETs
  AFTER  (optimized): 1 pipelined read of 3 GETs (get_health_many)

Run inside a container / env where REDIS_URL is set (never printed here).
Disables auto-reconnect pooling warmup effect by issuing a warmup first.

Usage:
    REDIS_URL=... .venv/bin/python scripts/perf/health_read_bench.py
"""

from __future__ import annotations

import asyncio
import os
import statistics
import time

from backend.services.ai.provider_health import (
    ProviderHealthStore,
    provider_health_name,
)
from redis.asyncio import Redis

# The three generation providers registered in production.
PROVIDERS = ["gemini", "groq", "openrouter"]
ROUNDS = 200


def _pct(vals: list[float], p: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    k = (len(s) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


async def main() -> int:
    url = os.environ.get("REDIS_URL")
    if not url:
        print("REDIS_URL is not set; aborting", file=__import__("sys").stderr)
        return 2
    redis = Redis.from_url(url, decode_responses=True)
    store = ProviderHealthStore(redis=redis)

    names = [provider_health_name("generation", p) for p in PROVIDERS]

    # Warmup the connection pool before measurement.
    await store.get_health_many(names)
    await asyncio.sleep(0.2)

    # ── AFTER: 1 pipelined read of 3 GETs ──────────────────────────────
    after_times: list[float] = []
    for _ in range(ROUNDS):
        t0 = time.perf_counter()
        await store.get_health_many(names)
        after_times.append((time.perf_counter() - t0) * 1000.0)

    # ── BEFORE: 6 sequential GETs (get_health x2 per provider) ─────────
    before_times: list[float] = []
    for _ in range(ROUNDS):
        t0 = time.perf_counter()
        for name in names:
            # Original adaptive router: get_health + is_available (2 GETs each).
            await store.get_health(name)
            h = await store.get_health(name)
            _ = store.is_available_from_health(h)
        before_times.append((time.perf_counter() - t0) * 1000.0)

    await redis.aclose()

    def _fmt(t: list[float]) -> str:
        return (
            f"n={len(t)} mean={statistics.mean(t):.3f}ms "
            f"p50={_pct(t, 50):.3f}ms p95={_pct(t, 95):.3f}ms "
            f"p99={_pct(t, 99):.3f}ms max={max(t):.3f}ms"
        )

    print(f"ROUNDS={ROUNDS} providers={len(names)}")
    print(f"AFTER  (1 pipeline, 3 GETs)     {_fmt(after_times)}")
    print(f"BEFORE (6 sequential GETs)      {_fmt(before_times)}")

    med_after = _pct(after_times, 50)
    med_before = _pct(before_times, 50)
    if med_before > 0:
        print(
            f"MEDIAN reduction: {(med_before - med_after):.3f}ms "
            f"({100 * (1 - med_after / med_before):.1f}%)"
        )
    p95_after = _pct(after_times, 95)
    p95_before = _pct(before_times, 95)
    print(f"P95 reduction:  {(p95_before - p95_after):.3f}ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
