"""RAG retrieval debug tool (read-only).

Mirrors the exact production chat path:
1. Embed the test query through the configured fallback chain
   (`build_embedding_fallback`, the same client `RagService` uses).
2. Run `MongoVectorRepository.similarity_search` - the exact method the chat
   pipeline calls - with the real tenant/website from the `widgets` collection.
3. Print the top-5 hits (score, chunk id, website_id, source url, text) or the
   reason no context is produced (no index, unsupported deployment, etc.).

Also prints deployment info (MongoDB version, search-index availability) so a
regression can be diagnosed without touching the app.

    WIDGET_SCRIPT_URL=https://cdn.example.com/w.js \
    WIDGET_API_BASE_URL=https://api.example.com \
    .venv/bin/python scripts/debug_vector_search.py

(Override WIDGET_* only when the local .env pins localhost values while
ENVIRONMENT=production.)
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path


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


async def main() -> None:
    _load_env()
    from backend.ai.registry import build_embedding_fallback
    from backend.core.config import get_settings
    from backend.core.database import MongoDB
    from backend.repositories.vector import get_vector_repository

    settings = get_settings()
    print(f"embedding_provider_order={settings.embedding_provider_order}")
    print(f"embedding_model={settings.embedding_model}")
    print(f"embedding_dimensions={settings.embedding_dimensions}")
    print(f"chat_top_k={settings.chat_top_k}")

    db = MongoDB.db()
    try:
        hello = await db.command("hello")
        print(f"deployment: mongodb={hello.get('clusterRole')}")
    except Exception as exc:  # noqa: BLE001
        print(f"deployment info unavailable: {exc}")

    # Resolve the widget -> website -> tenant identity exactly like the API does.
    widgets = [w async for w in db["widgets"].find({})]
    if not widgets:
        print("\nno widgets found; nothing to debug")
        await _close(db)
        return
    widget = widgets[0]
    tenant_id = str(widget["tenant_id"])
    website_id = str(widget["website_id"])
    print(f"\nwidget={widget['_id']} tenant_id={tenant_id} website_id={website_id}")

    website = await db["websites"].find_one({"_id": website_id})
    if website:
        print(
            f"website name={website.get('name')!r} status={website.get('status')} "
            f"knowledge_status={website.get('knowledge_status')} "
            f"knowledge_chunks={website.get('knowledge_chunks')}"
        )

    query = "What courses are offered by Indira University?"
    print(f"\nquery: {query!r}")

    embedder = build_embedding_fallback()
    query_vector = (await embedder.embed([query]))[0]
    print(f"query embedding: provider={embedder.active_provider or '?'} dims={len(query_vector)}")

    vector = get_vector_repository(db)
    results = await vector.similarity_search(
        tenant_id, website_id, query_vector, top_k=settings.chat_top_k
    )

    print(f"\ntop {len(results)} results:")
    for rank, result in enumerate(results, start=1):
        metadata = result.chunk.metadata
        print(
            f"  [{rank}] score={result.score:.6f} chunk_id={result.chunk.id}\n"
            f"        website_id={result.chunk.website_id} document_id={result.chunk.document_id}\n"
            f"        source_url={metadata.get('source_url')}\n"
            f"        text={result.chunk.chunk_text[:140]!r}"
        )
    if not results:
        print("  (none)")

    await _close(db)


async def _close(db) -> None:
    try:
        await db.client.close()
    except Exception:  # noqa: BLE001
        pass


if __name__ == "__main__":
    asyncio.run(main())
