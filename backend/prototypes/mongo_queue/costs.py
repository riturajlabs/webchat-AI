"""Pure models for Mongo operation counts, heartbeat cost, lease sizing and
retention/storage estimates (Phase 16 §7/§8/§9/§14).

Everything here is ``CALCULATED`` (deterministic arithmetic over the prototype's
queue operations) so the tests can assert the exact numbers the report cites.
Actual Atlas figures remain ``NOT MEASURED`` (no safe test Atlas connection).
"""

from __future__ import annotations

import json
import math
from typing import Any

from backend.prototypes.mongo_queue.poller import ARQ_DEFAULT_POLL_DELAY_SECONDS

# ---------------------------------------------------------------------------
# A-F operation counts (READ and WRITE, documented per driver command)
# ---------------------------------------------------------------------------


def enqueue_ops(dedup_collision: bool = False) -> dict[str, int]:
    """A. enqueue: 1 insert_one (WRITE); dedup collision adds a read-back."""
    return {"READ": int(dedup_collision), "WRITE": 1, "commands": 1 + int(dedup_collision)}


def claim_ops() -> dict[str, int]:
    """B. claim: one find_one_and_update = one findAndModify command = one
    index seek (READ) + one atomic write (WRITE)."""
    return {"READ": 1, "WRITE": 1, "commands": 1}


def complete_ops() -> dict[str, int]:
    """C. complete: one update_one keyed on _id (WRITE)."""
    return {"READ": 0, "WRITE": 1, "commands": 1}


def fail_ops() -> dict[str, int]:
    """D. fail/retry: one find_one (_id, READ) then one update_one (WRITE)."""
    return {"READ": 1, "WRITE": 1, "commands": 2}


def renew_ops() -> dict[str, int]:
    """E. lease renewal: one update_one keyed on _id (WRITE)."""
    return {"READ": 0, "WRITE": 1, "commands": 1}


def retire_ops(rows: int) -> dict[str, int]:
    """F. expired-lease recovery: one update_many sweep (WRITE)."""
    return {"READ": 0, "WRITE": 1 if rows else 0, "commands": int(rows > 0)}


def dedup_collision_ops() -> dict[str, int]:
    """G. dedup collision: failed insert (WRITE attempt) + read-back (READ)."""
    return {"READ": 1, "WRITE": 1, "commands": 2}


def poll_ops_idle(run: float = ARQ_DEFAULT_POLL_DELAY_SECONDS) -> dict[str, int]:
    """H. idle polling per poll: one findAndModify that matches nothing (READ
    index scan; no write since nothing matched)."""
    return {"READ": 1, "WRITE": 0, "commands": 1}


INDEX_MAINTENANCE_CLAIM = (
    "I. index maintenance is server-side (WiredTiger B-tree applies per write); "
    "no app commands."
)


# ---------------------------------------------------------------------------
# Polling cost
# ---------------------------------------------------------------------------


def idle_claims_per_day(schedule: tuple[float, ...], workers: int) -> float:
    """Steady-state idle claim attempts/day for ``workers`` adaptive pollers."""
    if not schedule:
        raise ValueError("empty schedule")
    cap = max(schedule)
    return 86400.0 / cap * workers


def arq_idle_polls_per_day(workers: int) -> float:
    """ARQ fixed 0.5 s idle polls/day/worker (one ZRANGEBYSCORE each)."""
    return 86400.0 / ARQ_DEFAULT_POLL_DELAY_SECONDS * workers


# ---------------------------------------------------------------------------
# Active job heartbeat cost (lease=600s scenario family, §11/§29)
# ---------------------------------------------------------------------------


def heartbeat_renewals(duration_seconds: float, heartbeat_seconds: float) -> int:
    """Number of renew_lease calls during a job of ``duration_seconds``."""
    if duration_seconds <= 0:
        return 0
    return max(1, int(math.ceil(duration_seconds / heartbeat_seconds)))


def active_job_ops(
    duration_seconds: float,
    *,
    lease_seconds: float,
    heartbeat_seconds: float,
) -> dict[str, int]:
    """Queue-level ops for one active job: enqueue + claim + renewals + complete."""
    return {
        "enqueue": 1,
        "claim": 1,
        "renew_lease": heartbeat_renewals(duration_seconds, heartbeat_seconds),
        "complete": 1,
        "domains": 3,
        "commands": 3 + heartbeat_renewals(duration_seconds, heartbeat_seconds),
    }


# ---------------------------------------------------------------------------
# Lease sizing trade-offs (no verdict provider; §14)
# ---------------------------------------------------------------------------


def lease_sizing_profiles() -> list[dict[str, Any]]:
    """Candidate (lease_seconds, heartbeat_seconds) trade-off table."""
    candidates = [(600, 30), (600, 60), (900, 60)]
    profiles = []
    for lease, heartbeat in candidates:
        profiles.append(
            {
                "lease_seconds": lease,
                "heartbeat_seconds": heartbeat,
                # Heartbeat renewals if the job runs the full lease window:
                "renewals_full_lease": heartbeat_renewals(lease, heartbeat),
                # Renewals for a 3600 s crawl (production crawl timeout):
                "renewals_3600s_crawl": heartbeat_renewals(3600, heartbeat),
                # Failure detection time == lease length (crash => reclaimable):
                "failure_detection_seconds": lease,
                # Maximum time a zombie worker can keep running a side effect
                # before the job becomes re-claimable:
                "stale_worker_window_seconds": lease,
                # Long-job safety: heartbeat must be comfortably < lease so a
                # healthy-but-slow renewal never trips the fence.
                "renewal_divisor_lease": round(lease / heartbeat, 1),
            }
        )
    return profiles


# ---------------------------------------------------------------------------
# Retention + storage estimates (§17/§18, labelled ESTIMATES)
# ---------------------------------------------------------------------------


def document_bytes(payload: dict[str, Any]) -> int:
    """BSON-encoded byte size of a queue row (measured against the prototype
    mongod in tests by inserting the same doc)."""
    from bson import encode  # pymongo dependency, already used by the queue

    try:
        return len(encode(payload))
    except Exception:
        return len(json.dumps(payload, default=str).encode("utf-8"))


def retention_storage_days(
    jobs_per_day: float, doc_bytes: int, days: int, index_overhead_factor: float = 1.0
) -> float:
    """Total bytes retained after ``days`` (ESTIMATE; index overhead is a
    labelled multiplicative factor, not a measured Atlas number)."""
    return jobs_per_day * days * doc_bytes * index_overhead_factor


__all__ = [
    "INDEX_MAINTENANCE_CLAIM",
    "active_job_ops",
    "arq_idle_polls_per_day",
    "claim_ops",
    "complete_ops",
    "dedup_collision_ops",
    "document_bytes",
    "enqueue_ops",
    "fail_ops",
    "heartbeat_renewals",
    "idle_claims_per_day",
    "lease_sizing_profiles",
    "poll_ops_idle",
    "renew_ops",
    "retention_storage_days",
    "retire_ops",
]