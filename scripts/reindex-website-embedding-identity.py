#!/usr/bin/env python3
"""Re-index one website's knowledge_chunks under a single embedding identity.

Remediation for audit BUG-1 (mixed embedding space): a website whose corpus
holds chunks stamped with more than one embedding identity (e.g. gemini +
jina) can never answer for the minority space, because `$vectorSearch`
filters on the query embedding's identity. The fix is to rebuild the whole
website corpus under ONE identity using the existing ingestion pipeline.

What it does (in order):
  1. Resolves the website row and its tenant (scope check).
  2. BACKUP: copies every `knowledge_chunks` doc of this website (embeddings
     included) into a timestamped backup collection plus a metadata record,
     and prints the affected chunk count and identity distribution.
  3. Verifies the ingestion pipeline is reachable (ARQ Redis ping) BEFORE any
     destructive step.
  4. DELETE: removes only this website's `knowledge_chunks` (tenant-scoped).
     Nothing else is touched - no documents, no websites, no other collections.
  5. TRIGGERS the existing ingestion pipeline via
     `enqueue_process_website_documents` (ARQ fan-out; requires a running
     worker built WITH the BUG-1 fix so ingestion stays single-provider).
  6. VERIFIES: polls until every document reaches a terminal knowledge state,
     then prints the final embedding_provider distribution (must be exactly
     one identity).

Safety:
  - DRY-RUN by default: steps 4-5 are skipped unless `--execute` is passed.
  - Deletion is scoped to `{tenant_id, website_id}` and asserted to match the
    backup count.
  - Restore hint: copy docs back from the backup collection
    (`_backup_metadata` doc excepted) into `knowledge_chunks`.

Usage:
    python scripts/reindex-website-embedding-identity.py --website-id <ID>           # dry-run
    python scripts/reindex-website-embedding-identity.py --website-id <ID> --execute # real run

Defaults:
    --uri   $MONGODB_URI or mongodb://localhost:27017
    --db    $MONGODB_DB  or webchat_ai
    Env (identity settings, Redis) loads from .env.production unless overridden.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from datetime import UTC, datetime
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


def _distribution(collection: pymongo.collection.Collection, scope: dict) -> list[dict]:
    rows = collection.aggregate(
        [
            {"$match": scope},
            {
                "$group": {
                    "_id": {
                        "provider": "$embedding_provider",
                        "model": "$embedding_model",
                        "dimensions": "$embedding_dimensions",
                        "version": "$embedding_version",
                    },
                    "count": {"$sum": 1},
                    "documents": {"$addToSet": "$document_id"},
                }
            },
            {"$sort": {"count": -1}},
        ]
    )
    return [
        {
            "provider": row["_id"].get("provider"),
            "model": row["_id"].get("model"),
            "dimensions": row["_id"].get("dimensions"),
            "version": row["_id"].get("version"),
            "count": row["count"],
            "documents": len(row["documents"]),
        }
        for row in rows
    ]


def _print_distribution(rows: list[dict], indent: str = "  ") -> None:
    if not rows:
        print(f"{indent}(no chunks)")
    for row in rows:
        print(
            f"{indent}provider={row['provider']!r} model={row['model']!r} "
            f"dims={row['dimensions']!r} version={row['version']!r} "
            f"-> {row['count']} chunk(s) across {row['documents']} doc(s)"
        )


def _backup(db: pymongo.database.Database, scope: dict, website_id: str, reason: str) -> str:
    """Copy all scoped chunk docs into a timestamped backup collection."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_name = f"knowledge_chunks_backup_{website_id}_{stamp}"
    backup = db[backup_name]
    source = db["knowledge_chunks"]
    docs = list(source.find(scope))
    if docs:
        backup.insert_many(docs, ordered=False)
    backup.insert_one(
        {
            "_backup_metadata": True,
            "created_at": datetime.now(UTC),
            "reason": reason,
            "source_collection": "knowledge_chunks",
            "scope": scope,
            "chunk_count": len(docs),
            "distribution": _distribution(source, scope),
        }
    )
    return backup_name


def _drain_status(db: pymongo.database.Database, scope: dict) -> tuple[int, int]:
    """Return (documents still processing, total documents in scope)."""
    documents = db["documents"]
    processing = documents.count_documents({**scope, "knowledge_status": "processing"})
    total = documents.count_documents(scope)
    return processing, total


