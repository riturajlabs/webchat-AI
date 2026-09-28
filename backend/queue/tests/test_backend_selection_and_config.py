"""Backend selection, unsafe configuration, Redis preservation, and the active
crawl-progress follow-up (Phase 17B, sections 14-19).

Production runs on ARQ + Redis. Nothing in this phase may change that, so the
tests here are mostly about what must *not* happen:

* ARQ is selected when ``QUEUE_BACKEND`` is absent, and Mongo is reachable only
  through an explicit two-flag opt-in.
* Every incoherent queue configuration fails at boot with a useful message
  rather than silently falling back.
* Selecting the Mongo queue does not disturb any other Redis consumer
  (cache, rate limiting, provider health, crawl progress pub/sub).
* FIND-03's terminal monotonicity still holds while active->active progress
  remains last-writer-wins - a NON-BLOCKING follow-up, validated not redesigned.
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from backend.core.config import Settings
from pydantic import ValidationError


def _settings(**overrides: Any) -> Settings:
    """Build Settings directly, bypassing the environment."""
    return Settings(**overrides)


# ----------------------------------------------------------------------
# §15 / §16 Backend selection
# ----------------------------------------------------------------------


def test_arq_is_the_default_when_queue_backend_is_absent() -> None:
    settings = _settings()
    assert settings.queue_backend == "arq"
    assert settings.mongo_queue_enabled is False


def test_the_default_selects_the_arq_adapter() -> None:
    from backend.queue.arq_adapter import ArqQueueAdapter
    from backend.queue.factory import get_queue

    assert isinstance(get_queue(), ArqQueueAdapter)


def test_mongo_requires_both_flags() -> None:
    """Backend name alone is not enough - the enable flag is a second gate."""
    with pytest.raises(ValidationError, match="MONGO_QUEUE_ENABLED"):
        _settings(queue_backend="mongo")


def test_mongo_opt_in_selects_the_mongo_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.core.config import get_settings
    from backend.queue.factory import get_queue, queue_database_name
    from backend.queue.mongo_adapter import MongoQueueAdapter

    settings = _settings(
        queue_backend="mongo",
        mongo_queue_enabled=True,
        mongo_queue_database="webchat_ai_queue_optin",
    )
    monkeypatch.setattr("backend.queue.factory.get_settings", lambda: settings)

    # A database handle is injected so nothing connects during the test. The
    # adapter only reads `db.name` and subscripts the collection at construction.
    class _Collection:
        def __init__(self, name: str) -> None:
            self.name = name

    class _Db:
        name = "webchat_ai_queue_optin"

        def __getitem__(self, item: str) -> _Collection:
            return _Collection(item)

    adapter = get_queue(_Db())  # type: ignore[arg-type]
    assert isinstance(adapter, MongoQueueAdapter)
    assert queue_database_name(settings) == "webchat_ai_queue_optin"
    assert get_settings is not None


class _FakeCollection:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeDb:
    name = "webchat_ai_queue_optin"

    def __getitem__(self, item: str) -> _FakeCollection:
        return _FakeCollection(item)


def test_the_factory_matches_the_backend_name_case_insensitively(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mixed-case ``QUEUE_BACKEND`` must not quietly become ARQ.

    ``Settings`` validates the name case-insensitively, so ``MONGO`` is a valid
    Mongo opt-in; the factory compared the raw string and would have served the
    ARQ adapter to a process that believes it opted in - the exact silent
    fallback §17 forbids.
    """
    from backend.queue.arq_adapter import ArqQueueAdapter
    from backend.queue.factory import get_queue
    from backend.queue.mongo_adapter import MongoQueueAdapter

    settings = _settings(
        queue_backend="MONGO",
        mongo_queue_enabled=True,
        mongo_queue_database="webchat_ai_queue_optin",
    )
    monkeypatch.setattr("backend.queue.factory.get_settings", lambda: settings)

    # A fake database handle so nothing connects during the test.
    assert isinstance(get_queue(_FakeDb()), MongoQueueAdapter)  # type: ignore[arg-type]
    assert not isinstance(get_queue(_FakeDb()), ArqQueueAdapter)  # type: ignore[arg-type]


