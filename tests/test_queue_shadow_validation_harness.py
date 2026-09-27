"""Safety rails of the Phase 17B shadow validation harness.

The harness is a tool an operator will eventually be pointed at a real cluster,
so its refusals are the part that matters most. These tests assert the refusals
*happen*, and that a legitimate sandbox is still reachable - a harness that
refuses everything would pass a naive "it refuses production" test while being
useless.

They also cover the two failure modes of a comparison harness: silently
comparing nothing, and a mismatch that passes anyway.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from backend.queue.envelope import ABSENT, SAMPLE_SUBMISSIONS
from scripts.queue_shadow_validation import (
    UnsafeEndpointError,
    check_endpoint,
    main,
    run,
)

# ----------------------------------------------------------------------
# 1. Endpoint safety
# ----------------------------------------------------------------------


def test_loopback_needs_no_consent() -> None:
    verdict = check_endpoint("mongodb://127.0.0.1:27019")
    assert verdict.allowed is True
    assert verdict.consent == ""


@pytest.mark.parametrize(
    "uri",
    [
        "mongodb+srv://user:pw@cluster0.ab1cd.mongodb.net/webchat",
        "mongodb://user:pw@prod-db.internal:27017/webchat",
        "mongodb://user:pw@production-mongo:27017/webchat",
        "mongodb://user:pw@atlas-shard-01.example.net:27017/webchat",
    ],
)
def test_unnamed_production_hosts_are_refused(uri: str) -> None:
    """The default must never reach anything that looks like production."""
    verdict = check_endpoint(uri)
    assert verdict.allowed is False
    assert verdict.reasons, "a refusal must explain itself"
    assert "--allow-host" in verdict.reasons[0]


def test_an_unnamed_unknown_host_is_also_refused() -> None:
    """Not just production: nothing off the loopback runs unattended."""
    verdict = check_endpoint("mongodb://db.example.org:27017/webchat")
    assert verdict.allowed is False
    assert "not loopback" in verdict.reasons[0]


def test_a_named_sandbox_is_allowed_but_records_the_consent() -> None:
    """A sandbox must be measurable - with the operator's typing on the record."""
    uri = "mongodb+srv://u:p@sandbox-abc.mongodb.net/webchat?retryWrites=true"
    verdict = check_endpoint(uri, ("sandbox-abc.mongodb.net",))
    assert verdict.allowed is True
    assert verdict.consent == "--allow-host sandbox-abc.mongodb.net"


def test_naming_one_host_does_not_unlock_another() -> None:
    """Allow-listing is per host, not a blanket permission."""
    verdict = check_endpoint(
        "mongodb+srv://u:p@other-cluster.mongodb.net/db?retryWrites=true",
        ("sandbox-abc.mongodb.net",),
    )
    assert verdict.allowed is False


def test_a_uri_without_a_hostname_is_rejected() -> None:
    with pytest.raises(UnsafeEndpointError):
        check_endpoint("not-a-uri")


def test_ambiguous_srv_defaults_are_surfaced_as_notes() -> None:
    """A silent environment-dependent default is reported, not inherited."""
    verdict = check_endpoint(
        "mongodb+srv://u:p@sandbox-abc.mongodb.net/db", ("sandbox-abc.mongodb.net",)
    )
    assert verdict.allowed is True
    assert any("retryWrites" in note for note in verdict.notes)


