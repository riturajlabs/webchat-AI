"""The claim's query plan is pinned so it cannot silently regress (Phase 17C.1).

Phase 17C measured a ~4.5x p95 / ~0.14x throughput degradation from 100 to
10,000 rows and attributed it to "depth". This module pins the real mechanism,
because the attribution matters for what can safely be changed:

* the claim is served by an index scan, never a collection scan;
* its cost tracks the number of **claimable** rows (the backlog), not the
  number of rows in the collection - 10,000 mostly-terminal rows cost about
  what 500 claimable rows cost;
* the residual cost is a blocking ``SORT`` above the ``FETCH``, because the
  attempt-budget predicate is a field-to-field ``$expr`` that no B-tree can
  answer, so documents must be materialised and sorted before the first row can
  be chosen.

The query under test is captured from the driver's own ``findAndModify`` rather
than re-declared here, so it cannot drift away from the production claim.
Latency is deliberately not asserted: it belongs in the Phase 17C.1 report
measurements, not in a timing-sensitive test. The assertions here are on plan
shape and examined counts, which are deterministic.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import pytest
from backend.prototypes.mongo_queue.config import DEFAULT_MONGO_URI
from backend.queue.mongo.ids import utcnow
from backend.queue.mongo.models import Job
from backend.queue.mongo_adapter import MongoQueueAdapter
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import monitoring

_COLLECTION = "worker_jobs_plan"
_TENANT = "tenant-a"
_FUNCTION = "process_document"
_FUNCTION_PAYLOAD = {"document_id": "d1", "run_id": None}


class _ClaimCapture(monitoring.CommandListener):
    """Records the exact ``findAndModify`` the claim sends."""

    def __init__(self) -> None:
        self.commands: list[dict[str, Any]] = []

    def started(self, event: monitoring.CommandStartedEvent) -> None:
        if event.command_name != "findAndModify":
            return
        if event.command.get("findAndModify") == _COLLECTION:
            self.commands.append(dict(event.command))

    def succeeded(self, event: monitoring.CommandSucceededEvent) -> None:
        pass

    def failed(self, event: monitoring.CommandFailedEvent) -> None:
        pass


@pytest.fixture
async def plan_env(
    queue_db: AsyncIOMotorDatabase[dict[str, Any]],
) -> AsyncIterator[tuple[MongoQueueAdapter, _ClaimCapture, AsyncIOMotorDatabase[dict[str, Any]]]]:
    """An adapter whose driver reports every claim command it sends.

    The listener has to exist at client construction, so this builds its own
    client against the same isolated prototype mongod the rest of the suite
    uses (``PROTOTYPE_MONGO_URI``), never a production endpoint.
    """
    uri = os.environ.get("PROTOTYPE_MONGO_URI", DEFAULT_MONGO_URI)
    capture = _ClaimCapture()
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        uri, serverSelectionTimeoutMS=3000, tz_aware=True, event_listeners=[capture]
    )
    try:
        await client.admin.command("ping")
    except Exception as exc:  # noqa: BLE001 - environment guard
        client.close()
        pytest.skip(f"isolated prototype mongod unreachable at {uri}: {exc}")
    database = client[queue_db.name]
    adapter = MongoQueueAdapter(database, collection_name=_COLLECTION)
    await adapter.ensure_indexes()
    try:
        yield adapter, capture, database
    finally:
        await adapter.queue.collection.delete_many({})
        client.close()


def _stages(node: Any, acc: set[str]) -> None:
    if isinstance(node, dict):
        stage = node.get("stage")
        if isinstance(stage, str):
            acc.add(stage)
        for value in node.values():
            _stages(value, acc)
    elif isinstance(node, list):
        for item in node:
            _stages(item, acc)


async def _explain_claim(
    adapter: MongoQueueAdapter,
    capture: _ClaimCapture,
    database: AsyncIOMotorDatabase[dict[str, Any]],
) -> dict[str, Any]:
    """Explain the production claim against the currently-populated collection."""
    capture.commands.clear()
    await adapter.claim("plan-probe")
    assert capture.commands, "claim() sent no findAndModify to explain"
    command = dict(capture.commands[-1])
    # Keep the real query and sort; drop only what identifies the session, since
    # ``database.command`` supplies ``$db`` itself and rejects a duplicate.
    for key in (
        "upsert",
        "remove",
        "let",
        "arrayFilters",
        "hint",
        "comment",
        "$db",
        "lsid",
        "$clusterTime",
        "txnNumber",
        "bypassDocumentValidation",
    ):
        command.pop(key, None)
    explained = await database.command("explain", command, verbosity="executionStats")

    planner = explained.get("queryPlanner", {})
    winner = planner.get("winningPlan") or planner.get("queryPlan") or {}
    stages: set[str] = set()
    _stages(winner, stages)
    # A plan that cannot be parsed would make the COLLSCAN assertions below
    # vacuously true, so refuse to continue. The claim is a findOneAndUpdate,
    # so a top-level UPDATE stage is always present in a real plan.
    assert "UPDATE" in stages, f"unparseable claim plan: {explained!r:.400}"
    stats = explained.get("executionStats", {})
    return {
        "stages": stages,
        "keys": stats.get("totalKeysExamined", 0),
        "docs": stats.get("totalDocsExamined", 0),
    }


async def _fill(adapter: MongoQueueAdapter, *, rows: int, claimable_every: int) -> None:
    """Insert ``rows`` documents; every ``claimable_every``-th is claimable.

    ``claimable_every == 1`` is an all-claimable backlog (the Phase 17C capacity
    shape). A larger stride leaves mostly-terminal history behind, which is what
    a long-lived deployment actually accumulates.
    """
    now = utcnow()
    docs: list[dict[str, Any]] = []
    for i in range(rows):
        claimable = claimable_every == 1 or i % claimable_every == 0
        docs.append(
            Job(
                id=f"plan-{i}",
                function=_FUNCTION,
                payload=dict(_FUNCTION_PAYLOAD),
                tenant_id=_TENANT,
                status="pending" if claimable else "completed",
                run_at=now - timedelta(seconds=1) if claimable else now - timedelta(days=30),
                max_tries=3,
                execution_version=0,
                created_at=now,
                finished_at=None if claimable else now - timedelta(days=30),
            ).to_doc()
        )
    if docs:
        await adapter.queue.collection.insert_many(docs)


PlanEnv = tuple[MongoQueueAdapter, _ClaimCapture, AsyncIOMotorDatabase[dict[str, Any]]]


@pytest.mark.parametrize(
    ("rows", "claimable_every"),
    [(0, 1), (1, 1), (100, 1), (2_000, 1), (2_000, 20)],
)
async def test_claim_is_served_by_an_index_and_never_a_collection_scan(
    plan_env: PlanEnv,
    rows: int,
    claimable_every: int,
) -> None:
    """The floor: an index scan, at any depth, in either collection shape.

    Phase 17C reported ``index: false`` for a claim plan; that was an
    empty-collection artefact. On an empty collection the server correctly
    answers with an ``IDHACK``/``FETCH`` on ``_id`` and no index scan, so this
    pins the honest invariant - never a collection scan - rather than the
    misleading one.
    """
    adapter, capture, database = plan_env
    await _fill(adapter, rows=rows, claimable_every=claimable_every)
    plan = await _explain_claim(adapter, capture, database)
    assert "COLLSCAN" not in plan["stages"], (rows, claimable_every, plan["stages"])


async def test_terminal_history_does_not_inflate_claim_cost(plan_env: PlanEnv) -> None:
    """10,000 mostly-terminal rows must not cost like 10,000 claimable rows.

    This is the correction to Phase 17C's "depth" framing. If terminal rows ever
    start inflating examined counts, retention stopped working and the claim's
    cost became coupled to collection size again.
    """
    adapter, capture, database = plan_env
    await _fill(adapter, rows=10_000, claimable_every=20)
    plan = await _explain_claim(adapter, capture, database)

    # 5% of 10,000 is 500 claimable rows; examined counts must track that
    # population, not the 10,000 documents present.
    assert plan["docs"] <= 1_500, plan["docs"]
    assert plan["keys"] <= 1_500, plan["keys"]


async def test_claim_cost_tracks_the_claimable_backlog(plan_env: PlanEnv) -> None:
    """Pin the known cost model: examined counts grow with the backlog.

    The claim must return the globally earliest eligible row across two disjoint
    status sets, which the server satisfies with a blocking ``SORT`` above the
    ``FETCH``. That work is proportional to the claimable backlog. This test
    documents the limit so that changing it is a deliberate decision: removing
    the sort would mean changing eligibility semantics or introducing derived
    claimability state, neither of which is a safe pre-commit change.
    """
    adapter, capture, database = plan_env
    docs_examined: dict[int, int] = {}
    for backlog in (100, 1_000):
        await adapter.queue.collection.delete_many({})
        await _fill(adapter, rows=backlog, claimable_every=1)
        docs_examined[backlog] = (await _explain_claim(adapter, capture, database))["docs"]

    assert docs_examined[100] < docs_examined[1_000], docs_examined
    # Bounded by the claimable set, not unbounded and not a full collection walk.
    assert docs_examined[100] <= 150, docs_examined
    assert docs_examined[1_000] <= 1_100, docs_examined
