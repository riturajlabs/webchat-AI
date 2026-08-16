"""Non-Gemini AI providers (Phase 9, ADR-009).

Each provider implements one of the existing Protocols - `GenerationClient`
(`backend/ai/gemini.py`) or `EmbeddingClient`
(`backend/services/knowledge/embedding.py`) - so the RAG service and the
knowledge worker keep depending on those Protocols while the concrete provider
resolves through the Phase 9 registry/fallback chain.

Embedding providers are cloud-only (Gemini, Jina, Cohere): no local models,
no Ollama. Every provider emits the same vector dimension
(`EMBEDDING_DIMENSIONS`); a provider whose API key is missing is skipped at
registry build time (docs/EMBEDDING_PROVIDERS.md).
"""

from backend.ai.providers.cohere import CohereEmbeddingClient
from backend.ai.providers.groq import GroqGenerationClient
from backend.ai.providers.jina import JinaEmbeddingClient
from backend.ai.providers.openrouter import OpenRouterGenerationClient

__all__ = [
    "CohereEmbeddingClient",
    "GroqGenerationClient",
    "JinaEmbeddingClient",
    "OpenRouterGenerationClient",
]
