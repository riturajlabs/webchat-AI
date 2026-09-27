"""FIND-03: terminal crawl jobs must never be resurrected by a stale write.

Reproduced during the Phase 17B crawl staging simulation, where a
dual-execution test intermittently observed TWO ``crawl.completed`` publishes
and TWO terminal audit rows for one crawl job.

The original defect
-------------------
``CrawlJobRepository.update`` was an unconditional ``replace_one`` scoped only
by ``(_id, tenant_id)``. A duplicate delivery - a redelivery, or a reclaim
after a queue lease expiry - that is still mid-crawl holds a stale in-memory
``CrawlJob`` whose status is active. When the winning attempt had already
transitioned the row to a terminal state, that stale write rolled the row back
to active, and a subsequent ``finish_if_active`` then succeeded a second time,
re-running every winner-gated side effect: the document purge, the website
write, the audit row, the ``crawl_pages`` rollup and usage event, and the
knowledge fan-out.

Queue ``execution_version`` fencing does not prevent this. It guards the queue
row, not this collection, and the unsafe domain write happens *before* the
worker tries to close the queue row - so the stale attempt is still writing
domain state while it legitimately believes it owns the queue job.

The fix
-------
``update`` is now fenced on ``status in CRAWL_ACTIVE_STATUSES`` (in addition to
``_id`` and ``tenant_id``) and returns whether the write was applied. Terminal
states are therefore monotonic at the persistence boundary rather than by
caller convention, and a caller can tell that it lost the race.

These tests pin that invariant on the REAL Mongo repository (isolated local
mongod) and on the in-memory fake, and assert the two agree - so a future
divergence between them fails loudly.
"""

from __future__ import annotations

import pytest
from backend.core.errors import CrawlConflictError
from backend.core.security import utcnow
from backend.models.crawl_job import (
    CRAWL_ACTIVE_STATUSES,
    CRAWL_STATUS_COMPLETED,
    CRAWL_STATUS_FAILED,
    CRAWL_STATUS_PENDING,
    CRAWL_STATUS_PROCESSING,
    CRAWL_STATUS_RUNNING,
    CRAWL_STATUSES,
    CrawlJob,
)
from backend.repositories.crawl_job_repository import MongoCrawlJobRepository
from motor.motor_asyncio import AsyncIOMotorDatabase
from tests.fakes import FakeCrawlJobRepository

TENANT = "tenant-a"

#: The only statuses from which a crawl job may never return to active.
#: Derived from `CRAWL_STATUSES - CRAWL_ACTIVE_STATUSES` in the model, NOT
#: hand-maintained, so a new status cannot silently escape this matrix.
TERMINAL_STATUSES = sorted(CRAWL_STATUSES - CRAWL_ACTIVE_STATUSES)

REPOSITORIES = ("fake", "mongo")


def _assert_terminal_statuses_are_the_real_ones() -> None:
    """Guard the matrix itself: it must stay in sync with the model."""
    assert TERMINAL_STATUSES == [CRAWL_STATUS_COMPLETED, CRAWL_STATUS_FAILED]
    assert set(TERMINAL_STATUSES).isdisjoint(CRAWL_ACTIVE_STATUSES)
    assert CRAWL_STATUS_PENDING in CRAWL_ACTIVE_STATUSES
    assert CRAWL_STATUS_RUNNING in CRAWL_ACTIVE_STATUSES
    assert CRAWL_STATUS_PROCESSING in CRAWL_ACTIVE_STATUSES


@pytest.fixture
async def repos(
    queue_db: AsyncIOMotorDatabase[dict[str, object]],
) -> dict[str, FakeCrawlJobRepository | MongoCrawlJobRepository]:
    """Both implementations, wired to fresh isolated state.

    The production index migration is run so the Mongo repository behaves
    exactly as it does in a real deployment (notably the FIND-02 single-flight
    partial unique index, which `create` depends on to raise
    `CrawlConflictError`).
    """
    _assert_terminal_statuses_are_the_real_ones()
    from backend.core.database import _ensure_crawl_job_active_index

    await _ensure_crawl_job_active_index(queue_db)
    mongo = MongoCrawlJobRepository(queue_db)
    return {"fake": FakeCrawlJobRepository(), "mongo": mongo}


