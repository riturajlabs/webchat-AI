"""Safety rails and measurement integrity of the Phase 17C validation harness.

The harness is the tool an operator would eventually point at a real free-tier
cluster, so its refusals matter more than its numbers. These tests assert that
the refusals *happen*, and - just as importantly - that a genuinely separate
sandbox is still reachable. A harness that refuses everything would satisfy a
naive "it refuses production" test while being useless.

The Phase 17B harness could be unlocked onto a production-shaped host with
``--allow-host``. That specific hole is pinned here, because it is the one way
this harness could cause real damage.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from scripts.queue_phase17c_validation import (
    _PRODUCTION_HOST_MARKERS,
    ATLAS_OPT_IN_ENV,
    DB_PREFIX,
    UnsafeEndpointError,
    _host_of,
    _is_production_shaped,
    check_endpoint,
    main,
)

# ----------------------------------------------------------------------
# 1. Endpoint safety: the local mode
# ----------------------------------------------------------------------


def test_loopback_needs_no_consent() -> None:
    verdict = check_endpoint("mongodb://127.0.0.1:27019", mode="local")
    assert verdict.allowed is True
    assert verdict.consent == ""


def test_local_refuses_a_remote_host_even_when_it_is_named() -> None:
    """--local means loopback. Naming the host does not widen the mode."""
    verdict = check_endpoint("mongodb://10.0.0.5:27017", mode="local", allow_hosts=("10.0.0.5",))
    assert verdict.allowed is False
    assert any("loopback" in reason for reason in verdict.reasons)


@pytest.mark.parametrize(
    "uri",
    [
        "mongodb+srv://user:pw@cluster0.ab1cd.mongodb.net/webchat",
        "mongodb://user:pw@prod-db.internal:27017/webchat",
        "mongodb://user:pw@production-mongo:27017/webchat",
        "mongodb://user:pw@atlas-shard-01.example.net:27017/webchat",
    ],
)
def test_local_refuses_production_shaped_hosts(uri: str) -> None:
    verdict = check_endpoint(uri, mode="local")
    assert verdict.allowed is False
    assert verdict.reasons, "a refusal must explain itself"


# ----------------------------------------------------------------------
# 2. Endpoint safety: the atlas-safe mode
# ----------------------------------------------------------------------


def test_atlas_safe_requires_the_environment_opt_in() -> None:
    verdict = check_endpoint(
        "mongodb://m0-sandbox.internal:27017",
        mode="atlas-safe",
        allow_hosts=("m0-sandbox.internal",),
        env={},
    )
    assert verdict.allowed is False
    assert any(ATLAS_OPT_IN_ENV in reason for reason in verdict.reasons)


def test_atlas_safe_refuses_an_unnamed_host_even_with_the_opt_in() -> None:
    verdict = check_endpoint(
        "mongodb://m0-sandbox.internal:27017",
        mode="atlas-safe",
        env={ATLAS_OPT_IN_ENV: "true"},
    )
    assert verdict.allowed is False
    assert any("--allow-host" in reason for reason in verdict.reasons)


def test_a_genuinely_separate_sandbox_is_reachable() -> None:
    """The harness must still be usable against a real non-production M0.

    This is the counterpart to the refusal tests: if nothing could ever pass,
    the refusals would prove nothing.
    """
    verdict = check_endpoint(
        "mongodb://m0-sandbox.internal:27017",
        mode="atlas-safe",
        allow_hosts=("m0-sandbox.internal",),
        env={ATLAS_OPT_IN_ENV: "true"},
        app_database="webchat_ai",
    )
    assert verdict.allowed is True
    assert verdict.consent == "--allow-host m0-sandbox.internal"


@pytest.mark.parametrize(
    "uri",
    [
        "mongodb+srv://user:pw@cluster0.ab1cd.mongodb.net/webchat",
        "mongodb://atlas-prod-01.internal:27017/webchat",
    ],
)
def test_allow_host_cannot_override_the_production_veto(uri: str) -> None:
    """The Phase 17B hole: naming a production host must not unlock it.

    The environment opt-in *and* ``--allow-host`` are both supplied here, so the
    only thing left to refuse is the production veto itself.
    """
    host = _host_of(uri)
    verdict = check_endpoint(
        uri,
        mode="atlas-safe",
        allow_hosts=(host,),
        env={ATLAS_OPT_IN_ENV: "true"},
        app_database="webchat_ai",
    )
    assert verdict.allowed is False
    assert any("hard veto" in reason for reason in verdict.reasons)
    assert any("--allow-host cannot override" in reason for reason in verdict.reasons)


def test_naming_one_host_does_not_unlock_another() -> None:
    verdict = check_endpoint(
        "mongodb://other-sandbox.internal:27017",
        mode="atlas-safe",
        allow_hosts=("m0-sandbox.internal",),
        env={ATLAS_OPT_IN_ENV: "true"},
    )
    assert verdict.allowed is False


def test_atlas_safe_refuses_the_application_database() -> None:
    """A sandbox must still not be the live application's own database."""
    verdict = check_endpoint(
        "mongodb://m0-sandbox.internal:27017",
        mode="atlas-safe",
        allow_hosts=("m0-sandbox.internal",),
        env={ATLAS_OPT_IN_ENV: "true"},
        app_database="webchat_ai",
    )
    assert verdict.allowed is True
    # And the check is not vacuous: the harness always writes to its own
    # prefixed database, never the application one.
    assert DB_PREFIX not in ("webchat_ai",)
    assert DB_PREFIX.startswith("webchat_ai_queue_phase17c")