def test_the_refusal_path_exits_non_zero_with_a_clear_message(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(["--mongo-uri", "mongodb+srv://u:p@cluster0.ab1cd.mongodb.net/webchat"])
    assert code == 2
    assert "SAFETY REFUSAL" in capsys.readouterr().err


# ----------------------------------------------------------------------
# 2. The run is real, and executes nothing
# ----------------------------------------------------------------------


async def test_the_harness_compares_every_registered_function() -> None:
    report = await run("mongodb://127.0.0.1:27019", ())
    assert report["registry_complete"] is True
    assert set(report["results"]) == set(report["registered_functions"])
    assert report["jobs_mirrored"] == len(report["registered_functions"])
    # A sweep that compared nothing would trivially "pass".
    assert report["unexplained_total"] == 0
    assert report["all_match"] is True


async def test_the_harness_leaves_no_executed_jobs() -> None:
    """The invariant that keeps this a comparison and not a duplicate run."""
    report = await run("mongodb://127.0.0.1:27019", ())
    assert report["jobs_executed"] == []
    assert report["no_side_effects"] is True


async def test_the_harness_drops_its_collection_on_exit() -> None:
    """No residue in the queue database, whatever the outcome."""
    from motor.motor_asyncio import AsyncIOMotorClient
    from scripts.queue_shadow_validation import SHADOW_COLLECTION, SHADOW_DB

    await run("mongodb://127.0.0.1:27019", ())
    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
        "mongodb://127.0.0.1:27019", serverSelectionTimeoutMS=5000
    )
    assert SHADOW_COLLECTION not in await client[SHADOW_DB].list_collection_names()
    client.close()


async def test_the_harness_never_reads_an_environment_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stray MONGO_URI in the environment cannot aim the tool."""
    monkeypatch.setenv("MONGO_URI", "mongodb+srv://u:p@cluster0.ab1cd.mongodb.net/prod")
    monkeypatch.setenv("MONGODB_URI", "mongodb+srv://u:p@cluster0.ab1cd.mongodb.net/prod")
    report = await run("mongodb://127.0.0.1:27019", ())
    assert report["endpoint"]["host"] == "127.0.0.1"


# ----------------------------------------------------------------------
# 3. The comparison is falsifiable and the gate is real
# ----------------------------------------------------------------------


async def test_a_corrupted_envelope_makes_the_harness_report_a_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Proof the harness can fail - the comparator is not a tautology."""
    from scripts import queue_shadow_validation as harness

    real_from_mongo = harness.from_mongo

    async def _corrupting(queue: Any, function: str, **kwargs: Any) -> Any:
        envelope = await real_from_mongo(queue, function, **kwargs)
        # Drop the per-function timeout: the drift the brief names explicitly.
        return envelope.__class__(**{**envelope.__dict__, "timeout_seconds": 600})

    monkeypatch.setattr(harness, "from_mongo", _corrupting)
    report = await harness.run("mongodb://127.0.0.1:27019", ())
    assert report["all_match"] is False
    assert report["unexplained_total"] > 0


def test_a_mismatch_makes_the_exit_code_non_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Synchronous on purpose: ``main`` drives its own event loop via asyncio.run."""
    from scripts import queue_shadow_validation as harness

    real_from_mongo = harness.from_mongo

    from backend.queue.envelope import payload_shape

    async def _corrupting(queue: Any, function: str, **kwargs: Any) -> Any:
        envelope = await real_from_mongo(queue, function, **kwargs)
        # A changed payload *value* is a real drift with no explainer.
        return envelope.__class__(
            **{
                **envelope.__dict__,
                "payload_shape": payload_shape({"document_id": "tampered", "run_id": None}),
            }
        )

    monkeypatch.setattr(harness, "from_mongo", _corrupting)
    assert harness.main([]) == 1
    assert "MISMATCH" in capsys.readouterr().out


def test_json_output_is_machine_readable(capsys: pytest.CaptureFixture[str]) -> None:
    import io
    from contextlib import redirect_stdout

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        assert main(["--json"]) == 0
    report = json.loads(buffer.getvalue())
    assert report["all_match"] is True
    assert report["no_side_effects"] is True
    assert set(report["compared_fields"]) >= {"function", "payload_keys", "tenant_id"}


def test_the_report_never_contains_a_payload_value() -> None:
    """Message bodies must not leak into an artifact that gets shared."""
    body = SAMPLE_SUBMISSIONS["send_email"]["html"]
    assert body not in ABSENT
    rendered = json.dumps(
        {"payload_keys": sorted(SAMPLE_SUBMISSIONS["send_email"]), "absent": ABSENT}
    )
    assert body not in rendered