def _make_job() -> CrawlJob:
    return CrawlJob.new(tenant_id=TENANT, website_id="website-1")


# ----------------------------------------------------------------------
# 10. direct resurrection
# ----------------------------------------------------------------------


@pytest.mark.parametrize("kind", REPOSITORIES)
@pytest.mark.parametrize("terminal_status", TERMINAL_STATUSES)
async def test_a_stale_active_snapshot_cannot_resurrect_a_terminal_job(
    repos: dict[str, FakeCrawlJobRepository | MongoCrawlJobRepository],
    kind: str,
    terminal_status: str,
) -> None:
    """The core invariant, for every real terminal status."""
    repo = repos[kind]
    job = _make_job()
    await repo.create(job)

    # A and B both hold an active snapshot of the same row.
    worker_a = await repo.find_by_id_any(job.id)
    worker_b = await repo.find_by_id_any(job.id)
    assert worker_a is not None and worker_b is not None

    # B wins the terminator.
    assert await repo.finish_if_active(
        job.id, TENANT, terminal_status=terminal_status, pages_completed=12
    )
    won = await repo.find_by_id_any(job.id)
    assert won is not None
    assert won.status == terminal_status
    assert won.active is False

    # A resumes and tries to persist its stale ACTIVE snapshot.
    worker_a.status = CRAWL_STATUS_RUNNING
    worker_a.active = True
    worker_a.pages_completed = 3
    applied = await repo.update(worker_a)
    assert applied is False, f"{kind}: a stale active write was reported as applied"

    # The row is still terminal, with the winner's fields intact.
    after = await repo.find_by_id_any(job.id)
    assert after is not None
    assert after.status == terminal_status, f"{kind}: the crawl job was resurrected"
    assert after.active is False
    assert after.pages_completed == 12, f"{kind}: the winner's fields were rewound"

    # And A can no longer win a second terminator.
    assert not await repo.finish_if_active(job.id, TENANT, terminal_status=terminal_status), (
        f"{kind}: a second terminal transition succeeded after resurrection"
    )


@pytest.mark.parametrize("kind", REPOSITORIES)
async def test_the_winners_terminal_fields_are_not_rewound(
    repos: dict[str, FakeCrawlJobRepository | MongoCrawlJobRepository], kind: str
) -> None:
    """The rollback was not just the status flag; `completed_at` was cleared."""
    repo = repos[kind]
    job = _make_job()
    await repo.create(job)
    stale = await repo.find_by_id_any(job.id)
    assert stale is not None

    assert await repo.finish_if_active(
        job.id,
        TENANT,
        terminal_status=CRAWL_STATUS_COMPLETED,
        completed_at=utcnow(),
        pages_completed=12,
        pages_total=12,
    )
    winner = await repo.find_by_id_any(job.id)
    assert winner is not None
    assert winner.completed_at is not None

    stale.pages_completed = 3
    stale.completed_at = None
    assert await repo.update(stale) is False

    after = await repo.find_by_id_any(job.id)
    assert after is not None
    assert after.pages_completed == 12
    assert after.completed_at is not None


# ----------------------------------------------------------------------
# 15. legitimate active updates still work
# ----------------------------------------------------------------------


@pytest.mark.parametrize("kind", REPOSITORIES)
@pytest.mark.parametrize(
    "status", sorted(CRAWL_ACTIVE_STATUSES)
)
async def test_a_valid_active_crawl_can_still_be_updated(
    repos: dict[str, FakeCrawlJobRepository | MongoCrawlJobRepository], kind: str, status: str
) -> None:
    """Guards against "fixing" FIND-03 by making `update` unusable."""
    repo = repos[kind]
    job = _make_job()
    await repo.create(job)

    live = await repo.find_by_id_any(job.id)
    assert live is not None
    live.status = status
    live.pages_completed = 5
    live.pages_total = 9
    assert await repo.update(live) is True, f"{kind}: a legitimate active update was rejected"

    stored = await repo.find_by_id_any(job.id)
    assert stored is not None
    assert stored.status == status
    assert stored.pages_completed == 5
    assert stored.pages_total == 9
    assert stored.active is True


