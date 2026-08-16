"""AI provider registry (Phase 9, ADR-009).

Maps provider names to client factories and builds the configured fallback
chains consumed by `router.FallbackGenerationClient`/
`FallbackEmbeddingClient`. Providers whose required API key is missing are
skipped (with a warning) so one unconfigured provider cannot break the whole
chain; an unknown name in `*_PROVIDER_ORDER` is a configuration error and
fails fast. Embedding chains additionally warn when their providers report
differing vector dimensions, because switching embedding providers on a mixed
corpus corrupts `$vectorSearch`; the configured `EMBEDDING_DIMENSIONS` must
match every provider in the order (validated in `backend/core/config.py`).
"""

import inspect
import logging
from collections.abc import Callable, Sequence

from backend.ai.gemini import GenerationClient, GoogleGeminiClient
from backend.ai.mock import MockEmbeddingClient, MockGenerationClient
from backend.ai.providers.cohere import CohereEmbeddingClient
from backend.ai.providers.groq import GroqGenerationClient
from backend.ai.providers.jina import JinaEmbeddingClient
from backend.ai.providers.openrouter import OpenRouterGenerationClient
from backend.ai.router import FallbackEmbeddingClient, FallbackGenerationClient
from backend.core.config import get_settings
from backend.core.errors import ProviderConfigurationError
from backend.services.knowledge.embedding import EmbeddingClient, GoogleEmbeddingClient

logger = logging.getLogger("webchat_ai")

GenerationFactory = Callable[[], GenerationClient]
# Embedding factories accept the retry-capable client's optional kwargs
# (e.g. `max_retries`) - `_instantiate` forwards them only when the factory
# signature accepts them.
EmbeddingFactory = Callable[..., EmbeddingClient]


class ProviderRegistry:
    """Registry of AI provider factories keyed by provider name."""

    def __init__(self) -> None:
        self._generation: dict[str, tuple[GenerationFactory, str | None]] = {}
        self._embedding: dict[str, tuple[EmbeddingFactory, str | None]] = {}

    def register_generation(
        self,
        name: str,
        factory: GenerationFactory,
        *,
        required_key: str | None = None,
    ) -> None:
        """Register a generation provider. `required_key` names the settings
        field whose presence gates the provider (skipped when empty)."""
        self._generation[name] = (factory, required_key)

    def register_embedding(
        self,
        name: str,
        factory: EmbeddingFactory,
        *,
        required_key: str | None = None,
    ) -> None:
        """Register an embedding provider. `required_key` gates availability."""
        self._embedding[name] = (factory, required_key)

    def generation_names(self) -> list[str]:
        return sorted(self._generation)

    def embedding_names(self) -> list[str]:
        return sorted(self._embedding)

    def build_generation_chain(self, order: Sequence[str]) -> list[GenerationClient]:
        """Resolve `order` into concrete generation clients (skipping unkeyed)."""
        chain: list[GenerationClient] = []
        for name in order:
            entry = self._generation.get(name)
            if entry is None:
                raise ProviderConfigurationError(
                    f"Unknown generation provider {name!r}. "
                    f"Known providers: {', '.join(self.generation_names()) or 'none'}."
                )
            factory, required_key = entry
            if required_key and not getattr(get_settings(), required_key, None):
                logger.warning(
                    "generation provider %r is configured in GENERATION_PROVIDER_ORDER but "
                    "%s is missing; skipping.",
                    name,
                    required_key.upper(),
                )
                continue
            chain.append(factory())
        return chain

    def build_embedding_chain(
        self,
        order: Sequence[str],
        *,
        max_retries: int | None = None,
    ) -> list[EmbeddingClient]:
        """Resolve `order` into concrete embedding clients (skipping unkeyed).

        `max_retries` is passed to providers that accept it (e.g.
        `GoogleEmbeddingClient`): the chat path uses a tight per-provider retry
        budget so a hung provider fails fast into the next one, while ingestion
        leaves it `None` and keeps the client's configured default.
        """
        chain: list[EmbeddingClient] = []
        dimensions: set[int] = set()
        for name in order:
            entry = self._embedding.get(name)
            if entry is None:
                raise ProviderConfigurationError(
                    f"Unknown embedding provider {name!r}. "
                    f"Known providers: {', '.join(self.embedding_names()) or 'none'}."
                )
            factory, required_key = entry
            if required_key and not getattr(get_settings(), required_key, None):
                logger.warning(
                    "embedding provider %r is configured in EMBEDDING_PROVIDER_ORDER but "
                    "%s is missing; skipping.",
                    name,
                    required_key.upper(),
                )
                continue
            provider = _instantiate(factory, max_retries)
            chain.append(provider)
            dims = getattr(provider, "dimensions", None)
            if isinstance(dims, int):
                dimensions.add(dims)
        if len(dimensions) > 1:
            logger.warning(
                "embedding providers in EMBEDDING_PROVIDER_ORDER report differing vector "
                "dimensions %s; switching providers corrupts $vectorSearch. Configure a "
                "single provider or providers with matching dimensions.",
                sorted(dimensions),
            )
        return chain


# Default registry: the built-in providers. Tests may instantiate their own
# registry or extend this one via register_*.
_registry = ProviderRegistry()
_registry.register_generation("gemini", GoogleGeminiClient, required_key="gemini_api_key")
_registry.register_generation("groq", GroqGenerationClient, required_key="groq_api_key")
_registry.register_generation(
    "openrouter", OpenRouterGenerationClient, required_key="openrouter_api_key"
)
_registry.register_embedding("gemini", GoogleEmbeddingClient, required_key="gemini_api_key")
# Cloud embedding fallbacks (ADR-009): skipped when their API key is missing.
_registry.register_embedding("jina", JinaEmbeddingClient, required_key="jina_api_key")
_registry.register_embedding("cohere", CohereEmbeddingClient, required_key="cohere_api_key")
# Mock is deterministic and keyless; only used when explicitly configured in
# the provider order (offline dev / performance runs, never the default).
_registry.register_generation("mock", MockGenerationClient)
_registry.register_embedding("mock", MockEmbeddingClient)


def build_generation_fallback() -> FallbackGenerationClient:
    """Build the configured generation fallback chain (ADR-009)."""
    order = get_settings().generation_provider_order
    return FallbackGenerationClient(_registry.build_generation_chain(order))


def build_embedding_fallback(
    max_retries: int | None = None,
) -> FallbackEmbeddingClient:
    """Build the configured embedding fallback chain (ADR-009).

    Pass `max_retries` (e.g. `settings.chat_embedding_max_retries`) from the
    chat path so a hung embedding provider fails fast into the next one.
    """
    order = get_settings().embedding_provider_order
    return FallbackEmbeddingClient(_registry.build_embedding_chain(order, max_retries=max_retries))


def _instantiate(factory: EmbeddingFactory, max_retries: int | None) -> EmbeddingClient:
    """Build a provider, forwarding `max_retries` only when it accepts it."""
    if max_retries is None or "max_retries" not in inspect.signature(factory).parameters:
        return factory()
    return factory(max_retries=max_retries)


__all__ = [
    "ProviderRegistry",
    "build_embedding_fallback",
    "build_generation_fallback",
]