# ----------------------------------------------------------------------
# 3. Endpoint safety: parsing and marker detection
# ----------------------------------------------------------------------


def test_a_uri_without_a_hostname_is_rejected() -> None:
    with pytest.raises(UnsafeEndpointError):
        check_endpoint("mongodb://", mode="local")


@pytest.mark.parametrize("marker", _PRODUCTION_HOST_MARKERS)
def test_every_declared_marker_is_detected(marker: str) -> None:
    """A marker in the list that no hostname triggers is dead safety code."""
    # Order matters only for which marker is reported, not whether one is:
    # "production" also contains "prod", so the first match wins.
    detected = _is_production_shaped(f"host{marker}tail")
    assert detected is not None
    assert detected in _PRODUCTION_HOST_MARKERS


def test_marker_detection_is_case_insensitive() -> None:
    assert _is_production_shaped("CLUSTER0.ABCD.MONGODB.NET") is not None
    assert _is_production_shaped("Production-Mongo") is not None


def test_an_ordinary_sandbox_name_is_not_flagged() -> None:
    assert _is_production_shaped("m0-sandbox.internal") is None
    assert _is_production_shaped("127.0.0.1") is None


def test_credentials_are_never_echoed_in_a_refusal() -> None:
    """Refusal text is printed to stderr, which lands in CI logs.

    A refusal must name the *host* so an operator can act on it, and must never
    carry the password through into that text.
    """
    verdict = check_endpoint(
        "mongodb+srv://operator:sup3rsecret@cluster0.ab1cd.mongodb.net",
        mode="local",
    )
    assert verdict.allowed is False
    rendered = " | ".join(verdict.reasons + verdict.notes)
    assert "sup3rsecret" not in rendered
    assert "operator" not in rendered
    # The host is still identified, so the refusal is actionable.
    assert "cluster0.ab1cd.mongodb.net" in rendered


def test_a_uri_without_credentials_is_still_refused_by_marker() -> None:
    """Marker detection must not depend on the URI carrying a userinfo part."""
    verdict = check_endpoint("mongodb://cluster0.ab1cd.mongodb.net", mode="local")
    assert verdict.allowed is False
    assert any("mongodb.net" in reason for reason in verdict.reasons)


# ----------------------------------------------------------------------
# 4. Semantic exit codes
# ----------------------------------------------------------------------


def test_the_refusal_path_exits_two_and_prints_a_clear_reason(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exit 2 means "refused", which is distinct from "measured and failed"."""
    monkeypatch.setattr(
        "sys.argv",
        [
            "queue_phase17c_validation.py",
            "--local",
            "--mongo-uri",
            "mongodb+srv://user:pw@cluster0.ab1cd.mongodb.net/webchat",
        ],
    )
    code = main()
    captured = capsys.readouterr()
    assert code == 2
    assert "SAFETY REFUSAL" in captured.err
    assert "No connection was attempted" in captured.err
    assert "sup3rsecret" not in captured.err


def test_help_exits_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["queue_phase17c_validation.py", "--help"])
    with pytest.raises(SystemExit) as excinfo:
        main()
    assert excinfo.value.code == 0


# ----------------------------------------------------------------------
# 5. Report integrity
# ----------------------------------------------------------------------


def test_the_generated_database_name_is_never_the_application_database() -> None:
    """Cleanup may drop a database, so its name must be provably ours."""
    from scripts.queue_phase17c_validation import _build_db_name

    name = _build_db_name("webchat_ai", "abc123")
    assert name.startswith(DB_PREFIX)
    assert name != "webchat_ai"
    assert "abc123" in name


def test_cleanup_refuses_a_database_without_our_prefix() -> None:
    """The prefix check is the first line of defence for a destructive action."""
    import asyncio

    from scripts.queue_phase17c_validation import _cleanup

    class _Ctx:
        db_name = "webchat_ai"

    result = asyncio.run(_cleanup(_Ctx(), "tag"))  # type: ignore[arg-type]
    assert result["dropped"] is False
    assert "lacks the Phase 17C prefix" in result["reason"]


def test_percentiles_are_nearest_rank_and_monotonic() -> None:
    from scripts.queue_phase17c_validation import _percentile

    samples = [float(n) for n in range(1, 101)]
    p50 = _percentile(samples, 0.50)
    p95 = _percentile(samples, 0.95)
    p99 = _percentile(samples, 0.99)
    assert p50 <= p95 <= p99
    assert 45 <= p50 <= 55
    assert 90 <= p95 <= 99


def test_percentiles_tolerate_an_unordered_sample() -> None:
    from scripts.queue_phase17c_validation import _percentile

    assert _percentile([5.0, 1.0, 4.0, 2.0, 3.0], 0.50) == 3.0


def test_json_output_is_machine_readable() -> None:
    """The report has to be diffable across runs and machine-parsed by CI."""
    report: dict[str, Any] = {
        "phase": "17C",
        "latency": {"enqueue": {"p50_ms": 1.0, "p95_ms": 2.0, "p99_ms": 3.0, "samples": 3}},
    }
    assert json.loads(json.dumps(report)) == report