def reindex(
    uri: str,
    db_name: str,
    *,
    website_id: str,
    execute: bool,
    timeout_seconds: int,
    poll_interval_seconds: int,
) -> int:
    settings = get_settings()
    target_provider = (
        settings.embedding_provider_order[0] if settings.embedding_provider_order else None
    )
    print(
        "target identity (current config): "
        f"provider={target_provider!r} model={settings.embedding_model!r} "
        f"dims={settings.embedding_dimensions} version={settings.embedding_version!r}"
    )

    client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=15000)
    db = client[db_name]

    website = db["websites"].find_one({"_id": website_id})
    if website is None:
        print(f"ERROR: website {website_id!r} not found in 'websites'.", file=sys.stderr)
        return 1
    if website.get("status") == "deleted":
        print(f"ERROR: website {website_id!r} is deleted; nothing to re-index.", file=sys.stderr)
        return 1
    tenant_id = website.get("tenant_id")
    scope = {"tenant_id": tenant_id, "website_id": website_id}
    print(f"website={website_id} name={website.get('name')!r} tenant={tenant_id}")

    # ---- 1. Backup count + distribution -----------------------------------
    chunk_count = db["knowledge_chunks"].count_documents(scope)
    dist_before = _distribution(db["knowledge_chunks"], scope)
    identities = {(r["provider"], r["model"], r["dimensions"], r["version"]) for r in dist_before}
    print(f"\naffected chunk count: {chunk_count}")
    print("distribution BEFORE:")
    _print_distribution(dist_before)
    if len(identities) <= 1:
        print("\nNothing to do: corpus already holds a single embedding identity.")
        return 0

    # ---- 2. Pipeline reachability BEFORE any destructive step -------------
    if execute:
        try:
            from backend.core.redis import get_redis
            from backend.workers.jobs.knowledge import enqueue_process_website_documents

            asyncio.run(get_redis().ping())
            print("\nARQ Redis reachable: ingestion pipeline can be triggered.")
        except Exception as exc:  # noqa: BLE001 - abort before deleting anything
            print(
                f"\nABORT: cannot reach the ingestion pipeline ({exc}). "
                "No chunks were deleted. Start Redis/the worker and retry.",
                file=sys.stderr,
            )
            return 1

    # ---- 3. Backup ---------------------------------------------------------
    if execute:
        backup_name = _backup(
            db,
            scope,
            website_id,
            reason=f"BUG-1 mixed-identity re-index; identities={sorted(map(str, identities))}",
        )
        backed_up = db[backup_name].count_documents({"_backup_metadata": {"$ne": True}})
        print(f"backup written: {backup_name} ({backed_up} doc(s); expected {chunk_count})")
        if backed_up != chunk_count:
            print(
                f"ABORT: backup count {backed_up} != source count {chunk_count}. "
                "No chunks were deleted.",
                file=sys.stderr,
            )
            return 1
    else:
        print("\nDRY RUN: backup collection would be created here.")

    # ---- 4. Delete (this website only) ------------------------------------
    if execute:
        result = db["knowledge_chunks"].delete_many(scope)
        print(f"deleted {result.deleted_count} chunk(s) scoped to {scope}")
        if result.deleted_count != chunk_count:
            print(
                f"WARNING: deleted {result.deleted_count} != backed-up {chunk_count}; "
                "continuing (backup collection holds the exact prior state)."
            )
    else:
        print(f"DRY RUN: would delete {chunk_count} chunk(s) scoped to {scope}.")
        print("DRY RUN: would enqueue process_website_documents fan-out.")
        print("\nDry-run complete. Re-run with --execute to apply.")
        return 0

    # ---- 5. Trigger the existing ingestion pipeline ------------------------
    asyncio.run(enqueue_process_website_documents(website_id))
    print(
        "enqueued process_website_documents; the running ARQ worker will now "
        "re-embed every document (single-provider ingestion, BUG-1 fix required)."
    )

    # ---- 6. Verify final distribution --------------------------------------
    print(f"\nwaiting for drain (timeout {timeout_seconds}s, poll {poll_interval_seconds}s)...")
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        time.sleep(poll_interval_seconds)
        processing, total_docs = _drain_status(db, scope)
        count = db["knowledge_chunks"].count_documents(scope)
        print(f"  processing={processing}/{total_docs} docs, chunks={count}")
        if processing == 0 and count > 0:
            break
    else:
        print(
            "\nTIMEOUT waiting for the worker to finish. Check worker logs, then "
            "re-run this script WITHOUT --execute to inspect the distribution.",
            file=sys.stderr,
        )
        return 2

    dist_after = _distribution(db["knowledge_chunks"], scope)
    identities_after = {
        (r["provider"], r["model"], r["dimensions"], r["version"]) for r in dist_after
    }
    print("\ndistribution AFTER:")
    _print_distribution(dist_after)
    failed = db["documents"].count_documents({**scope, "knowledge_status": "failed"})
    if failed:
        print(f"WARNING: {failed} document(s) ended in knowledge_status=failed.")
    if len(identities_after) == 1:
        print("\nSUCCESS: the website corpus now holds exactly one embedding identity.")
        return 0
    print(
        "\nFAILURE: multiple embedding identities remain. Restore from the backup "
        "collection and investigate before retrying.",
        file=sys.stderr,
    )
    return 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--website-id", required=True, help="website to re-index (required)")
    parser.add_argument("--execute", action="store_true", help="apply changes (default: dry-run)")
    parser.add_argument(
        "--uri", default=None, help="defaults to $MONGODB_URI or mongodb://localhost:27017"
    )
    parser.add_argument("--db", default=None, help="defaults to $MONGODB_DB or webchat_ai")
    parser.add_argument(
        "--env-file",
        default=str(_project_root / ".env.production"),
        help="env file to load for settings (default: .env.production)",
    )
    parser.add_argument("--timeout", type=int, default=1800, help="drain wait budget in seconds")
    parser.add_argument("--poll-interval", type=int, default=15, help="seconds between polls")
    args = parser.parse_args()
    _load_env(Path(args.env_file))
    uri = args.uri or os.environ.get("MONGODB_URI", "mongodb://localhost:27017")
    db_name = args.db or os.environ.get("MONGODB_DB", "webchat_ai")
    try:
        return reindex(
            uri,
            db_name,
            website_id=args.website_id,
            execute=args.execute,
            timeout_seconds=args.timeout,
            poll_interval_seconds=args.poll_interval,
        )
    except pymongo.errors.ServerSelectionTimeoutError as error:
        print(f"reindex-website-embedding-identity: MongoDB unreachable: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