@pytest.mark.parametrize("kind", REPOSITORIES)
async def test_an_active_row_may_still_be_transitioned_to_terminal_via_update(
    repos: dict[str, FakeCrawlJobRepository | MongoCrawlJobRepository], kind: str
) -> None:
    """The fence constrains the STORED row, not the incoming snapshot.

    Writing a terminal status over an active row is legitimate and is used by
    tests and by the service layer; only an already-terminal row is immutable.
    """
    repo = repos[kind]
    job = _make_job()
    await repo.create(job)

    live = await repo.find_by_id_any(job.id)
    assert live is not None
    live.status = CRAWL_STATUS_FAILED
    live.active = False
    assert await repo.update(live) is True

    stored = await repo.find_by_id_any(job.id)
    assert stored is not None
    assert stored.status == CRAWL_STATUS_FAILED
    # And it is now immutable.
    assert await repo.update(live) is False


@pytest.mark.parametrize("kind", REPOSITORIES)
async def test_repeated_progress_updates_are_all_applied_while_active(
    repos: dict[str, FakeCrawlJobRepository | MongoCrawlJobRepository], kind: str
) -> None:
    """The ordinary crawl loop writes progress many times; none may be lost."""
    repo = repos[kind]
    job = _make_job()
    await repo.create(job)

    live = await repo.find_by_id_any(job.id)
    assert live is not None
    live.status = CRAWL_STATUS_PROCESSING
    for completed in range(1, 6):
        live.pages_completed = completed
        assert await repo.update(live) is True, f"{kind}: progress write {completed} was dropped"

    stored = await repo.find_by_id_any(job.id)
    assert stored is not None
    assert stored.pages_completed == 5
    assert stored.status == CRAWL_STATUS_PROCESSING


# ----------------------------------------------------------------------
# 21. tenant scoping must be preserved, never narrowed to _id alone
# ----------------------------------------------------------------------


@pytest.mark.parametrize("kind", REPOSITORIES)
async def test_a_stale_write_cannot_cross_tenants(
    repos: dict[str, FakeCrawlJobRepository | MongoCrawlJobRepository], kind: str
) -> None:
    """A foreign-tenant snapshot must never land, active or otherwise."""
    repo = repos[kind]
    job = _make_job()
    await repo.create(job)

    impostor = await repo.find_by_id_any(job.id)
    assert impostor is not None
    impostor.tenant_id = "tenant-b"
    assert await repo.update(impostor) is False

    # The owner's row is untouched.
    stored = await repo.find_by_id_any(job.id)
    assert stored is not None
    assert stored.tenant_id == TENANT

    # A foreign read is not even possible.
    assert await repo.find_by_id("tenant-b", job.id) is None


@pytest.mark.parametrize("kind", REPOSITORIES)
async def test_a_terminal_row_cannot_be_reopened_by_a_foreign_tenant(
    repos: dict[str, FakeCrawlJobRepository | MongoCrawlJobRepository], kind: str
) -> None:
    repo = repos[kind]
    job = _make_job()
    await repo.create(job)
    assert await repo.finish_if_active(job.id, TENANT, terminal_status=CRAWL_STATUS_COMPLETED)

    intruder = await repo.find_by_id_any(job.id)
    assert intruder is not None
    intruder.tenant_id = "tenant-b"
    intruder.status = CRAWL_STATUS_RUNNING
    assert await repo.update(intruder) is False
    # A foreign terminator is refused too.
    assert not await repo.finish_if_active(
        job.id, "tenant-b", terminal_status=CRAWL_STATUS_FAILED
    )

    stored = await repo.find_by_id_any(job.id)
    assert stored is not None
    assert stored.status == CRAWL_STATUS_COMPLETED
    assert stored.tenant_id == TENANT


# ----------------------------------------------------------------------
# 18. fake/production parity
# ----------------------------------------------------------------------


@pytest.mark.parametrize("kind", REPOSITORIES)
async def test_the_write_filter_is_scoped_by_id_and_tenant(
    queue_db: AsyncIOMotorDatabase[dict[str, object]], kind: str
) -> None:
    """The Mongo filter must keep BOTH scopes plus the status fence.

    Asserted by observing behaviour rather than by reading source, so a
    refactor cannot quietly weaken the filter.
    """
    if kind == "fake":
        pytest.skip("filter shape is a Mongo concern")
    repo = MongoCrawlJobRepository(queue_db)
    job = _make_job()
    await repo.create(job)

    # Wrong id.
    ghost = job.model_copy(deep=True)
    ghost.id = "does-not-exist"
    assert await repo.update(ghost) is False
    # Right id, wrong tenant.
    foreign = job.model_copy(deep=True)
    foreign.tenant_id = "tenant-b"
    assert await repo.update(foreign) is False
    # Right id, right tenant, active row: accepted.
    assert await repo.update(job) is True


