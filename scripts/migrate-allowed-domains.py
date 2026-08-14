#!/usr/bin/env python3
"""Repair legacy `allowed_domains` widget data in MongoDB.

Before the strict allowlist policy, widgets could be seeded (or edited) with
values that are no longer valid under the dashboard/backend validation, e.g.
full URLs (`http://localhost:3000`), trailing dots, uppercase, or malformed
entries. This script normalizes every stored allowlist with the same rules the
dashboard applies (`backend.utils.origin.normalize_domain_entry`), so:
  * `http://localhost:3000`  -> `localhost`
  * `HTTPS://WWW.Example.COM` -> `www.example.com`
  * `example.com/`           -> dropped (invalid)
  * `*` stays `*` (open-embed opt-in is preserved)

Nothing is deleted unless it is invalid; an empty allowlist is kept empty
(that now means "blocked until configured", not "any origin").

Usage:
    python scripts/migrate-allowed-domains.py [--dry-run] [--uri mongodb://...]

Defaults:
    --uri   $MONGODB_URI or mongodb://localhost:27017
    --db    $MONGODB_DB  or webchat_ai
"""

from __future__ import annotations

import argparse
import os
import sys

import pymongo
from backend.utils.origin import normalize_domain_entry


def _normalize_allowlist(entries: list[str] | None) -> list[str]:
    """Normalize one widget's allowlist, preserving order and dropping junk."""
    if not entries:
        return []
    normalized: list[str] = []
    for entry in entries:
        value = normalize_domain_entry(entry)
        if value is None:
            continue
        if value not in normalized:
            normalized.append(value)
    return normalized


def migrate(uri: str, db_name: str, *, dry_run: bool) -> int:
    client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=5000)
    collection = client[db_name]["widgets"]
    total_widgets = 0
    changed_widgets = 0
    dropped_entries = 0
    for widget in collection.find({"allowed_domains": {"$exists": True}}):
        total_widgets += 1
        stored = list(widget.get("allowed_domains") or [])
        fixed = _normalize_allowlist(stored)
        if fixed == stored:
            continue
        changed_widgets += 1
        dropped_entries += len(stored) - len(fixed)
        if not dry_run:
            collection.update_one(
                {"_id": widget["_id"]}, {"$set": {"allowed_domains": fixed}}
            )
        print(
            f"{'[dry-run] ' if dry_run else ''}{widget.get('widget_id', widget['_id'])}: "
            f"{stored} -> {fixed}"
        )
    print(
        f"\n{total_widgets} widget(s) inspected, {changed_widgets} changed, "
        f"{dropped_entries} invalid entrie(s) removed "
        f"({'DRY RUN — no writes' if dry_run else 'writes applied'})."
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uri", default=os.environ.get("MONGODB_URI", "mongodb://localhost:27017"))
    parser.add_argument("--db", default=os.environ.get("MONGODB_DB", "webchat_ai"))
    parser.add_argument("--dry-run", action="store_true", help="report changes without writing")
    args = parser.parse_args()
    try:
        return migrate(args.uri, args.db, dry_run=args.dry_run)
    except pymongo.errors.ServerSelectionTimeoutError as error:
        print(f"migrate-allowed-domains: MongoDB unreachable: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
