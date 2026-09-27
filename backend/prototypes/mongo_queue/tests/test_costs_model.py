"""Phase 16 pure cost/op-count models: operation model A-I, adaptive vs ARQ
idle polling, active-job heartbeat cost, lease sizing trade-offs, and retention
/ storage estimates. All assertions are CALCULATED arithmetic (no mongod
required) so the report's numbers are exactly reproducible."""

from __future__ import annotations

from backend.prototypes.mongo_queue.config import QueueConfig
from backend.prototypes.mongo_queue.costs import (
    INDEX_MAINTENANCE_CLAIM,
    active_job_ops,
    arq_idle_polls_per_day,
    claim_ops,
    complete_ops,
    dedup_collision_ops,
    document_bytes,
    enqueue_ops,
    fail_ops,
    heartbeat_renewals,
    idle_claims_per_day,
    lease_sizing_profiles,
    renew_ops,
    retention_storage_days,
)
from backend.prototypes.mongo_queue.poller import ARQ_DEFAULT_POLL_DELAY_SECONDS


def test_poll_delay_baseline_is_05s() -> None:
    assert ARQ_DEFAULT_POLL_DELAY_SECONDS == 0.5


def test_idle_costs_adaptive_vs_arq() -> None:
    workers = 2
    adaptive = idle_claims_per_day(QueueConfig().poll_schedule, workers)
    arq = arq_idle_polls_per_day(workers)
    assert adaptive == 86400.0 / 30.0 * workers  # 5,760 strategy idle claims/day
    assert arq == 86400.0 / 0.5 * workers  # 345,600 ZRANGEBYSCORE/day baseline
    assert adaptive < arq


def test_operation_model_counts() -> None:
    assert claim_ops() == {"READ": 1, "WRITE": 1, "commands": 1}
    assert enqueue_ops() == {"READ": 0, "WRITE": 1, "commands": 1}
    assert enqueue_ops(dedup_collision=True) == {"READ": 1, "WRITE": 1, "commands": 2}
    assert complete_ops() == {"READ": 0, "WRITE": 1, "commands": 1}
    assert fail_ops() == {"READ": 1, "WRITE": 1, "commands": 2}
    assert renew_ops() == {"READ": 0, "WRITE": 1, "commands": 1}
    assert dedup_collision_ops() == {"READ": 1, "WRITE": 1, "commands": 2}
    assert INDEX_MAINTENANCE_CLAIM.startswith("I.")


def test_retire_ops() -> None:
    from backend.prototypes.mongo_queue.costs import retire_ops

    assert retire_ops(rows=5) == {"READ": 0, "WRITE": 1, "commands": 1}
    assert retire_ops(rows=0) == {"READ": 0, "WRITE": 0, "commands": 0}


def test_long_job_within_lease_needs_heartbeat() -> None:
    # A 600 s job with 30 s heartbeat renews 20 times (full lease window).
    assert heartbeat_renewals(600, 30) == 20
    assert heartbeat_renewals(600, 60) == 10
    assert heartbeat_renewals(1, 30) == 1  # short job: one renewal is still issued


def test_active_job_op_budget() -> None:
    ops = active_job_ops(600, lease_seconds=600, heartbeat_seconds=30)
    assert ops == {
        "enqueue": 1,
        "claim": 1,
        "renew_lease": 20,
        "complete": 1,
        "domains": 3,
        "commands": 23,  # 3 fixed + 20 heartbeats
    }


def test_lease_sizing_profiles_are_tradeoffs_without_verdict() -> None:
    profiles = lease_sizing_profiles()
    assert [p["lease_seconds"] for p in profiles] == [600, 600, 900]
    assert [p["heartbeat_seconds"] for p in profiles] == [30, 60, 60]
    for profile in profiles:
        assert profile["failure_detection_seconds"] == profile["lease_seconds"]
        assert profile["stale_worker_window_seconds"] == profile["lease_seconds"]
    # 900/60 detects failures 50% slower than 600/60 and renews less often.
    assert profiles[2]["failure_detection_seconds"] == 900
    assert profiles[2]["renewals_3600s_crawl"] == heartbeat_renewals(3600, 60)
    assert profiles[0]["renewals_3600s_crawl"] == heartbeat_renewals(3600, 30)
    assert profiles[0]["renewals_3600s_crawl"] == 120


def test_retention_storage_estimate_arithmetic() -> None:
    # 1,000 jobs/day * ~500 B rows * 30 days, ~1.5x index/overhead factor.
    est = retention_storage_days(1000, 500, 30, index_overhead_factor=1.5)
    assert est == float(1000 * 500 * 30 * 1.5)


def test_document_byte_measurement_is_sane() -> None:
    payload = {
        "_id": "job-1",
        "function": "send_email",
        "payload": {"to": "a@b.c"},
        "tenant_id": "tenant-a",
        "status": "pending",
        "created_at": "2026-09-21T00:00:00Z",
        "max_tries": 3,
        "attempts": 0,
        "execution_version": 0,
    }
    size = document_bytes(payload)
    assert 200 < size < 2000  # small payload; well under M0 doc-size limits
