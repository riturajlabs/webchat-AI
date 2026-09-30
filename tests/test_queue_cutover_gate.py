"""Falsification suite for the read-only cutover gate (Phase 18C).

The gate is only useful if it is *hard to make it say GO*. Every test here tries
to fool it: strand work on a side, make a broker uninspectable, point it at the
wrong pair, and confirm the verdict is NO-GO or UNKNOWN and the exit code is
non-zero. The two GO tests then prove it is not simply always-fail.

The invariant under test: **a cutover is safe only when both sides are
quiesced, and "could not look" is never "looked and found empty".**

Integration coverage uses the isolated prototype Mongo and a throwaway Redis;
nothing here can reach production, and no test enqueues, claims or mutates a job.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from backend.queue.mongo.models import (
    STATUS_COMPLETED,
    STATUS_DEAD,
    STATUS_PENDING,
    STATUS_RETRY_PENDING,
    STATUS_RUNNING,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import queue_cutover_gate as gate  # noqa: E402

GATE_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "queue_cutover_gate.py"


# ----------------------------------------------------------------------
# Fakes
# ----------------------------------------------------------------------


def _side(
    backend: str,
    *,
    pending: int = 0,
    running: int = 0,
    retry_pending: int = 0,
    reachable: bool = True,
    error: str | None = None,
) -> gate.SideCounts:
    counts: dict[str, int | None] = {
        STATUS_PENDING: pending,
        STATUS_RUNNING: running,
        STATUS_RETRY_PENDING: retry_pending,
        STATUS_COMPLETED: 7,
        STATUS_DEAD: 3,
    }
    blocking = pending + running + retry_pending
    return gate.SideCounts(
        backend=backend,
        counts=counts,
        blocking=blocking if reachable else None,
        reachable=reachable,
        error=error,
        endpoint="test://stub",
    )


def _clean() -> dict[str, gate.SideCounts]:
    return {
        gate.BACKEND_ARQ: _side(gate.BACKEND_ARQ),
        gate.BACKEND_MONGO: _side(gate.BACKEND_MONGO),
    }


# ----------------------------------------------------------------------
# 1. The five questions
# ----------------------------------------------------------------------


def test_a_quiesced_pair_is_go() -> None:
    verdict, reasons = gate.decide("arq", "mongo", "arq", _clean())
    assert verdict == gate.VERDICT_GO
    assert any("no non-terminal work" in reason for reason in reasons)


def test_the_report_answers_all_five_questions() -> None:
    report = gate.GateReport(source="arq", target="mongo", configured_backend="arq", sides=_clean())
    report.verdict, report.reasons = gate.decide("arq", "mongo", "arq", report.sides)
    payload = report.as_dict()

    # 1. source/target, 2. per-status counts, 3. non-terminal count,
    # 4. verdict, 5. the read-only attestation.
    assert payload["source"] == "arq" and payload["target"] == "mongo"
    assert payload["sides"]["mongo"]["counts"] == {
        STATUS_PENDING: 0,
        STATUS_RUNNING: 0,
        STATUS_RETRY_PENDING: 0,
        STATUS_COMPLETED: 7,
        STATUS_DEAD: 3,
    }
    assert payload["sides"]["mongo"]["blocking"] == 0
    assert payload["verdict"] == gate.VERDICT_GO
    assert payload["read_only_operations"]
    assert all(
        not any(word in read.lower() for word in ("set", "del", "zadd", "hset", "insert"))
        for read in payload["read_only_operations"]
    )


# ----------------------------------------------------------------------
# 2. Falsification: any straggler blocks
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "status,count",
    [
        (STATUS_PENDING, 1),
        (STATUS_RUNNING, 1),
        (STATUS_RETRY_PENDING, 1),
    ],
)
def test_a_single_straggler_on_the_source_is_no_go(status: str, count: int) -> None:
    sides = _clean()
    sides["arq"] = _side(gate.BACKEND_ARQ, **{status: count})
    verdict, reasons = gate.decide("arq", "mongo", "arq", sides)
    assert verdict == gate.VERDICT_NO_GO
    assert "strand" in reasons[0]


def test_a_straggler_already_sitting_on_the_target_is_no_go() -> None:
    """A target that already holds work means jobs would be lost or doubled."""
    sides = _clean()
    sides["mongo"] = _side(gate.BACKEND_MONGO, running=2)
    verdict, reasons = gate.decide("arq", "mongo", "arq", sides)
    assert verdict == gate.VERDICT_NO_GO
    assert "mongo still holds" in reasons[0]


def test_terminal_only_history_does_not_block() -> None:
    """completed/dead are history: they are auditable, not in flight."""
    sides = _clean()
    sides["mongo"] = _side(gate.BACKEND_MONGO, pending=0, running=0, retry_pending=0)
    sides["mongo"] = gate.SideCounts(
        backend=gate.BACKEND_MONGO,
        counts={
            STATUS_PENDING: 0,
            STATUS_RUNNING: 0,
            STATUS_RETRY_PENDING: 0,
            STATUS_COMPLETED: 4_096,
            STATUS_DEAD: 12,
        },
        blocking=0,
        reachable=True,
    )
    verdict, _ = gate.decide("arq", "mongo", "arq", sides)
    assert verdict == gate.VERDICT_GO


# ----------------------------------------------------------------------
# 3. Falsification: unavailable must never read as empty
# ----------------------------------------------------------------------


@pytest.mark.parametrize("backend", [gate.BACKEND_ARQ, gate.BACKEND_MONGO])
def test_an_unreachable_backend_is_unknown_not_empty(backend: str) -> None:
    sides = _clean()
    sides[backend] = _side(backend, reachable=False, error="Connection refused")
    verdict, reasons = gate.decide("arq", "mongo", "arq", sides)
    assert verdict == gate.VERDICT_UNKNOWN
    assert "could not be inspected" in reasons[0]


def test_a_side_that_was_never_probed_is_unknown() -> None:
    verdict, reasons = gate.decide("arq", "mongo", "arq", {gate.BACKEND_ARQ: _side("arq")})
    assert verdict == gate.VERDICT_UNKNOWN
    assert "not probed" in reasons[0]


# ----------------------------------------------------------------------
# 4. Falsification: wrong pair / malformed input
# ----------------------------------------------------------------------


def test_source_equal_to_target_is_never_go() -> None:
    verdict, reasons = gate.decide("mongo", "mongo", "mongo", _clean())
    assert verdict == gate.VERDICT_NO_GO
    assert "no cutover to gate" in reasons[0]


def test_a_declared_source_that_contradicts_queue_backend_is_unknown() -> None:
    """Claiming to drain Mongo while ARQ is still live would gate the wrong run."""
    verdict, reasons = gate.decide("mongo", "arq", "arq", _clean())
    assert verdict == gate.VERDICT_UNKNOWN
    assert "does not match" in reasons[0]


def test_an_unknown_backend_name_is_unknown() -> None:
    verdict, _ = gate.decide("postgres", "mongo", "postgres", _clean())
    assert verdict == gate.VERDICT_UNKNOWN


# ----------------------------------------------------------------------
# 5. Exit codes: only a proven GO is zero
# ----------------------------------------------------------------------


def test_exit_codes_map_go_to_zero_and_everything_else_away() -> None:
    assert gate.EXIT_GO == 0
    assert gate.EXIT_NO_GO != 0
    assert gate.EXIT_UNKNOWN != 0
    assert (
        gate.EXIT_GO,
        gate.EXIT_NO_GO,
        gate.EXIT_UNKNOWN,
    ) == (0, 1, 2)


def test_missing_environment_is_unknown_and_non_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No silent localhost fallback: an unset URI must not become a local check."""
    for name in ("MONGODB_URI", "MONGODB_QUEUE_DATABASE", "REDIS_URL", "QUEUE_BACKEND"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(gate.GateConfigError) as excinfo:
        gate.resolve_config()
    assert "MONGODB_URI" in str(excinfo.value)
    assert "refusing to fall back" in str(excinfo.value)

    code = gate.main(["--from", "arq", "--to", "mongo"])
    assert code == gate.EXIT_UNKNOWN


# ----------------------------------------------------------------------
# 6. Redaction
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "uri,forbidden,has_userinfo",
    [
        (
            "mongodb+srv://user:sup3rs3cret@cluster0.example.net/prod?ssl=true",
            "sup3rs3cret",
            True,
        ),
        ("redis://admin:hunter2@10.0.0.5:6379/0", "hunter2", True),
        # A query-string secret is removed outright - there is nothing to mask.
        ("rediss://cache.example.net:6380/0?sslPassword=letmein", "letmein", False),
    ],
)
def test_credentials_never_reach_the_output(uri: str, forbidden: str, has_userinfo: bool) -> None:
    redacted = gate.redact_uri(uri)
    assert forbidden not in redacted
    # Credentials appear in the userinfo and in the query string; both are gone.
    assert "?" not in redacted
    assert ("***" in redacted) is has_userinfo
    # The operator still needs to know *which* host, so host and db survive.
    assert urlsplit_host(redacted) == urlsplit_host(uri)


