"""Non-Gemini AI providers (Phase 9, ADR-009).

Each provider implements one of the existing Protocols - `GenerationClient`
(`backend/ai/gemini.py`) or `EmbeddingClient`
(`backend/services/knowledge/embedding.py`) - so the RAG service and the
knowledge worker keep depending on those Protocols while the concrete provider
resolves through the Phase 9 registry/fallback chain.
"""

from backend.ai.providers.groq import GroqGenerationClient
from backend.ai.providers.ollama import OllamaEmbeddingClient
from backend.ai.providers.openrouter import OpenRouterGenerationClient

__all__ = ["GroqGenerationClient", "OllamaEmbeddingClient", "OpenRouterGenerationClient"]
