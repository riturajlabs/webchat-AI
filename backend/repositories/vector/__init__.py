"""Vector store repositories (00-AI-Development-Rules.md §13).

Application code depends on the `VectorRepository` Protocol only - never
directly on MongoDB Vector Search. The factory binds the configured backend;
today that is `MongoVectorRepository` (Atlas `$vectorSearch`), and Qdrant /
Pinecone / Weaviate can be added behind the same interface.
"""

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.repositories.vector.base import VectorRepository, VectorSearchResult
from backend.repositories.vector.hybrid import (
    HybridSearcher,
    keyword_search,
    reciprocal_rank_fusion,
)
from backend.repositories.vector.mongodb import MongoVectorRepository


def get_vector_repository(db: AsyncIOMotorDatabase[Any]) -> VectorRepository:
    """Build the configured vector repository (currently Atlas Vector Search)."""
    return MongoVectorRepository(db)


__all__ = [
    "HybridSearcher",
    "MongoVectorRepository",
    "VectorRepository",
    "VectorSearchResult",
    "get_vector_repository",
    "keyword_search",
    "reciprocal_rank_fusion",
]
