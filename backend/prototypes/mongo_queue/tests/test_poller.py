"""Polling cost experiments (§15, §24, §25, §26).

The heart of the investigation: how many MongoDB operations does the adaptive
poller cost while idle, vs the fixed 0.5 s ARQ behaviour. Pure/analytic parts
are deterministic (no sleeps); the live sections use short real bursts on the
isolated mongod and are clearly labelled as local-dev resamples, not Atlas.
"""

from __future__ import annotations

from typing import Any

from backend.prototypes.mongo_queue import MongoQueue
from backend.prototypes.mongo_queue.config import QueueConfig
from backend.prototypes.mongo_queue.measure import (
    current_process_memory_mb,
    run_latency_measurements,
)
from backend.prototypes.mongo_queue.poller import (
    ARQ_DEFAULT_POLL_DELAY_SECONDS,
    AdaptivePoller,
    estimate_idle_ops_per_day,
)
from backend.prototypes.mongo_queue.sim_jobs import MockMailProvider, send_email_handler
from backend.prototypes.mongo_queue.worker import PrototypeWorker

SCHEDULE = (1.0, 2.0, 5.0, 10.0, 30.0)
SECONDS_PER_DAY = 86_400.0
ARQ_IDLE_OPS_PER_DAY = SECONDS_PER_DAY / ARQ_DEFAULT_POLL_DELAY_SECONDS


async def test_adaptive_schedule_is_deterministic() -> None:
    poller = AdaptivePoller(SCHEDULE)
    assert poller.nick(found_work=False) == 2.0
    assert poller.nick(found_work=False) == 5.0
    assert poller.nick(found_work=False) == 10.0
    assert poller.nick(found_work=False) == 30.0
    assert poller.nick(found_work=False) == 30.0  # capped
    assert poller.nick(found_work=True) == 1.0  # reset on work
    assert poller.stats.iterations == 6


async def test_estimate_idle_ops_per_day_matches_schedule_math() -> None:
    cap = max(SCHEDULE)
    assert estimate_idle_ops_per_day(SCHEDULE, 1) == SECONDS_PER_DAY / cap
    assert estimate_idle_ops_per_day(SCHEDULE, 2) == 2 * (SECONDS_PER_DAY / cap)
    assert estimate_idle_ops_per_day(SCHEDULE, 5) == 5 * (SECONDS_PER_DAY / cap)
    # The fixed fast-poller variant (the ARQ case).
    assert estimate_idle_ops_per_day((ARQ_DEFAULT_POLL_DELAY_SECONDS,), 1) == ARQ_IDLE_OPS_PER_DAY


async def test_polling_cost_table_ops_per_day() -> None:
    """§15 §25: ops/day and ops/30day for 1/2/5 workers at each interval."""
    fastest = estimate_idle_ops_per_day((1.0,), 1)
    slowest = estimate_idle_ops_per_day((30.0,), 1)
    assert (1.0, 1, fastest, fastest * 30) == (1.0, 1, 86_400.0, 2_592_000.0)
    assert (30.0, 1, slowest, slowest * 30) == (30.0, 1, 2_880.0, 86_400.0)
    assert estimate_idle_ops_per_day((30.0,), 5) == 5 * slowest
    # Adaptive (0.5 -> 1 -> 2 -> 5 -> 10 -> 30) beats fixed 0.5 s by ~60x.
    arq_one = ARQ_IDLE_OPS_PER_DAY
    assert slowest < arq_one
    assert arq_one / slowest > 50


async def test_idle_five_minutes_simulated_without_sleeping() -> None:
    """§15: run the poller policy over a VIRTUAL 5-minute idle window (no
    real waiting); the claim-per-wake contract yields a bounded op count."""
    virtual_sleep = 0.0
    poller = AdaptivePoller(SCHEDULE)
    claim_ops = 0
    while virtual_sleep < 5 * 60:
        claim_ops += 1
        virtual_sleep += poller.nick(found_work=False)
    # Steady state dwells on the 30 s slot: far below the naive
    # 5*60/1 = 300 ops a fixed 1 s poller would spend in 5 idle minutes.
    assert claim_ops < 60
    assert claim_ops >= 10


async def test_real_idle_poller_run_counts_live_ops(queue: MongoQueue) -> None:
    """A SHORT real idle run (isolated mongod): one claim op per wake, i.e.
    ~a handful in a few seconds - never the 172,800/day-per-worker stream."""
    worker = PrototypeWorker(queue, QueueConfig(), worker_id="live-idle")
    queue.reset_ops()
    await worker.run(stop_after_seconds=3.0)
    ops = queue.ops
    assert 0 < ops <= 8  # 3 s at the initial 1-2 s cadence


async def test_live_latency_p50_p95_p99_local_mongod() -> None:
    """§24: enqueue/claim/complete/renew/fail latency on the ISOLATED local
    mongod (labelled local-dev; NOT Atlas M0). 300 samples per operation."""
    result = await run_latency_measurements(rounds=300)
    assert set(result) == {
        "enqueue",
        "claim_empty",
        "claim+complete",
        "claim+renew",
        "claim+fail(retry)",
    }
    for label, row in result.items():
        assert row["samples"] == 300
        assert 0 < row["p50_ms"] <= row["p95_ms"] <= row["p99_ms"], label


async def test_worker_memory_profile_idle_and_active(queue: MongoQueue) -> None:
    """§26: RSS of the prototype worker while idle (adaptive poller) and
    immediately after executing a mock email job. LOCAL-DEV measurement; the
    production worker (Chromium + embeddings) is explicitly NOT measured."""
    worker = PrototypeWorker(
        queue,
        QueueConfig(),
        worker_id="mem-worker",
        handlers={
            "send_email": lambda p, ctx: send_email_handler(p, ctx, provider=MockMailProvider())
        },
    )
    await worker.run(stop_after_seconds=2.0)  # idle phase (adaptive backoff)
    idle = current_process_memory_mb()
    assert idle.get("rss_mb", 0) > 0

    await queue.enqueue(
        function="send_email",
        payload={"to": "x@example.com", "subject": "s", "body": "b"},
        tenant_id="t",
    )
    await worker.work_once()
    active = current_process_memory_mb()
    assert active.get("rss_mb", 10_000) < 256, active
    del idle


def test_reportable_polling_numbers_for_report() -> None:
    """One consolidated, reproducible table used verbatim in the report."""
    rows: dict[str, dict[str, Any]] = {}
    for workers in (1, 2, 5):
        adaptive = estimate_idle_ops_per_day(SCHEDULE, workers)
        arq = ARQ_IDLE_OPS_PER_DAY * workers
        rows[f"workers_{workers}"] = {
            "adaptive_ops_day": adaptive,
            "adaptive_ops_30d": adaptive * 30,
            "arq_0_5s_ops_day": arq,
            "reduction_ratio": round(arq / adaptive, 1),
        }
    assert rows["workers_1"]["adaptive_ops_day"] == 2880.0
    assert rows["workers_1"]["adaptive_ops_30d"] == 86_400.0
    assert rows["workers_1"]["reduction_ratio"] == 60.0
    assert rows["workers_5"]["adaptive_ops_day"] == 14_400.0
    assert rows["workers_2"]["arq_0_5s_ops_day"] == 2 * ARQ_IDLE_OPS_PER_DAY