"""Knowledge processing services (Phase 5, ADR-008).

`KnowledgeProcessor` turns crawled documents into embedded knowledge chunks;
`chunker` and `embedding` provide the token chunking and embedding client used
by the processor (and by Phase 6 retrieval).
"""

from backend.services.knowledge.chunker import TextChunk, chunk_text, count_tokens
from backend.services.knowledge.embedding import (
    EmbeddingClient,
    EmbeddingUsage,
    GoogleEmbeddingClient,
)
from backend.services.knowledge.processor import KnowledgeProcessor

__all__ = [
    "EmbeddingClient",
    "EmbeddingUsage",
    "GoogleEmbeddingClient",
    "KnowledgeProcessor",
    "TextChunk",
    "chunk_text",
    "count_tokens",
]
