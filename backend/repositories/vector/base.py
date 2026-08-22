"""Vector store abstraction (00-AI-Development-Rules.md §13).

Application logic (services, worker jobs) depends only on `VectorRepository`;
the concrete backend (MongoDB Atlas Vector Search today, Qdrant/Pinecone
tomorrow) is bound through a factory. Every method is tenant-scoped - no
cross-tenant vector access is possible.
"""

from dataclasses import dataclass
from typing import Protocol

from backend.core.embedding_identity import EmbeddingIdentity
from backend.models.knowledge_chunk import KnowledgeChunk


@dataclass(frozen=True)
class VectorSearchResult:
    """One vector-search hit with its similarity score."""

    chunk: KnowledgeChunk
    score: float


class VectorRepository(Protocol):
    """Write/delete/search operations over embedded knowledge chunks."""

    async def insert_chunks(self, chunks: list[KnowledgeChunk]) -> int: ...

    async def delete_by_document(self, tenant_id: str, document_id: str) -> int: ...

    async def delete_by_website(self, tenant_id: str, website_id: str) -> int: ...

    async def list_chunks(
        self, tenant_id: str, website_id: str, *, limit: int = 0
    ) -> list[KnowledgeChunk]: ...

    async def list_chunks_light(
        self, tenant_id: str, website_id: str, *, limit: int = 0
    ) -> list[KnowledgeChunk]:
        """Like :pymethod:`list_chunks` but excludes embedding vectors.

        .. deprecated::
            This method is **dead code** — no production code path calls it.
            Keyword scoring was refactored to operate on vector-search results
            only, making the lightweight chunk load unnecessary.  Retained for
            potential future use and for test coverage.
        """

    async def similarity_search(
        self,
        tenant_id: str,
        website_id: str,
        query_embedding: list[float],
        *,
        top_k: int = 5,
        embedding_identity: EmbeddingIdentity | None = None,
    ) -> list[VectorSearchResult]: ...


__all__ = ["VectorRepository", "VectorSearchResult"]
