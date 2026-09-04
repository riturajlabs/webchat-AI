#!/usr/bin/env python3
"""Re-chunk and re-embed one existing website without crawling.

Dry-run is the default. Execution uses the persisted website embedding lock,
processes only the requested tenant/site documents, and relies on the
processor's insert-first ``replace_by_document`` operation.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from backend.ai.registry import build_locked_embedding_client  # noqa: E402
from backend.core.database import MongoDB  # noqa: E402
from backend.core.embedding_identity import EmbeddingIdentity  # noqa: E402
from backend.models.knowledge_chunk import KnowledgeChunk  # noqa: E402
from backend.repositories import (  # noqa: E402
    MongoAuditLogRepository,
    MongoDocumentRepository,
    MongoKnowledgeChunkRepository,
    MongoUsageRecordRepository,
    MongoWebsiteRepository,
)
from backend.repositories.vector import get_vector_repository  # noqa: E402
from backend.services.knowledge.chunker import chunk_text  # noqa: E402
from backend.services.knowledge.corpus_quality import CorpusEntry, compute_metrics  # noqa: E402
from backend.services.knowledge.processor import KnowledgeProcessor  # noqa: E402

TENANT_ID = "fc9a1f08-70de-4185-b34d-fbaa28624dd5"
WEBSITE_ID = "3178bfdf-3ca9-44c7-8ccf-0e19ce20f83e"
EXPECTED_IDENTITY = ("jina", "jina-embeddings-v3", 1024, "1")


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def validate_target(website: Any, *, tenant_id: str, website_id: str) -> None:
    """Reject missing, deleted, or cross-tenant targets before any work."""
    if website is None or website.id != website_id or website.tenant_id != tenant_id:
        raise RuntimeError("target website was not found in the requested tenant")
    if website.status == "deleted":
        raise RuntimeError("target website is deleted")


def _locked_provider(embedder: Any) -> Any:
    async def resolve(_: Any) -> Any:
        return embedder

    return resolve


async def run(*, tenant_id: str, website_id: str, execute: bool) -> dict[str, Any]:
    db = MongoDB.db()
    websites = MongoWebsiteRepository(db)
    website = await websites.find_by_id(tenant_id, website_id)
    validate_target(website, tenant_id=tenant_id, website_id=website_id)
    assert website is not None
    identity = website.embedding_identity
    documents = await MongoDocumentRepository(db).list_by_website(tenant_id, website_id)
    before = await MongoKnowledgeChunkRepository(db).count_by_website(tenant_id, website_id)
    stored_chunks = [
        KnowledgeChunk.from_doc(item)
        async for item in db["knowledge_chunks"].find(
            {"tenant_id": tenant_id, "website_id": website_id}
        )
    ]
    chunk_identities = {
        (
            chunk.embedding_provider,
            chunk.embedding_model,
            chunk.embedding_dimensions,
            chunk.embedding_version,
        )
        for chunk in stored_chunks
    }
    actual = (
        (identity.provider, identity.model, identity.dimensions, identity.version)
        if identity
        else next(iter(chunk_identities), None)
    )
    if actual != EXPECTED_IDENTITY:
        raise RuntimeError(f"refusing non-Jina or unlocked website identity: {actual!r}")
    if chunk_identities != {EXPECTED_IDENTITY}:
        raise RuntimeError(f"refusing mixed or incomplete chunk identities: {chunk_identities!r}")
    identity = EmbeddingIdentity(
        provider=actual[0], model=actual[1], dimensions=actual[2], version=actual[3]
    )
    document_sources = {document.id: document.url for document in documents}
    old_entries = [
        CorpusEntry.from_chunk(chunk, source=document_sources.get(chunk.document_id, ""))
        for chunk in stored_chunks
    ]
    simulated_entries = [
        CorpusEntry.from_text_chunk(
            chunk,
            source=document.url,
        )
        for document in documents
        for chunk in chunk_text(document.content)
    ]
    report: dict[str, Any] = {
        "tenant_id": tenant_id,
        "website_id": website_id,
        "documents": len(documents),
        "chunks_before": before,
        "identity": actual,
        "executed": execute,
        "old_metrics": compute_metrics(old_entries).to_dict(),
        "simulated_new_metrics": compute_metrics(simulated_entries).to_dict(),
    }
    if not execute:
        return report

    locked_embedder = build_locked_embedding_client(identity)
    acquired = await websites.acquire_embedding_run(tenant_id, website_id, identity)
    if acquired is None:
        raise RuntimeError("another embedding run is already active for this website")
    processor = KnowledgeProcessor(
        documents=MongoDocumentRepository(db),
        vector=get_vector_repository(db),
        chunks=MongoKnowledgeChunkRepository(db),
        websites=websites,
        audit=MongoAuditLogRepository(db),
        embedder=locked_embedder,
        usage=MongoUsageRecordRepository(db),
        provider_resolver=_locked_provider(locked_embedder),
    )
    results = []
    for document in documents:
        results.append(
            await processor.process_document(
                document.id,
                force_rechunk=True,
                run_id=acquired.embedding_run.id if acquired.embedding_run else None,
            )
        )
    report["results"] = results
    report["chunks_after"] = await MongoKnowledgeChunkRepository(db).count_by_website(
        tenant_id, website_id
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", default=TENANT_ID)
    parser.add_argument("--website-id", default=WEBSITE_ID)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--env-file", default=str(_PROJECT_ROOT / ".env.production"))
    args = parser.parse_args()
    _load_env(Path(args.env_file))
    try:
        report = asyncio.run(
            run(tenant_id=args.tenant_id, website_id=args.website_id, execute=args.execute)
        )
    except Exception as exc:
        print(f"REINGESTION_ABORTED: {exc}", file=sys.stderr)
        return 1
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
