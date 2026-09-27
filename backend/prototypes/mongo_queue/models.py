"""Prototype queue data model (Phase 15).

Field set follows the design in the Phase 15 brief. ``execution_version`` is
the fencing token: every claim increments it and completion must match it, so
a worker whose lease expired (and whose execution a newer worker reclaimed)
can never complete or fail that execution.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.prototypes.mongo_queue.ids import new_job_id, utcnow

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_RETRY_PENDING = "retry_pending"
STATUS_COMPLETED = "completed"
STATUS_DEAD = "dead"

# Terminal states: nothing can claim them again.
TERMINAL_STATUSES = frozenset({STATUS_COMPLETED, STATUS_DEAD})
# States a claim filter may pick up.
CLAIMABLE_PENDING = frozenset({STATUS_PENDING, STATUS_RETRY_PENDING})

# Status values are plain strings; `JobStatus` documents the intent.
JobStatus = str


def status_is_terminal(status: str) -> bool:
    return status in TERMINAL_STATUSES


class Job(BaseModel):
    """One row of the ``worker_jobs_prototype`` collection."""

    model_config = ConfigDict(extra="allow", frozen=True)

    id: str = Field(default_factory=new_job_id)
    function: str
    payload: dict[str, Any] = Field(default_factory=dict)
    tenant_id: str = ""
    status: JobStatus = STATUS_PENDING
    run_at: datetime = Field(default_factory=utcnow)
    attempts: int = 0
    max_tries: int = 3
    execution_version: int = 0
    lease_expires_at: datetime | None = None
    locked_by: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    last_error: str | None = None
    result: Any = None
    dedup_key: str | None = None

    @classmethod
    def from_doc(cls, doc: dict[str, Any] | None) -> Job | None:
        if doc is None:
            return None
        return cls(id=str(doc.pop("_id")), **doc)

    def to_doc(self) -> dict[str, Any]:
        doc = self.model_dump(exclude={"id"})
        doc["_id"] = self.id
        return doc

    def to_out(self) -> dict[str, Any]:
        """Non-exhaustive display shape (result excluded where huge)."""
        return {
            "id": self.id,
            "function": self.function,
            "status": self.status,
            "attempts": self.attempts,
            "max_tries": self.max_tries,
            "execution_version": self.execution_version,
            "run_at": self.run_at,
            "lease_expires_at": self.lease_expires_at,
            "locked_by": self.locked_by,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "tenant_id": self.tenant_id,
        }
