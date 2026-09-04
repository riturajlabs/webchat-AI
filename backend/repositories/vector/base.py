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
    """One vector-search hit with its similarity score.

    ``lexical_score`` holds explicit keyword/RRF retrieval evidence (on a
    different scale than the cosine ``score``) when a chunk was recovered by
    the hybrid keyword pass. It is ``None`` for candidates whose only evidence
    is vector cosine. It is intended purely as structured evidence for
    score-type-aware context gating; it never replaces ``score``.
    """

    chunk: KnowledgeChunk
    score: float
    lexical_score: float | None = None
    dense_score: float | None = None
    lexical_exact: bool = False


class VectorRepository(Protocol):
    """Write/delete/search operations over embedded knowledge chunks."""

    async def insert_chunks(self, chunks: list[KnowledgeChunk]) -> int: ...

    async def replace_by_document(
        self, tenant_id: str, document_id: str, chunks: list[KnowledgeChunk]
    ) -> int:
        """Atomically replace a document's chunks with `chunks`.

        The intended safety contract (P1): a document must never be reduced to
        zero/partial chunks by a failed replacement. The reference
        implementation inserts the new chunks FIRST (upserting on the unique
        tenant/website/document/index key) and only then deletes the document's
        stale chunk indexes that are no longer produced. A mid-replacement
        failure therefore leaves the previous chunks (or a superset) in place
        instead of the current delete-then-insert window which can leave zero
        chunks. Returns the number of chunks newly inserted.
        """

    async def delete_by_document(self, tenant_id: str, document_id: str) -> int: ...

    async def delete_by_website(self, tenant_id: str, website_id: str) -> int: ...

    async def list_chunks(
        self, tenant_id: str, website_id: str, *, limit: int = 0
    ) -> list[KnowledgeChunk]: ...

    async def list_chunks_light(
        self, tenant_id: str, website_id: str, *, limit: int = 0
    ) -> list[KnowledgeChunk]:
        """Like :pymethod:`list_chunks` but excludes embedding vectors.

        The hybrid keyword corpus load in ``RagService._load_all_chunks`` uses
        this so keyword scoring (which only needs chunk text/metadata) does not
        transfer the large embedding payload.
        """

    async def get_chunks_by_ids(
        self, tenant_id: str, website_id: str, ids: list[str]
    ) -> list[KnowledgeChunk]:
        """Fetch full documents (including embeddings) for a set of chunk ids.

        Used to hydrate embeddings onto the small reranker candidate pool that
        the embedding-free keyword corpus load cannot otherwise provide, so the
        reranker's stored-embedding cosine scoring (and its strong-lexical
        protection) work exactly as before.

        Defense-in-depth: the fetch is scoped by must tenant ID and website ID
        in addition to the chunk ids, so a caller can never retrieve chunks
        that live outside its tenant/website even if it holds raw ``_id`` values
        (e.g. from a keyword corpus load). Returns only chunks that satisfy all
        three predicates.
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
