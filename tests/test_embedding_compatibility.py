"""Embedding-space compatibility tests for ingestion and retrieval guards."""

import pytest
from backend.core.errors import EmbeddingCompatibilityError, EmbeddingError
from backend.models.knowledge_chunk import KnowledgeChunk
from backend.services.knowledge.embedding import (
    EmbeddingIdentity,
    ensure_embedding_compatibility,
    ensure_vector_dimensions,
)

IDENTITY = EmbeddingIdentity(
    provider="gemini",
    model="gemini-embedding-001",
    dimensions=1024,
    version="1",
)


def _chunk(identity: EmbeddingIdentity = IDENTITY) -> KnowledgeChunk:
    return KnowledgeChunk.new(
        tenant_id="tenant-a",
        website_id="site-a",
        document_id="doc-a",
        chunk_text="content",
        embedding=[0.0] * identity.dimensions,
        chunk_index=0,
        embedding_provider=identity.provider,
        embedding_model=identity.model,
        embedding_dimensions=identity.dimensions,
        embedding_version=identity.version,
    )


def test_same_embedding_model_is_compatible() -> None:
    ensure_embedding_compatibility(_chunk(), IDENTITY)


def test_different_embedding_model_is_blocked() -> None:
    incompatible = EmbeddingIdentity(
        provider="jina",
        model="jina-embeddings-v3",
        dimensions=1024,
        version="1",
    )

    with pytest.raises(EmbeddingCompatibilityError, match="incompatible"):
        ensure_embedding_compatibility(_chunk(incompatible), IDENTITY)


def test_dimension_mismatch_fails() -> None:
    with pytest.raises(EmbeddingError, match="dimensions"):
        ensure_vector_dimensions("gemini", [[0.0] * 1024, [0.0] * 768], 1024)
