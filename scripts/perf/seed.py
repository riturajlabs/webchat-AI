#!/usr/bin/env python3
"""Seed a reproducible performance-baseline dataset (Phase 12.1).

Writes a realistic multi-tenant dataset directly into MongoDB using the app's
own models, so every endpoint (dashboard, widget, chat, analytics) has real
data to read/write. The seeded knowledge chunks carry deterministic 3072-dim
embeddings (same generator as the `mock` embedding provider), so vector search
brute-force work is representative.

Run against the native perf MongoDB:
    uv run python scripts/perf/seed.py --reset

Known account (password hashed with the app's Argon2id):
    email:    perf@example.com
    password: perf-password-123

The script only ever touches the collections it seeds and, with `--reset`,
drops them first - it never touches other application data.
"""

import argparse
import asyncio
import logging
from datetime import timedelta
from typing import Any

from backend.ai.mock import MockEmbeddingClient
from backend.core.security import (
    hash_password,
    new_id,
    utcnow,
)
from backend.models.chat_message import CHAT_ROLE_ASSISTANT, CHAT_ROLE_USER, ChatMessage
from backend.models.chat_session import ChatSession
from backend.models.document import Document
from backend.models.knowledge_chunk import KNOWLEDGE_STATUS_READY, KnowledgeChunk
from backend.models.member import Member
from backend.models.tenant import Tenant
from backend.models.usage_record import USAGE_COUNTERS, UsageRecord
from backend.models.user import User
from backend.models.website import WEBSITE_STATUS_READY, Website
from backend.models.widget import Widget
from motor.motor_asyncio import AsyncIOMotorClient

logger = logging.getLogger("seed")

EMAIL = "perf@example.com"
PASSWORD = "perf-password-123"

SEED_COLLECTIONS = [
    "tenants",
    "users",
    "members",
    "websites",
    "widgets",
    "documents",
    "knowledge_chunks",
    "chat_sessions",
    "messages",
    "usage_records",
]


async def _reset(db: Any) -> None:
    for name in SEED_COLLECTIONS:
        await db[name].drop()
        logger.info("dropped %s", name)


def _sample(seed: int, low: int, high: int) -> int:
    return low + (seed % (high - low + 1))


async def _seed_embedding(embedder: MockEmbeddingClient, text: str) -> list[float]:
    vectors = await embedder.embed([text])
    return vectors[0]


def _build_chunk_text(document_index: int, chunk_index: int) -> str:
    return (
        f"Seed document {document_index} chunk {chunk_index}. "
        "This is representative knowledge-base content for performance "
        "benchmarking: it exists so retrieval has realistic data to score "
        "without contacting any external service."
    )


