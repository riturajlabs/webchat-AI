"""Shared helpers for RAG chat tests (Phase 6).

`build_chat_env` wires every fake repository plus the `RagService` (and a
`WebsiteService` over the same website/widget/audit fakes) so API tests can
exercise the full register -> create website -> chat flow.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from backend.models.knowledge_chunk import KNOWLEDGE_STATUS_READY, KnowledgeChunk
from backend.models.website import WEBSITE_STATUS_READY, Website
from backend.repositories.vector.base import VectorSearchResult
from backend.services.chat.rag_service import RagService
from backend.services.website import WebsiteService

from tests.fakes import (
    FakeAuditLogRepository,
    FakeCacheStore,
    FakeChatMessageRepository,
    FakeChatSessionRepository,
    FakeEmbeddingClient,
    FakeGenerationClient,
    FakeUsageRecordRepository,
    FakeVectorRepository,
    FakeWebsiteRepository,
    FakeWidgetRepository,
)


@dataclass
class ChatEnv:
    websites: FakeWebsiteRepository
    widgets: FakeWidgetRepository
    audit: FakeAuditLogRepository
    vector: FakeVectorRepository
    embedder: FakeEmbeddingClient
    generation: FakeGenerationClient
    sessions: FakeChatSessionRepository
    messages: FakeChatMessageRepository
    usage: FakeUsageRecordRepository
    cache: FakeCacheStore
    rag: RagService
    websites_service: WebsiteService


def build_chat_env(
    *,
    top_k: int = 5,
    memory_turns: int = 8,
    deltas: list[str] | None = None,
    cache: FakeCacheStore | None = None,
    reranker: bool = False,
) -> ChatEnv:
    websites = FakeWebsiteRepository()
    widgets = FakeWidgetRepository()
    audit = FakeAuditLogRepository()
    vector = FakeVectorRepository()
    embedder = FakeEmbeddingClient()
    generation = FakeGenerationClient(deltas=deltas)
    sessions = FakeChatSessionRepository()
    messages = FakeChatMessageRepository()
    usage = FakeUsageRecordRepository()
    cache_store = cache if cache is not None else FakeCacheStore()
    rag = RagService(
        websites=websites,
        vector=vector,
        embedder=embedder,
        generation=generation,
        sessions=sessions,
        messages=messages,
        usage=usage,
        cache=cache_store,
        top_k=top_k,
        memory_turns=memory_turns,
        allow_reranking=reranker,
    )
    websites_service = WebsiteService(
        websites=websites,
        widgets=widgets,
        audit=audit,
    )
    return ChatEnv(
        websites=websites,
        widgets=widgets,
        audit=audit,
        vector=vector,
        embedder=embedder,
        generation=generation,
        sessions=sessions,
        messages=messages,
        usage=usage,
        cache=cache_store,
        rag=rag,
        websites_service=websites_service,
    )


async def make_website(
    env: ChatEnv,
    *,
    tenant_id: str = "tenant-a",
    website_id: str = "web-1",
    url: str = "https://example.com",
    knowledge_chunks: int = 1,
) -> Website:
    website = Website.new(tenant_id=tenant_id, name="Example", url=url)
    website.id = website_id
    website.status = WEBSITE_STATUS_READY
    website.knowledge_status = KNOWLEDGE_STATUS_READY
    website.knowledge_chunks = knowledge_chunks
    await env.websites.create(website)
    return website


async def make_chunk(
    env: ChatEnv,
    *,
    tenant_id: str,
    website_id: str,
    text: str,
    url: str = "https://example.com/page",
    title: str = "Page",
    document_id: str = "doc-1",
    chunk_index: int = 0,
) -> KnowledgeChunk:
    chunk = KnowledgeChunk.new(
        tenant_id=tenant_id,
        website_id=website_id,
        document_id=document_id,
        chunk_text=text,
        embedding=[0.0, 0.0, 0.0, 0.0],
        chunk_index=chunk_index,
        embedding_provider=env.embedder.embedding_identity.provider,
        embedding_model=env.embedder.embedding_identity.model,
        embedding_dimensions=env.embedder.embedding_identity.dimensions,
        embedding_version=env.embedder.embedding_identity.version,
        metadata={"source_url": url, "title": title},
    )
    await env.vector.insert_chunks([chunk])
    return chunk


async def consume(stream) -> list[dict]:
    """Collect all events from a `stream_answer` generator."""
    return [event async for event in stream]


_RELEVANCE_STOPWORDS = frozenset(
    "a an and are as at be by do does for from how i in is it me my no not of on or "
    "that the this to was what when where which who why will with you your".split()
)
_TOKEN_RE = re.compile(r"[a-z0-9$]+")


def _relevance_tokens(text: str) -> set[str]:
    return {
        token
        for token in _TOKEN_RE.findall(text.lower())
        if token not in _RELEVANCE_STOPWORDS and not token.isdigit()
    }


def install_relevance_scoring(env: ChatEnv) -> None:
    """Make `env.vector.similarity_search` score chunks by lexical relevance.

    The default `FakeVectorRepository` returns a constant 0.9 for every
    query-chunk pair, so retrieval-dependent behaviour (confidence gating,
    fallback on irrelevant questions) can never trigger. This helper replaces
    `similarity_search` with a deterministic token-overlap score between the
    question (the text the fake embedder embedded last) and each chunk,
    returning only chunks with overlap > 0 — mirroring how a real ANN index
    behaves for unrelated queries. Production code is untouched.
    """

    async def relevance_search(
        tenant_id: str,
        website_id: str,
        query_embedding: list[float],
        *,
        top_k: int = 5,
        embedding_identity: object = None,
    ) -> list[VectorSearchResult]:
        question = env.embedder.calls[-1][-1] if env.embedder.calls else ""
        query_tokens = _relevance_tokens(question)
        scored: list[VectorSearchResult] = []
        for chunk in env.vector.chunks:
            if chunk.tenant_id != tenant_id or chunk.website_id != website_id:
                continue
            chunk_tokens = _relevance_tokens(chunk.chunk_text)
            if not query_tokens or not chunk_tokens:
                continue
            overlap = len(query_tokens & chunk_tokens)
            if overlap == 0:
                continue
            score = overlap / min(len(query_tokens), len(chunk_tokens))
            scored.append(VectorSearchResult(chunk=chunk, score=round(score, 4)))
        scored.sort(key=lambda result: result.score, reverse=True)
        return scored[:top_k]

    env.vector.similarity_search = relevance_search  # type: ignore[method-assign]
