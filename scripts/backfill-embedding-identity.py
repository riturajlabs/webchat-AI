#!/usr/bin/env python3
"""Backfill embedding-identity metadata on legacy `knowledge_chunks`.

Chunks indexed before the embedding-identity contract (ADR-009,
`backend/core/embedding_identity.py`) have no `embedding_provider`,
`embedding_model`, `embedding_dimensions`, or `embedding_version` fields.
The retrieval pipeline filters `$vectorSearch` on those fields, so legacy
chunks become invisible to search until they carry the identity of the
embedding space they were actually produced in.

Safety: a chunk is only stamped when its vector length equals the configured
`EMBEDDING_DIMENSIONS`; anything else is left untouched and reported for
manual re-indexing. No vectors are modified, no documents are deleted.

Usage:
    python scripts/backfill-embedding-identity.py [--dry-run] [--uri ...] [--db ...]

Defaults:
    --uri   $MONGODB_URI or mongodb://localhost:27017
    --db    $MONGODB_DB  or webchat_ai
Identity values come from settings (EMBEDDING_PROVIDER_ORDER /
EMBEDDING_MODEL / EMBEDDING_DIMENSIONS / EMBEDDING_VERSION) via .env.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pymongo

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

from backend.core.config import get_settings  # noqa: E402


def _load_env(env_file: Path) -> None:
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def backfill(
    uri: str,
    db_name: str,
    *,
    dry_run: bool,
) -> int:
    settings = get_settings()
    provider = (
    settings.embedding_provider_order[0]
    if settings.embedding_provider_order
    else "gemini"
    )   
    model = settings.embedding_model
    dimensions = settings.embedding_dimensions
    version = settings.embedding_version

    print(f"target identity: provider={provider} model={model} dims={dimensions} version={version}")

    client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=15000)
    collection = client[db_name]["knowledge_chunks"]

    query = {"embedding_provider": {"$exists": False}}
    total = 0
    stamped = 0
    skipped = 0
    for chunk in collection.find(query, {"embedding": 1}):
        total += 1
        embedding = chunk.get("embedding")
        actual_dims = len(embedding) if isinstance(embedding, list) else None
        if actual_dims != dimensions:
            skipped += 1
            print(
                f"  SKIP _id={chunk['_id']} dims={actual_dims} (expected {dimensions}) "
                "- re-index this chunk manually"
            )
            continue
        stamped += 1
        if not dry_run:
            collection.update_one(
                {"_id": chunk["_id"]},
                {
                    "$set": {
                        "embedding_provider": provider,
                        "embedding_model": model,
                        "embedding_dimensions": dimensions,
                        "embedding_version": version,
                    }
                },
            )

    verb = "would be stamped" if dry_run else "stamped"
    print(
        f"\n{total} legacy chunk(s) inspected, {stamped} {verb}, "
        f"{skipped} skipped (dimension mismatch) "
        f"({'DRY RUN — no writes' if dry_run else 'writes applied'})."
    )
    client.close()
    return 0 if skipped == 0 else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uri", default=None, help="defaults to $MONGODB_URI or mongodb://localhost:27017")
    parser.add_argument("--db", default=None, help="defaults to $MONGODB_DB or webchat_ai")
    parser.add_argument(
        "--env-file",
        default=str(_project_root / ".env.production"),
        help="env file to load for identity settings (default: .env.production)",
    )
    parser.add_argument("--dry-run", action="store_true", help="report changes without writing")
    args = parser.parse_args()
    _load_env(Path(args.env_file))
    uri = args.uri or os.environ.get("MONGODB_URI", "mongodb://localhost:27017")
    db_name = args.db or os.environ.get("MONGODB_DB", "webchat_ai")
    try:
        return backfill(uri, db_name, dry_run=args.dry_run)
    except pymongo.errors.ServerSelectionTimeoutError as error:
        print(f"backfill-embedding-identity: MongoDB unreachable: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