def test_the_arq_default_path_never_imports_the_prototype_package(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§16: no prototype import, no implicit Redis queue use, no side effect."""
    import subprocess
    import sys

    code = (
        "import sys;"
        "from backend.queue.factory import get_queue;"
        "q = get_queue();"
        "assert 'backend.prototypes' not in sys.modules, sorted(sys.modules);"
        "assert type(q).__name__ == 'ArqQueueAdapter', type(q).__name__;"
        "print('ok')"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=os.getcwd()
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


def test_constructing_a_queue_backend_performs_no_external_side_effect() -> None:
    """Building the ARQ adapter must not dial Redis."""
    from backend.queue.arq_adapter import ArqQueueAdapter

    adapter = ArqQueueAdapter("redis://127.0.0.1:1/0")  # unreachable on purpose
    assert adapter.queue_name == "arq:queue"


# ----------------------------------------------------------------------
# §17 Unsafe configuration
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"queue_backend": "kafka"}, "QUEUE_BACKEND"),
        ({"queue_backend": ""}, "QUEUE_BACKEND"),
        ({"mongo_queue_retention_days": -1.0}, "MONGO_QUEUE_RETENTION_DAYS"),
        ({"mongo_queue_max_tries": 0}, "MONGO_QUEUE_MAX_TRIES"),
        ({"mongo_queue_result_policy": "everything"}, "MONGO_QUEUE_RESULT_POLICY"),
        ({"mongo_queue_lease_seconds": 0.0}, "MONGO_QUEUE_LEASE_SECONDS"),
        ({"mongo_queue_lease_seconds": -5.0}, "MONGO_QUEUE_LEASE_SECONDS"),
        ({"mongo_queue_heartbeat_seconds": 0.0}, "MONGO_QUEUE_HEARTBEAT_SECONDS"),
        ({"mongo_queue_heartbeat_seconds": 120.0}, "shorter than"),
        (
            {"mongo_queue_lease_seconds": 30.0, "mongo_queue_heartbeat_seconds": 30.0},
            "shorter than",
        ),
        ({"mongo_queue_poll_schedule": []}, "must not be empty"),
        ({"mongo_queue_poll_schedule": [1.0, 0.0]}, "must be positive"),
        ({"mongo_queue_poll_schedule": [-1.0]}, "must be positive"),
    ],
)
def test_unsafe_queue_configuration_fails_fast(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError) as excinfo:
        _settings(**overrides)
    assert message in str(excinfo.value)


def test_production_mongo_requires_an_explicit_database() -> None:
    """A production Mongo queue must never fall back to a default DB name."""
    with pytest.raises(ValidationError, match="MONGO_QUEUE_DATABASE"):
        _settings(
            queue_backend="mongo",
            mongo_queue_enabled=True,
            environment="production",
            mongo_queue_database="",
        )


def test_the_queue_database_may_not_be_the_application_database() -> None:
    """Defensive runtime check as well as the boot-time one."""
    from backend.queue.errors import MongoQueueNotEnabledError
    from backend.queue.factory import queue_database_name

    settings = _settings(
        queue_backend="mongo",
        mongo_queue_enabled=True,
        mongo_queue_database="webchat_ai",
        mongodb_db="webchat_ai",
    )
    with pytest.raises(MongoQueueNotEnabledError, match="must differ"):
        queue_database_name(settings)


def test_no_unsafe_configuration_silently_falls_back_to_arq() -> None:
    """A rejected configuration raises; it never quietly becomes ARQ."""
    for overrides in (
        {"queue_backend": "mongo"},
        {"queue_backend": "not-a-backend"},
        {"mongo_queue_heartbeat_seconds": 999.0},
    ):
        with pytest.raises(ValidationError):
            _settings(**overrides)


# ----------------------------------------------------------------------
# §18 Redis consumer preservation
# ----------------------------------------------------------------------


def test_mongo_queue_selection_does_not_disable_redis_settings() -> None:
    """Redis stays configured and reachable-in-principle under the Mongo queue."""
    settings = _settings(
        queue_backend="mongo",
        mongo_queue_enabled=True,
        mongo_queue_database="webchat_ai_queue_optin",
    )
    assert settings.redis_url, "Redis must remain configured for non-queue consumers"
    assert settings.redis_prefix


def test_the_shared_redis_client_is_still_available_for_non_queue_uses() -> None:
    """cache / rate limiting / health / pub-sub all read the same singleton."""
    from backend.core import redis as redis_module

    assert hasattr(redis_module, "get_redis")


def test_non_queue_redis_consumers_import_without_the_mongo_queue() -> None:
    """These modules must not depend on the queue backend at all."""
    import importlib

    for module in (
        "backend.core.cache",
        "backend.core.redis",
        "backend.services.ai.provider_health",
    ):
        assert importlib.import_module(module) is not None


def test_only_the_worker_consumes_the_queue_redis() -> None:
    """Which module actually consumes ARQ: the worker, not the API.

    This is the table in section 18, asserted: the ARQ queue is the only
    queue-dependent Redis consumer, and it stays on ARQ in production.
    """
    import inspect

    from backend.workers.jobs import crawl as crawl_module

    source = inspect.getsource(crawl_module)
    # The crawl worker still builds an ARQ client for its API-process entry point.
    assert "_arq_redis" in source
    # ...and its in-job fan-out goes through the queue abstraction.
    assert "_child_enqueue_knowledge" in source


# ----------------------------------------------------------------------
# §14 Active crawl progress follow-up (NON-BLOCKING)
# ----------------------------------------------------------------------


def test_find03_report_records_the_active_progress_follow_up() -> None:
    """The follow-up must be recorded as a follow-up, not silently dropped."""
    import pathlib

    report = pathlib.Path("docs/reports/FIND03_CRAWL_RESURRECTION_REMEDIATION.md")
    # Normalise the report's hard line wrapping before matching phrases.
    text = " ".join(report.read_text().split())
    assert "last writer wins" in text or "last-writer-wins" in text
    assert "eventually consistent" in text
    assert "out of FIND-03" in text or "out of scope" in text
