"""Identifiers and clock helpers for the production Mongo queue.

Deliberately dependency-free: the queue must never reach into application
settings to decide what time it is or how a worker is named. Mirrors the
validated ``backend/prototypes/mongo_queue/ids.py`` semantics.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta


def utcnow() -> datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(UTC)


def new_job_id() -> str:
    """Return a new opaque job identifier (uuid hex)."""
    return uuid.uuid4().hex


def new_worker_id(prefix: str = "worker") -> str:
    """Return a new worker identifier, e.g. ``worker-1a2b3c4d5e6f``."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def add_seconds(value: datetime, seconds: float) -> datetime:
    """Return ``value`` shifted forward by ``seconds`` (clamped >= epoch)."""
    return value + timedelta(seconds=max(0, seconds))
