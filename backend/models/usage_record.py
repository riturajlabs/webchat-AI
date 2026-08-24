"""Daily tenant usage rollup model (Phase 6, ADR-005 §5.5).

One `usage_records` document per (tenant, website, day) aggregating the
counters that Phase 9 analytics and future billing read: chats, messages,
input/output tokens, embeddings created, vector queries and crawled pages.
The unique (tenant_id, website_id, date) index makes the `$inc` upsert
idempotent; `updated_at` backs the 3-year TTL (ADR-005 §5.7).
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from backend.core.security import new_id, utcnow

USAGE_SCHEMA_VERSION = 1

USAGE_COUNTER_CHATS = "chats"
USAGE_COUNTER_MESSAGES = "messages"
USAGE_COUNTER_INPUT_TOKENS = "input_tokens"
USAGE_COUNTER_OUTPUT_TOKENS = "output_tokens"
USAGE_COUNTER_ESTIMATED_COST_MICROS = "estimated_cost_micros"
USAGE_COUNTER_EMBEDDINGS_CREATED = "embeddings_created"
USAGE_COUNTER_VECTOR_QUERIES = "vector_queries"
USAGE_COUNTER_CRAWL_PAGES = "crawl_pages"

USAGE_COUNTERS = frozenset(
    {
        USAGE_COUNTER_CHATS,
        USAGE_COUNTER_MESSAGES,
        USAGE_COUNTER_INPUT_TOKENS,
        USAGE_COUNTER_OUTPUT_TOKENS,
        USAGE_COUNTER_ESTIMATED_COST_MICROS,
        USAGE_COUNTER_EMBEDDINGS_CREATED,
        USAGE_COUNTER_VECTOR_QUERIES,
        USAGE_COUNTER_CRAWL_PAGES,
    }
)


def usage_date_key(when: datetime | None = None) -> str:
    """Return the UTC day key "YYYY-MM-DD" for a usage record."""
    now = when if when is not None else utcnow()
    return now.strftime("%Y-%m-%d")


class UsageRecord(BaseModel):
    """Daily aggregate counters for one (tenant, website) pair."""

    model_config = ConfigDict(extra="allow")

    id: str
    tenant_id: str
    website_id: str
    date: str
    counters: dict[str, int]
    created_at: datetime
    updated_at: datetime
    schema_version: int = USAGE_SCHEMA_VERSION

    @classmethod
    def new(
        cls,
        *,
        tenant_id: str,
        website_id: str,
        date: str,
    ) -> "UsageRecord":
        now = utcnow()
        return cls(
            id=new_id(),
            tenant_id=tenant_id,
            website_id=website_id,
            date=date,
            counters={counter: 0 for counter in USAGE_COUNTERS},
            created_at=now,
            updated_at=now,
        )

    @classmethod
    def from_doc(cls, doc: dict[str, Any]) -> "UsageRecord":
        doc = dict(doc)
        doc["id"] = str(doc.pop("_id"))
        return cls(**doc)

    def to_doc(self) -> dict[str, Any]:
        doc = self.model_dump(exclude={"id"})
        doc["_id"] = self.id
        return doc


__all__ = [
    "USAGE_COUNTERS",
    "USAGE_COUNTER_CHATS",
    "USAGE_COUNTER_EMBEDDINGS_CREATED",
    "USAGE_COUNTER_CRAWL_PAGES",
    "USAGE_COUNTER_ESTIMATED_COST_MICROS",
    "USAGE_COUNTER_INPUT_TOKENS",
    "USAGE_COUNTER_MESSAGES",
    "USAGE_COUNTER_OUTPUT_TOKENS",
    "USAGE_COUNTER_VECTOR_QUERIES",
    "USAGE_SCHEMA_VERSION",
    "UsageRecord",
    "usage_date_key",
]
