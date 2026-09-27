"""Backend selection + safety-gating tests (Phase 17A §28.20-24)."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

import pytest
from backend.core.config import Settings
from backend.queue.arq_adapter import ArqQueueAdapter
from backend.queue.errors import MongoQueueNotEnabledError
from backend.queue.factory import get_queue, queue_database_name
from backend.queue.mongo_adapter import MongoQueueAdapter
from motor.motor_asyncio import AsyncIOMotorClient


def _prod(**overrides: Any) -> dict[str, Any]:
    """A valid production config (mypy-clean **kwargs for pydantic Settings)."""
    base: dict[str, Any] = {
        "environment": "production",
        "jwt_secret": "a" * 32,
        "gemini_api_key": "test-key",
        "enable_docs": False,
        "widget_script_url": "https://cdn.example.com/webchat-widget.iife.min.js",
        "payment_provider": "stripe",
        "stripe_secret_key": "sk_test_" + "a" * 24,
        "stripe_webhook_secret": "whsec_" + "b" * 24,
        "cors_origins": ["https://app.example.com"],
        "allowed_hosts": ["app.example.com"],
        "mongo_username": "test-user",
        "mongo_password": "test-pass",
        "redis_password": "test-pass",
    }
    base.update(overrides)
    return base


def _stub_settings(**kwargs: Any) -> SimpleNamespace:
    """A settings-shaped double so factory branches can be driven directly."""
    base: dict[str, Any] = {
        "queue_backend": "arq",
        "mongo_queue_enabled": False,
        "mongo_queue_database": "",
        "mongo_queue_collection": "worker_jobs",
        "mongo_queue_lease_seconds": 120.0,
        "mongo_queue_heartbeat_seconds": 30.0,
        "mongo_queue_max_tries": 3,
        "mongo_queue_backoff_seconds": [5.0, 30.0, 180.0],
        "mongo_queue_poll_schedule": [1.0, 2.0, 5.0, 10.0, 30.0],
        "mongo_queue_max_result_bytes": 16_384,
        "mongo_queue_retention_days": 0.0,
        "mongo_queue_result_policy": "status",
        "mongodb_db": "webchat_ai",
        "redis_url": "redis://localhost:6379",
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_default_backend_is_arq(monkeypatch: pytest.MonkeyPatch) -> None:
    import backend.queue.factory as factory

    monkeypatch.setattr(factory, "get_settings", lambda: _stub_settings())
    q = get_queue()
    assert isinstance(q, ArqQueueAdapter)


def test_mongo_backend_requires_explicit_enable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import backend.queue.factory as factory

    monkeypatch.setattr(
        factory,
        "get_settings",
        lambda: _stub_settings(queue_backend="mongo", mongo_queue_enabled=False),
    )
    with pytest.raises(MongoQueueNotEnabledError):
        get_queue()


def test_mongo_backend_builds_adapter_over_given_db(
    monkeypatch: pytest.MonkeyPatch, mongo_client: AsyncIOMotorClient[Any]
) -> None:
    import backend.queue.factory as factory

    monkeypatch.setattr(
        factory,
        "get_settings",
        lambda: _stub_settings(
            queue_backend="mongo",
            mongo_queue_enabled=True,
            mongo_queue_database="webchat_ai_queue_test_selection",
        ),
    )
    db = mongo_client["webchat_ai_queue_test_selection"]
    q = get_queue(db=db)
    assert isinstance(q, MongoQueueAdapter)
    assert q.queue_name == "webchat_ai_queue_test_selection.worker_jobs"
    assert callable(getattr(q, "ensure_indexes", None))


def test_mongo_backend_refuses_the_application_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Queue rows must never sit beside tenant data in the app database."""
    import backend.queue.factory as factory

    monkeypatch.setattr(
        factory,
        "get_settings",
        lambda: _stub_settings(
            queue_backend="mongo",
            mongo_queue_enabled=True,
            mongo_queue_database="webchat_ai",
            mongodb_db="webchat_ai",
        ),
    )
    with pytest.raises(MongoQueueNotEnabledError):
        get_queue()


def test_result_policy_is_passed_into_the_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    import backend.queue.factory as factory

    monkeypatch.setattr(
        factory,
        "get_settings",
        lambda: _stub_settings(
            queue_backend="mongo",
            mongo_queue_enabled=True,
            mongo_queue_database="webchat_ai_queue",
            mongo_queue_result_policy="full",
        ),
    )
    assert factory.build_mongo_config_kwargs()["result_policy"] == "full"


def test_default_result_policy_stores_no_result_body() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.mongo_queue_result_policy == "status"


def test_invalid_result_policy_fails_fast() -> None:
    with pytest.raises(ValueError, match="MONGO_QUEUE_RESULT_POLICY"):
        Settings(_env_file=None, mongo_queue_result_policy="everything")  # type: ignore[call-arg]