async def test_a_second_active_job_for_the_same_website_is_still_refused(
    repos: dict[str, FakeCrawlJobRepository | MongoCrawlJobRepository],
) -> None:
    """The single-flight marker must survive this change (FIND-02)."""
    for repo in repos.values():
        first = _make_job()
        await repo.create(first)
        with pytest.raises(CrawlConflictError):
            await repo.create(_make_job())


# ----------------------------------------------------------------------
# 16. 100 controlled races, deterministically synchronised
# ----------------------------------------------------------------------


@pytest.mark.parametrize("kind", REPOSITORIES)
async def test_one_hundred_stale_writer_vs_terminal_winner_races(
    repos: dict[str, FakeCrawlJobRepository | MongoCrawlJobRepository], kind: str
) -> None:
    """100 interleavings of "stale active writer" against "terminal winner".

    Deterministic by construction: the stale snapshot is captured while the row
    is active, the winner then terminalises the row, and only then does the
    stale write land. That is exactly the FIND-03 ordering, and it is enforced
    by awaiting each step in turn rather than by sleeping.
    """
    repo = repos[kind]
    resurrection = 0
    double_winner = 0
    rewound = 0
    races = 100

    for _ in range(races):
        job = CrawlJob.new(tenant_id=TENANT, website_id=f"website-{_}")
        await repo.create(job)

        stale = await repo.find_by_id_any(job.id)
        assert stale is not None
        stale.status = CRAWL_STATUS_RUNNING
        stale.pages_completed = 1

        if not await repo.finish_if_active(
            job.id, TENANT, terminal_status=CRAWL_STATUS_COMPLETED, pages_completed=42
        ):
            pytest.fail(f"{kind}: the first terminator unexpectedly lost")

        applied = await repo.update(stale)
        if applied:
            resurrection += 1

        if await repo.finish_if_active(
            job.id, TENANT, terminal_status=CRAWL_STATUS_COMPLETED, pages_completed=42
        ):
            double_winner += 1

        final = await repo.find_by_id_any(job.id)
        assert final is not None
        if final.status != CRAWL_STATUS_COMPLETED or final.active is not False:
            resurrection += 1
        if final.pages_completed != 42:
            rewound += 1

    assert resurrection == 0, f"{kind}: {resurrection}/{races} terminal rows were resurrected"
    assert double_winner == 0, f"{kind}: {double_winner}/{races} rows had two terminal winners"
    assert rewound == 0, f"{kind}: {rewound}/{races} rows lost the winner's terminal fields"


@pytest.mark.parametrize("kind", REPOSITORIES)
async def test_one_hundred_interleaved_winner_and_stale_writer_orderings(
    repos: dict[str, FakeCrawlJobRepository | MongoCrawlJobRepository], kind: str
) -> None:
    """Both orderings, 100 each, alternating.

    Guards the other side of the race: a stale write that lands *before* the
    terminator is legitimate and must still be accepted, otherwise the fix
    would have broken normal progress reporting.
    """
    repo = repos[kind]
    for index in range(100):
        job = CrawlJob.new(tenant_id=TENANT, website_id=f"website-order-{index}")
        await repo.create(job)
        stale = await repo.find_by_id_any(job.id)
        assert stale is not None
        stale.pages_completed = 7

        if index % 2 == 0:
            # Stale write first: legitimate, must be accepted.
            assert await repo.update(stale) is True
            assert await repo.finish_if_active(
                job.id, TENANT, terminal_status=CRAWL_STATUS_COMPLETED, pages_completed=7
            )
        else:
            # Winner first: the stale write must be rejected.
            assert await repo.finish_if_active(
                job.id, TENANT, terminal_status=CRAWL_STATUS_COMPLETED, pages_completed=7
            )
            assert await repo.update(stale) is False

        final = await repo.find_by_id_any(job.id)
        assert final is not None
        assert final.status == CRAWL_STATUS_COMPLETED
        assert final.active is False
