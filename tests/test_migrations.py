"""Tests for the deployment-time migration entrypoint (backend.migrations)."""

import pytest
from backend.migrations import _run_migrations
from backend.migrations import main as migration_main


class _AsyncStub:
    """Coroutine stub for monkeypatched async methods.

    The suite runs under pytest-asyncio ``asyncio_mode=auto``; these stubs
    never touch the real MongoDB (conftest disables it).
    """

    def __init__(self, value: object) -> None:
        self._value = value

    async def __call__(self, *args: object, **kwargs: object) -> object:
        return self._value


async def _run_main() -> int:
    return await migration_main()


async def test_migrations_ok_calls_init_indexes(monkeypatch: pytest.MonkeyPatch) -> None:
    """A reachable database applies init_indexes and exits 0."""
    calls: list[str] = []

    async def fake_ping() -> bool:
        calls.append("ping")
        return True

    async def fake_init_indexes() -> None:
        calls.append("init_indexes")

    monkeypatch.setattr("backend.core.database.MongoDB.ping", fake_ping)
    monkeypatch.setattr("backend.core.database.MongoDB.init_indexes", fake_init_indexes)
    monkeypatch.setattr("backend.core.database.MongoDB.close", _AsyncStub(None))

    code = await _run_main()
    assert code == 0
    assert calls == ["ping", "init_indexes"]


async def test_migrations_fails_fast_when_database_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exit 1 without calling init_indexes when MongoDB is unreachable."""
    called = False

    async def fake_ping() -> bool:
        return False

    async def fail_init_indexes() -> None:
        nonlocal called
        called = True

    monkeypatch.setattr("backend.core.database.MongoDB.ping", fake_ping)
    monkeypatch.setattr("backend.core.database.MongoDB.init_indexes", fail_init_indexes)
    monkeypatch.setattr("backend.core.database.MongoDB.close", _AsyncStub(None))

    code = await _run_main()
    assert code == 1
    assert called is False


async def test_migrations_returns_1_when_index_creation_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failure inside init_indexes surfaces as exit code 1."""

    async def fake_ping() -> bool:
        return True

    async def raise_init_indexes() -> None:
        raise RuntimeError("index build failed")

    monkeypatch.setattr("backend.core.database.MongoDB.ping", fake_ping)
    monkeypatch.setattr("backend.core.database.MongoDB.init_indexes", raise_init_indexes)
    monkeypatch.setattr("backend.core.database.MongoDB.close", _AsyncStub(None))

    code = await _run_main()
    assert code == 1


async def test_migrations_success_is_idempotent_on_rerun(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Re-running a successful migration stays a no-op (exit 0).

    ``MongoDB.init_indexes`` builds indexes with fixed spec+name, which
    ``create_index`` treats as a no-op when the index already exists, so a
    CI/CD migration retry is always safe.
    """
    from backend.core.database import MongoDB

    ping_calls = 0

    async def fake_ping() -> bool:
        nonlocal ping_calls
        ping_calls += 1
        return True

    async def fake_init_indexes() -> None:
        return None

    monkeypatch.setattr(MongoDB, "ping", fake_ping)
    monkeypatch.setattr(MongoDB, "init_indexes", fake_init_indexes)
    monkeypatch.setattr(MongoDB, "close", _AsyncStub(None))

    first = await _run_migrations()
    second = await _run_migrations()
    assert first == 0 and second == 0
    assert ping_calls == 2