def urlsplit_host(uri: str) -> str:
    from urllib.parse import urlsplit

    return urlsplit(uri).hostname or ""


def test_the_rendered_report_contains_no_uri_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    import urllib.parse

    sides = _clean()
    sides["mongo"] = gate.SideCounts(
        backend=gate.BACKEND_MONGO,
        counts=dict.fromkeys(gate.MONGO_STATUSES, 0),
        blocking=0,
        reachable=True,
        endpoint="mongodb+srv://***@cluster0.example.net/webchat_ai_queue.worker_jobs",
    )
    report = gate.GateReport(source="arq", target="mongo", configured_backend="arq", sides=sides)
    report.verdict, report.reasons = gate.decide("arq", "mongo", "arq", sides)
    text = gate.render(report)
    assert "mongodb+srv://***@cluster0.example.net" in text
    assert "user:sup3rs3cret" not in text
    assert urllib.parse.urlsplit("mongodb+srv://***@host/db").hostname == "host"


# ----------------------------------------------------------------------
# 7. ARQ probe: untracked states are None, never 0
# ----------------------------------------------------------------------


def test_arq_reports_completed_and_dead_as_untracked() -> None:
    """ARQ TTLs results and has no dead-letter store; claiming 0 would be a lie."""
    counts = {status: None for status in gate.MONGO_STATUSES}
    side = gate.SideCounts(backend=gate.BACKEND_ARQ, counts=counts, blocking=0, reachable=True)
    assert side.counts[STATUS_COMPLETED] is None
    assert side.counts[STATUS_DEAD] is None
    # ...and the gate still blocks on the states ARQ *does* track.
    assert side.blocking == 0


