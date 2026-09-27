"""Phase 16 index-plan validation against the isolated prototype mongod.

Confirms the claim query is served by one of the two status compound indexes
(never a collection scan) and that the dedup partial unique index actually
enforces submission-level de-duplication (index-level guarantee)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from backend.prototypes.mongo_queue.models import (
    CLAIMABLE_PENDING,
    STATUS_PENDING,
    STATUS_RUNNING,
)
from backend.prototypes.mongo_queue.queue import MongoQueue
from motor.motor_asyncio import AsyncIOMotorCollection


def _claim_filter(
    now: Any,
) -> dict[str, Any]:
    return {
        "$expr": {"$lt": ["$attempts", "$max_tries"]},
        "$or": [
            {"status": {"$in": sorted(CLAIMABLE_PENDING)}, "run_at": {"$lte": now}},
            {"status": STATUS_RUNNING, "lease_expires_at": {"$lte": now}},
        ],
    }


def _flatten_plan(node: dict[str, Any], acc: list[dict[str, Any]]) -> None:
    """Collect every stage in a query plan tree (incl. OR sub-plans)."""
    if not isinstance(node, dict):
        return
    acc.append(node)
    if isinstance(node.get("inputStage"), dict):
        _flatten_plan(node["inputStage"], acc)
    for shard in node.get("shards", []) if isinstance(node.get("shards"), list) else []:
        _flatten_plan(shard, acc)
    for sub in node.get("subPlans", []) if isinstance(node.get("subPlans"), list) else []:
        _flatten_plan(sub, acc)
    for sub in node.get("inputStages", []) if isinstance(node.get("inputStages"), list) else []:
        _flatten_plan(sub, acc)


@pytest.mark.parametrize("branch", ["pending", "expired_running"])
async def test_claim_query_uses_a_status_compound_index(queue: MongoQueue, branch: str) -> None:
    now = datetime.now(UTC)
    col: AsyncIOMotorCollection[dict[str, Any]] = queue.collection
    if branch == "pending":
        await queue.enqueue(function="job", payload={}, tenant_id="t")
    else:
        job_id = await queue.enqueue(function="job", payload={}, tenant_id="t")
        # Force a stale RUNNING row whose lease expired.
        await col.update_one(
            {"_id": job_id},
            {
                "$set": {
                    "status": STATUS_RUNNING,
                    "run_at": now,
                    "lease_expires_at": now,
                }
            },
        )
    plan = await col.find(_claim_filter(now)).sort([("run_at", 1), ("_id", 1)]).explain()
    winning = plan["queryPlanner"]["winningPlan"]
    stages: list[dict[str, Any]] = []
    _flatten_plan(winning, stages)
    stage_names = [s.get("stage") for s in stages]
    assert "IXSCAN" in stage_names
    assert "COLLSCAN" not in stage_names
    index_names = [s.get("indexName") for s in stages if s.get("indexName")]
    assert index_names and index_names[0] in ("status_1_run_at_1", "status_1_lease_expires_at_1")


async def test_dedup_partial_unique_index_prevents_duplicate_jobs(
    queue: MongoQueue,
) -> None:
    import asyncio

    results = await asyncio.gather(
        *(
            queue.enqueue(
                function="job",
                payload={},
                tenant_id="t",
                dedup_key="email:tenant-c:same",
            )
            for _ in range(25)
        )
    )
    assert len(set(results)) == 1  # one logical job, 25 submissions collapse
    assert await queue.count_documents(STATUS_PENDING) == 1