async def seed(
    *,
    uri: str,
    db_name: str,
    reset: bool,
    websites: int,
    documents: int,
    chunks: int,
    sessions: int,
    messages: int,
    embedding_dimensions: int,
) -> None:
    client = AsyncIOMotorClient(uri)
    db = client[db_name]
    if reset:
        await _reset(db)

    embedder = MockEmbeddingClient(dimensions=embedding_dimensions)
    now = utcnow()

    tenant = Tenant.new(company_name="Performance Tenant")
    user = User.new(
        tenant_id=tenant.id,
        name="Performance Owner",
        email=EMAIL,
        password_hash=hash_password(PASSWORD),
    )
    user.email_verified = True
    member = Member.new(tenant_id=tenant.id, user_id=user.id, role="owner")

    await db["tenants"].insert_one(tenant.to_doc())
    await db["users"].insert_one(user.to_doc())
    await db["members"].insert_one(member.to_doc())

    website_ids: list[str] = []
    widget_ids: list[str] = []
    total_chunks = 0

    for w in range(websites):
        website = Website.new(
            tenant_id=tenant.id,
            name=f"Performance Site {w + 1}",
            url=f"https://perf-example-{w + 1}.test",
        )
        website.status = WEBSITE_STATUS_READY
        website.pages_indexed = documents
        website.knowledge_status = KNOWLEDGE_STATUS_READY
        website.last_crawled_at = now - timedelta(days=3)
        website.last_knowledge_at = now - timedelta(days=2)

        widget = Widget.new(
            tenant_id=tenant.id,
            website_id=website.id,
        )
        widget.suggested_questions = ["What does your product do?", "How do I get started?"]

        await db["websites"].insert_one(website.to_doc())
        await db["widgets"].insert_one(widget.to_doc())
        website_ids.append(website.id)
        widget_ids.append(widget.widget_id)

        chunk_docs: list[dict[str, Any]] = []
        for d in range(documents):
            document = Document.new(
                tenant_id=tenant.id,
                website_id=website.id,
                url=f"{website.url}/docs/{d + 1}",
                title=f"Seed document {d + 1}",
                content=" ".join(_build_chunk_text(d, c) for c in range(chunks)),
                checksum=f"seed-{w}-{d}",
            )
            document.knowledge_status = KNOWLEDGE_STATUS_READY
            document.knowledge_checksum = document.checksum
            document.knowledge_chunks = chunks
            document.knowledge_processed_at = now - timedelta(days=2)
            await db["documents"].insert_one(document.to_doc())

            for c in range(chunks):
                text = _build_chunk_text(d, c)
                chunk = KnowledgeChunk.new(
                    tenant_id=tenant.id,
                    website_id=website.id,
                    document_id=document.id,
                    chunk_text=text,
                    embedding=await _seed_embedding(embedder, text),
                    chunk_index=c,
                    metadata={
                        "source_url": document.url,
                        "title": document.title,
                    },
                )
                chunk_docs.append(chunk.to_doc())
                total_chunks += 1
            if len(chunk_docs) >= 200:
                await db["knowledge_chunks"].insert_many(chunk_docs, ordered=False)
                chunk_docs = []
        if chunk_docs:
            await db["knowledge_chunks"].insert_many(chunk_docs, ordered=False)

        website.knowledge_chunks = documents * chunks
        await db["websites"].update_one(
            {"_id": website.id},
            {"$set": {"knowledge_chunks": website.knowledge_chunks}},
        )

    session_docs: list[dict[str, Any]] = []
    message_docs: list[dict[str, Any]] = []
    for s in range(sessions):
        website_id = website_ids[s % len(website_ids)]
        started = now - timedelta(days=s % 30, hours=s % 24)
        session = ChatSession(
            id=new_id(),
            tenant_id=tenant.id,
            website_id=website_id,
            session_id=new_id(),
            visitor_id=f"visitor-{s % 40}",
            started_at=started,
            last_activity=started + timedelta(minutes=5),
            expires_at=started + timedelta(days=90),
        )
        session_docs.append(session.to_doc())
        for m in range(messages):
            role = CHAT_ROLE_ASSISTANT if m % 2 else CHAT_ROLE_USER
            message = ChatMessage(
                id=new_id(),
                tenant_id=tenant.id,
                website_id=website_id,
                session_id=session.session_id,
                role=role,
                content=(
                    "Sample assistant answer from the seeded knowledge base."
                    if role == CHAT_ROLE_ASSISTANT
                    else "Sample user question for performance benchmarking."
                ),
                sources=(
                    [{"url": f"{website_id}/doc", "title": "Seed doc", "score": 0.9, "citation": 1}]
                    if role == CHAT_ROLE_ASSISTANT
                    else []
                ),
                response_time=0.42 if role == CHAT_ROLE_ASSISTANT else None,
                input_tokens=120 if role == CHAT_ROLE_ASSISTANT else 40,
                output_tokens=180 if role == CHAT_ROLE_ASSISTANT else 0,
                created_at=started + timedelta(minutes=m),
            )
            message_docs.append(message.to_doc())
        if len(session_docs) >= 200:
            await db["chat_sessions"].insert_many(session_docs, ordered=False)
            await db["messages"].insert_many(message_docs, ordered=False)
            session_docs, message_docs = [], []
    if session_docs:
        await db["chat_sessions"].insert_many(session_docs, ordered=False)
        await db["messages"].insert_many(message_docs, ordered=False)

    usage_docs: list[dict[str, Any]] = []
    for day in range(30):
        for w, website_id in enumerate(website_ids):
            date = (now - timedelta(days=day)).strftime("%Y-%m-%d")
            usage = UsageRecord.new(tenant_id=tenant.id, website_id=website_id, date=date)
            usage.counters = {
                counter: _sample(day * 100 + w * 7 + index, 5, 400)
                for index, counter in enumerate(USAGE_COUNTERS)
            }
            usage_docs.append(usage.to_doc())
    await db["usage_records"].insert_many(usage_docs, ordered=False)

    print("\nSeeded performance dataset:")
    print(f"  tenant:      {tenant.id}")
    print(f"  login:       {EMAIL} / {PASSWORD}")
    print(f"  websites:    {len(website_ids)}  (ids: {', '.join(website_ids)})")
    print(f"  widgets:     {len(widget_ids)}  (widget_id[0]: {widget_ids[0]})")
    print(f"  chunks:      {total_chunks}  (dims {embedding_dimensions})")
    print(f"  sessions:    {sessions}  messages: {sessions * messages}  usage days: 30")
    client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the performance-baseline dataset.")
    parser.add_argument("--uri", default="mongodb://localhost:27017")
    parser.add_argument("--db", default="webchat_ai")
    parser.add_argument("--reset", action="store_true", help="drop the seeded collections first")
    parser.add_argument("--websites", type=int, default=3)
    parser.add_argument("--documents", type=int, default=5)
    parser.add_argument("--chunks", type=int, default=10)
    parser.add_argument("--sessions", type=int, default=500)
    parser.add_argument("--messages", type=int, default=6)
    parser.add_argument("--embedding-dimensions", type=int, default=3072)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)
    asyncio.run(
        seed(
            uri=args.uri,
            db_name=args.db,
            reset=args.reset,
            websites=args.websites,
            documents=args.documents,
            chunks=args.chunks,
            sessions=args.sessions,
            messages=args.messages,
            embedding_dimensions=args.embedding_dimensions,
        )
    )


if __name__ == "__main__":
    main()