# ----------------------------------------------------------------------
# 8. The gate cannot write, even by accident
# ----------------------------------------------------------------------


def test_the_gate_source_issues_no_mutating_redis_or_mongo_call() -> None:
    """A structural guard: no write verb appears in the probe paths."""
    source = GATE_SCRIPT.read_text()
    forbidden = (
        ".zadd(",
        ".hset(",
        ".set(",
        ".delete(",
        ".lpush(",
        ".rpush(",
        ".sadd(",
        ".flushdb(",
        ".flushall(",
        "insert_one",
        "insert_many",
        "update_one",
        "update_many",
        "find_one_and_update",
        "bulk_write",
        "drop(",
        ".enqueue(",
        ".claim(",
        ".fail(",
        ".requeue",
    )
    for verb in forbidden:
        assert verb not in source, f"gate must not call {verb}"


def test_the_gate_never_defaults_to_a_localhost_endpoint() -> None:
    source = GATE_SCRIPT.read_text()
    for default in ("mongodb://localhost", "redis://localhost", "127.0.0.1", "0.0.0.0"):
        assert default not in source, f"gate must not hardcode {default}"


# ----------------------------------------------------------------------
# 9. Real brokers: read-only against isolated infrastructure
# ----------------------------------------------------------------------


@pytest.fixture
async def isolated_mongo() -> Any:
    """The isolated prototype mongod, never Atlas and never the dev stack.

    Mirrors backend/queue/tests/conftest.py, but lives here so this suite stays
    inside the default ``testpaths`` and needs no extra pytest invocation.
    """
    import os

    from backend.prototypes.mongo_queue.config import DEFAULT_MONGO_URI
    from backend.queue.mongo.ids import new_job_id
    from motor.motor_asyncio import AsyncIOMotorClient

    uri = os.environ.get("PROTOTYPE_MONGO_URI", DEFAULT_MONGO_URI)
    client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=3000)
    try:
        await client.admin.command("ping")
    except Exception as exc:  # noqa: BLE001 - environment guard
        client.close()
        pytest.skip(f"isolated prototype mongod unreachable at {uri}: {exc}")

    db_name = f"webchat_ai_gate_test_{new_job_id()[:8]}"
    database = client[db_name]
    yield uri, database
    await client.drop_database(db_name)
    client.close()


