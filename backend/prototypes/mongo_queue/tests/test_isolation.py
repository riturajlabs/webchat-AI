"""Isolation guarantees (Phase 15 §34 §29).

Proves the prototype is a parallel experiment: importing it never touches
production ARQ/Redis/Mongo wiring, and no production module imports it.
"""

from __future__ import annotations

import pathlib
import sys

PROTOTYPE_PKG = "backend.prototypes"


async def test_production_workers_do_not_import_prototype() -> None:
    """No production worker/API/service source may reference the prototype."""
    roots = (
        pathlib.Path("backend/workers"),
        pathlib.Path("backend/api"),
        pathlib.Path("backend/services"),
        pathlib.Path("backend/repositories"),
        pathlib.Path("backend/workers/jobs"),
    )
    offenders: list[str] = []
    for root in roots:
        for source in root.rglob("*.py"):
            text = source.read_text()
            if "prototypes" in text or "mongo_queue" in text:
                offenders.append(str(source))
    assert offenders == [], f"production modules import the prototype: {offenders}"


async def test_importing_prototype_does_not_activate_production_stack() -> None:
    """Importing the queue/poller/worker modules pulls in no ARQ worker or
    backend.core wiring (no Redis client, no config env side effects)."""
    before = set(sys.modules)
    import backend.prototypes.mongo_queue.poller  # noqa: F401
    import backend.prototypes.mongo_queue.queue  # noqa: F401
    import backend.prototypes.mongo_queue.worker  # noqa: F401

    after = set(sys.modules)
    loaded = after - before
    forbidden_prefixes = (
        "backend.workers.",
        "backend.core.database",
        "backend.core.redis",
        "arq.worker",
        "redis.asyncio",
    )
    leaked = {m for m in loaded if m.startswith(forbidden_prefixes)}
    assert leaked == set(), f"prototype import activated production stack: {leaked}"
    assert PROTOTYPE_PKG in after


async def test_prototype_namespace_is_isolated_collection() -> None:
    """§5: the prototype DB/collection names are explicit and disjoint from
    production (production uses `webchat_ai`; prototype uses its own)."""
    from backend.prototypes.mongo_queue.config import (
        DEFAULT_COLLECTION,
        DEFAULT_DB_NAME,
    )

    assert DEFAULT_DB_NAME == "webchat_ai_queue_prototype"
    assert DEFAULT_COLLECTION == "worker_jobs_prototype"
    assert DEFAULT_DB_NAME != "webchat_ai"