def test_settings_gate_mongo_without_enable_fails_fast() -> None:
    with pytest.raises(ValueError, match="MONGO_QUEUE_ENABLED"):
        Settings(_env_file=None, queue_backend="mongo")  # type: ignore[call-arg]


def test_production_settings_require_explicit_mongo_database() -> None:
    with pytest.raises(ValueError, match="MONGO_QUEUE_DATABASE"):
        Settings(**_prod(queue_backend="mongo", mongo_queue_enabled=True))


def test_production_arq_never_requires_mongo_database() -> None:
    settings = Settings(**_prod())
    assert settings.queue_backend == "arq"
    assert settings.mongo_queue_enabled is False


def test_queue_database_name_resolution() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert queue_database_name(settings) == "webchat_ai_queue"


def test_unknown_backend_setting_fails_fast() -> None:
    with pytest.raises(ValueError, match="QUEUE_BACKEND"):
        Settings(_env_file=None, queue_backend="kafka")  # type: ignore[call-arg]

def test_redis_consumers_remain_intact() -> None:
    """§28.23: Redis stays in use - cache, rate limiting, health, ARQ broker."""
    from backend.core.redis import get_redis  # noqa: F401 - must import cleanly
    from backend.workers.jobs.crawl import _arq_redis as crawl_arq_redis  # noqa: F401
    from backend.workers.jobs.email import _arq_redis as email_arq_redis  # noqa: F401
    from backend.workers.jobs.knowledge import _arq_redis as knowledge_arq_redis  # noqa: F401

    mod = sys.modules["backend.workers.jobs.crawl"]
    assert "ArqRedis" in dir(mod)


def test_mongo_adapter_isolates_its_database(
    mongo_client: AsyncIOMotorClient[Any],
) -> None:
    """§28.24: the adapter targets an explicit queue DB, never the app DB."""
    db = mongo_client["webchat_ai_queue_isolation_probe"]
    q = MongoQueueAdapter(db, collection_name="worker_jobs")
    assert q.queue_name == "webchat_ai_queue_isolation_probe.worker_jobs"
    assert q.queue_name.split(".")[0] != "webchat_ai"


def test_queue_reuses_the_application_mongo_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """No second, unmanaged Mongo client: the app pool and its timeouts are kept.

    A queue that opened its own client would double the connection count
    against the deployment's server-side connection limit and would silently
    opt out of the app's command monitoring and slow-query logging.
    """
    import backend.core.database as database_module
    import backend.queue.factory as factory

    opened: list[str] = []

    class _FakeQueueDb(SimpleNamespace):
        def __getitem__(self, name: str) -> Any:
            return f"collection:{name}"

    sentinel_db = _FakeQueueDb(name="webchat_ai_queue")

    class _FakeMongoDB:
        @classmethod
        def client(cls) -> Any:
            opened.append("client")

            class _Client:
                def __getitem__(self, name: str) -> Any:
                    opened.append(name)
                    return sentinel_db

            return _Client()

    monkeypatch.setattr(
        factory,
        "get_settings",
        lambda: _stub_settings(
            queue_backend="mongo",
            mongo_queue_enabled=True,
            mongo_queue_database="webchat_ai_queue",
        ),
    )
    monkeypatch.setattr(database_module, "MongoDB", _FakeMongoDB)

    queue = factory.get_queue()
    assert opened == ["client", "webchat_ai_queue"]
    assert isinstance(queue, MongoQueueAdapter)
    assert queue.queue_name == "webchat_ai_queue.worker_jobs"


def test_arq_backend_never_imports_the_mongo_store() -> None:
    """The production default path must not pay for the Mongo driver.

    ``MongoQueueAdapter`` is exported lazily for exactly this reason; if it were
    imported eagerly the API process would load motor/pymongo for nothing.
    """
    import subprocess
    import sys

    code = (
        "import sys; import backend.queue as q; "
        "q.ArqQueueAdapter('redis://127.0.0.1:1'); "
        "assert 'backend.queue.mongo_adapter' not in sys.modules, "
        "sorted(m for m in sys.modules if 'queue.mongo' in m)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_heartbeat_must_be_shorter_than_the_lease() -> None:
    """A heartbeat at or beyond the lease can never renew in time."""
    with pytest.raises(ValueError, match="MONGO_QUEUE_HEARTBEAT_SECONDS"):
        Settings(
            _env_file=None,  # type: ignore[call-arg]
            mongo_queue_lease_seconds=30.0,
            mongo_queue_heartbeat_seconds=30.0,
        )


def test_empty_poll_schedule_is_rejected() -> None:
    with pytest.raises(ValueError, match="MONGO_QUEUE_POLL_SCHEDULE"):
        Settings(_env_file=None, mongo_queue_poll_schedule=[])  # type: ignore[call-arg]