"""RAG pipeline debug inspector (read-only).

Loads .env, connects to MongoDB (Atlas or local), and prints the shape of
the data the retrieval pipeline depends on: widgets -> websites -> documents
-> knowledge_chunks, plus the Atlas vector index status and embedding dims.

Read-only: never mutates production data. Run with the project venv:
    .venv/bin/python scripts/inspect_rag.py
"""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

import pymongo


def _load_env() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _embedding_dims(doc: dict[str, Any]) -> int | None:
    embedding = doc.get("embedding")
    if isinstance(embedding, list):
        return len(embedding)
    return None


def main() -> None:
    _load_env()
    uri = os.environ.get("MONGODB_URI", "")
    db_name = os.environ.get("MONGODB_DB", "webchat_ai")
    if not uri:
        raise SystemExit("MONGODB_URI is not set.")

    client = pymongo.MongoClient(
        uri,
        serverSelectionTimeoutMS=15000,
    )
    db = client[db_name]
    print(f"db={db_name}")

    widgets = list(db["widgets"].find({}))
    print(f"\n== widgets: {len(widgets)}")
    for w in widgets:
        print(
            f"  widget_id={w.get('_id')} tenant_id={w.get('tenant_id')} "
            f"website_id={w.get('website_id')} enabled={w.get('enabled')}"
        )

    websites = list(db["websites"].find({}))
    print(f"\n== websites: {len(websites)}")
    for s in websites:
        print(
            f"  website_id={s.get('_id')} tenant_id={s.get('tenant_id')} "
            f"name={s.get('name')!r} url={s.get('url')!r} status={s.get('status')} "
            f"knowledge_status={s.get('knowledge_status')} "
            f"knowledge_documents={s.get('knowledge_documents')} "
            f"knowledge_chunks={s.get('knowledge_chunks')} "
            f"deleted={s.get('deleted')}"
        )

    documents = list(db["documents"].find({}))
    print(f"\n== documents: {len(documents)}")
    per_website: Counter[str] = Counter()
    ready = 0
    for d in documents:
        per_website[str(d.get("website_id"))] += 1
        if d.get("knowledge_status") == "ready":
            ready += 1
        if d.get("knowledge_status") == "ready" and d.get("knowledge_chunks", 0) > 0:
            pass
    print(f"  total documents: {len(documents)}, knowledge_status=ready: {ready}")
    for website_id, count in per_website.items():
        print(f"  website_id={website_id}: {count} documents")

    sample_docs = list(db["documents"].find({}).limit(5))
    for d in sample_docs:
        print(
            f"  doc id={d.get('_id')} website_id={d.get('website_id')} "
            f"title={str(d.get('title'))[:60]!r} knowledge_status={d.get('knowledge_status')} "
            f"knowledge_chunks={d.get('knowledge_chunks')}"
        )

    chunks_total = db["knowledge_chunks"].count_documents({})
    print(f"\n== knowledge_chunks: {chunks_total} total")

    per_website_chunks = Counter()
    per_website_dims: dict[str, set[int | None]] = {}
    no_embedding = 0
    for chunk in db["knowledge_chunks"].find({}, {"website_id": 1, "embedding": 1, "tenant_id": 1}):
        website_id = str(chunk.get("website_id"))
        per_website_chunks[website_id] += 1
        per_website_dims.setdefault(website_id, set()).add(_embedding_dims(chunk))
        if not chunk.get("embedding"):
            no_embedding += 1
    for website_id, count in per_website_chunks.items():
        dims = per_website_dims[website_id]
        print(f"  website_id={website_id}: {count} chunks, embedding dims={dims}")
    print(f"  chunks with no embedding: {no_embedding}")

    sample_chunks = list(
        db["knowledge_chunks"].find({}).sort([("created_at", -1)]).limit(3)
    )
    for c in sample_chunks:
        print(
            f"  chunk id={c.get('_id')} tenant_id={c.get('tenant_id')} "
            f"website_id={c.get('website_id')} document_id={c.get('document_id')} "
            f"chunk_index={c.get('chunk_index')} dims={_embedding_dims(c)} "
            f"text={str(c.get('chunk_text'))[:70]!r}"
        )

    tenants = set()
    for w in widgets:
        tenants.add(str(w.get("tenant_id")))
    for s in websites:
        tenants.add(str(s.get("tenant_id")))
    for d in documents:
        tenants.add(str(d.get("tenant_id")))
    print(f"\n== distinct tenant_ids: {tenants}")

    try:
        indexes = list(db["knowledge_chunks"].list_search_indexes())
        for ix in indexes:
            print(
                f"== vector search index: name={ix.get('name')} "
                f"type={ix.get('type')} status={ix.get('status')} "
                f"definition={json.dumps(ix.get('latestDefinition', ix.get('definition', {})))}"
            )
    except Exception as exc:  # noqa: BLE001
        print(f"== vector search index: unavailable ({exc})")

    client.close()


if __name__ == "__main__":
    main()