@pytest.mark.asyncio
async def test_the_mongo_probe_reads_real_counts_without_mutating(
    isolated_mongo: tuple[str, Any],
) -> None:
    uri, database = isolated_mongo
    await database["worker_jobs"].insert_many(
        [
            {"status": STATUS_PENDING},
            {"status": STATUS_RUNNING},
            {"status": STATUS_RETRY_PENDING},
            {"status": STATUS_COMPLETED},
            {"status": STATUS_DEAD},
        ]
    )

    side = await gate.probe_mongo(uri, database.name, "worker_jobs")

    assert side.reachable, side.error
    assert side.counts == {
        STATUS_PENDING: 1,
        STATUS_RUNNING: 1,
        STATUS_RETRY_PENDING: 1,
        STATUS_COMPLETED: 1,
        STATUS_DEAD: 1,
    }
    assert side.blocking == 3
    # The password-free URI still identifies the instance, for the operator.
    assert "***" not in side.endpoint  # this test URI has no credentials
    assert database.name in side.endpoint

    # Counting created, updated and removed nothing.
    assert await database["worker_jobs"].count_documents({}) == 5


@pytest.mark.asyncio
async def test_the_mongo_probe_reports_an_unreachable_broker_as_unknown() -> None:
    """A refused/unreachable broker must never surface as a count of zero."""
    side = await gate.probe_mongo("mongodb://127.0.0.1:1", "webchat_ai_queue", "worker_jobs")
    assert side.reachable is False
    assert side.blocking is None
    assert side.counts[STATUS_PENDING] is None
    assert side.error


@pytest.mark.asyncio
async def test_the_arq_probe_reads_real_counts_without_mutating() -> None:
    """Counts ARQ's own structures, and only counts them."""
    import os

    from redis.asyncio import Redis

    url = os.environ.get("QUEUE_TEST_ARQ_REDIS_URL") or "redis://127.0.0.1:27029"
    client = Redis.from_url(url, socket_timeout=2, socket_connect_timeout=2)
    try:
        await client.ping()
    except Exception as exc:  # noqa: BLE001 - isolated Redis is optional
        await client.aclose()
        pytest.skip(f"isolated ARQ Redis unavailable: {exc}")

    queue_key = "arq:queue"
    in_progress_key = "arq:in-progress:arq:queue"
    abort_key = "arq:abort"
    before = await client.zcard(queue_key)
    try:
        await client.zadd(queue_key, {"gate-soon": 1, "gate-later": 4_102_444_800_000})
        await client.hset(in_progress_key, mapping={"gate-busy": "worker-1"})
        await client.sadd(abort_key, "gate-abort")

        side = await gate.probe_arq(url)

        assert side.reachable, side.error
        # One future-scored (deferred) entry and one due-now (pending) entry.
        assert side.counts[STATUS_RETRY_PENDING] == 1
        assert side.counts[STATUS_PENDING] == before + 1
        assert side.counts[STATUS_RUNNING] == 2  # in-progress + abort
        # ARQ has no dead-letter store and TTLs results: untracked, not zero.
        assert side.counts[STATUS_DEAD] is None
        assert side.counts[STATUS_COMPLETED] is None
        assert side.blocking == 4
    finally:
        await client.zrem(queue_key, "gate-soon", "gate-later")
        await client.hdel(in_progress_key, "gate-busy")
        await client.srem(abort_key, "gate-abort")
        await client.aclose()

    # The probe left the queue exactly as it found it.
    assert await client.zcard(queue_key) == before


@pytest.mark.asyncio
async def test_the_arq_probe_reports_an_unreachable_broker_as_unknown() -> None:
    side = await gate.probe_arq("redis://127.0.0.1:1/0")
    assert side.reachable is False
    assert side.blocking is None
    assert side.error


# ----------------------------------------------------------------------
# 10. End-to-end: the CLI
# ----------------------------------------------------------------------


def test_the_cli_rejects_source_equal_to_target() -> None:
    result = subprocess.run(
        [sys.executable, str(GATE_SCRIPT), "--from", "mongo", "--to", "mongo"],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert result.returncode != 0
    assert "VERDICT" in (result.stdout + result.stderr)


def test_the_cli_help_documents_the_read_only_contract() -> None:
    result = subprocess.run(
        [sys.executable, str(GATE_SCRIPT), "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "read-only" in result.stdout.lower() or "READ-ONLY" in result.stdout
