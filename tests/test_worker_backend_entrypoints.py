"""Backend-aware worker entrypoints and health probe (Phase 18A).

``python -m backend.workers`` picks its consumer from ``QUEUE_BACKEND``, and the
container healthcheck must probe the broker that consumer actually uses. Both
are pure wiring, so they are tested here without Redis, MongoDB or ARQ running:

* ARQ (the production default) still starts the ARQ worker, unchanged.
* ``QUEUE_BACKEND=mongo`` starts the Mongo consumer; an unknown value refuses to
  start anything at all rather than becoming a silent no-op.
* The health probe pings Redis under ARQ and the queue store under Mongo - and
  under Mongo it must not depend on Redis at all, or a deployment that retired
  ARQ would report permanently unhealthy.
"""

from __future__ import annotations

import asyncio
import pathlib
from types import SimpleNamespace
from typing import Any

import pytest
from backend.core.config import Settings
from backend.core.database import MongoDB
from backend.queue.mongo_adapter import MongoQueueAdapter
from backend.workers import __main__ as entrypoint
from backend.workers import health as health_module

_TENANT = "tenant-a"


def _arq_settings() -> Settings:
    return Settings()


def _mongo_settings() -> Settings:
    return Settings(
        queue_backend="mongo",
        mongo_queue_enabled=True,
        mongo_queue_database="webchat_ai_queue_health",
    )


# ----------------------------------------------------------------------
# python -m backend.workers
# ----------------------------------------------------------------------


def test_the_default_entrypoint_starts_the_arq_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    import arq.cli

    seen: dict[str, Any] = {}

    def _cli(args: list[str], prog_name: str) -> int:
        seen["args"] = args
        seen["prog_name"] = prog_name
        return 0

    monkeypatch.setattr(entrypoint, "get_settings", _arq_settings)
    monkeypatch.setattr(arq.cli, "cli", _cli)

    with pytest.raises(SystemExit) as excinfo:
        entrypoint.main()

    assert excinfo.value.code == 0
    assert seen == {
        "args": ["backend.workers.app.WorkerSettings"],
        "prog_name": "python -m backend.workers",
    }


def test_the_mongo_backend_starts_the_mongo_consumer(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.workers import mongo as mongo_worker

    started: list[bool] = []
    monkeypatch.setattr(entrypoint, "get_settings", _mongo_settings)
    monkeypatch.setattr(mongo_worker, "run_worker", lambda: started.append(True) or 0)

    with pytest.raises(SystemExit) as excinfo:
        entrypoint.main()

    assert excinfo.value.code == 0
    assert started == [True]


def test_the_backend_name_is_matched_case_insensitively(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``Settings`` validates the name case-insensitively, so the entrypoint does.

    Without the normalization a ``MONGO`` value would validate as an opt-in and
    then start the ARQ worker - the same silent mismatch the factory had.
    """
    from backend.workers import mongo as mongo_worker

    started: list[bool] = []
    monkeypatch.setattr(
        entrypoint,
        "get_settings",
        lambda: _mongo_settings().model_copy(update={"queue_backend": " MONGO "}),
    )
    monkeypatch.setattr(mongo_worker, "run_worker", lambda: started.append(True) or 0)

    with pytest.raises(SystemExit):
        entrypoint.main()
    assert started == [True]


def test_an_unknown_backend_refuses_to_start_a_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    """A value ``Settings`` would have rejected must not start the wrong worker."""
    monkeypatch.setattr(entrypoint, "get_settings", lambda: SimpleNamespace(queue_backend="kafka"))

    with pytest.raises(SystemExit, match="Unknown QUEUE_BACKEND"):
        entrypoint.main()


# ----------------------------------------------------------------------
# python -m backend.workers.health
# ----------------------------------------------------------------------


class _PingableQueue(MongoQueueAdapter):
    """A real adapter shape whose ``ping`` is scripted (no connection opened)."""

    def __init__(self, result: bool) -> None:
        self._result = result
        self.pings = 0

    async def ping(self) -> bool:
        self.pings += 1
        return self._result


def _recorder(sink: list[str], name: str, result: Any) -> Any:
    async def _record() -> Any:
        sink.append(name)
        return result

    return _record


def test_health_pings_redis_under_the_arq_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    import backend.core.redis as redis_module

    calls: list[str] = []
    monkeypatch.setattr(health_module, "get_settings", _arq_settings)
    monkeypatch.setattr(redis_module, "ping_redis", _recorder(calls, "redis", True))

    assert asyncio.run(health_module.check()) is True
    assert calls == ["redis"]


def test_health_reports_unhealthy_when_redis_is_down(monkeypatch: pytest.MonkeyPatch) -> None:
    import backend.core.redis as redis_module

    monkeypatch.setattr(health_module, "get_settings", _arq_settings)
    monkeypatch.setattr(redis_module, "ping_redis", _recorder([], "redis", False))
    assert asyncio.run(health_module.check()) is False


def test_health_pings_the_queue_under_mongo_and_never_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cutover case: ARQ may be gone, so Redis must not be part of health."""
    import backend.core.redis as redis_module

    adapter = _PingableQueue(True)
    closed: list[bool] = []

    async def _explode() -> bool:
        raise AssertionError("Mongo mode must not probe Redis")

    async def _close() -> None:
        closed.append(True)

    monkeypatch.setattr(health_module, "get_settings", _mongo_settings)
    monkeypatch.setattr("backend.queue.factory.get_queue", lambda: adapter)
    monkeypatch.setattr(redis_module, "ping_redis", _explode)
    monkeypatch.setattr(MongoDB, "close", _close)

    assert asyncio.run(health_module.check()) is True
    assert adapter.pings == 1
    # The probe opens the shared client, so it must give it back.
    assert closed == [True]


def test_health_reports_unhealthy_when_the_queue_is_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _close() -> None:
        return None

    monkeypatch.setattr(health_module, "get_settings", _mongo_settings)
    monkeypatch.setattr("backend.queue.factory.get_queue", lambda: _PingableQueue(False))
    monkeypatch.setattr(MongoDB, "close", _close)
    assert asyncio.run(health_module.check()) is False


def test_health_refuses_a_backend_that_is_not_a_mongo_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Configured as mongo but handed another adapter: unhealthy, not a pass."""
    from backend.queue.arq_adapter import ArqQueueAdapter

    async def _close() -> None:
        return None

    monkeypatch.setattr(health_module, "get_settings", _mongo_settings)
    monkeypatch.setattr(
        "backend.queue.factory.get_queue", lambda: ArqQueueAdapter("redis://127.0.0.1:1/0")
    )
    monkeypatch.setattr(MongoDB, "close", _close)
    assert asyncio.run(health_module.check()) is False


def test_health_exit_codes_follow_the_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _healthy() -> bool:
        return True

    async def _unhealthy() -> bool:
        return False

    async def _explodes() -> bool:
        raise RuntimeError("probe error")

    monkeypatch.setattr(health_module, "check", _healthy)
    assert health_module.main() == 0
    monkeypatch.setattr(health_module, "check", _unhealthy)
    assert health_module.main() == 1
    monkeypatch.setattr(health_module, "check", _explodes)
    assert health_module.main() == 1


def test_the_container_healthcheck_runs_the_backend_aware_probe() -> None:
    """A Redis-only probe would fail a Mongo deployment forever."""
    dockerfile = pathlib.Path("docker/Dockerfile.worker").read_text()
    assert "python -m backend.workers.health" in dockerfile
    assert "asyncio.run(r.from_url" not in dockerfile
    assert 'CMD ["python", "-m", "backend.workers"]' in dockerfile
