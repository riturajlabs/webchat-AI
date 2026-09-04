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

import asyncio
import inspect
import logging
import time
from collections.abc import Callable, Sequence

from backend.ai.gemini import GenerationClient, GoogleGeminiClient
from backend.ai.mock import MockEmbeddingClient, MockGenerationClient
from backend.ai.providers.cohere import CohereEmbeddingClient
from backend.ai.providers.groq import GroqGenerationClient
from backend.ai.providers.jina import JinaEmbeddingClient
from backend.ai.providers.openrouter import OpenRouterGenerationClient
from backend.ai.router import FallbackEmbeddingClient, FallbackGenerationClient
from backend.core.config import get_settings
from backend.core.embedding_identity import EmbeddingIdentity
from backend.core.errors import ProviderConfigurationError
from backend.services.ai.provider_health import ProviderHealthStore, provider_health_name
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


def build_generation_providers() -> list[GenerationClient]:
    """Build the raw generation provider list for the adaptive router.

    Returns concrete client instances (not wrapped in FallbackGenerationClient)
    so the adaptive router can wrap them itself and reorder per-request.
    """
    order = get_settings().generation_provider_order
    return _registry.build_generation_chain(order)


def build_embedding_fallback(
    max_retries: int | None = None,
) -> FallbackEmbeddingClient:
    """Build the configured embedding fallback chain (ADR-009).

    Pass `max_retries` (e.g. `settings.chat_embedding_max_retries`) from the
    chat path so a hung embedding provider fails fast into the next one.
    """
    order = get_settings().embedding_provider_order
    return FallbackEmbeddingClient(_registry.build_embedding_chain(order, max_retries=max_retries))


def build_ingestion_embedding_client() -> EmbeddingClient:
    """Build the single embedding provider ingestion writes with (BUG-1 fix).

    Ingestion must never switch embedding spaces mid-corpus: providers that
    agree on `EMBEDDING_DIMENSIONS` still live in incompatible vector spaces,
    so a Gemini->Jina failover while storing chunks stamps a website with two
    identities and makes one of them invisible to every identity-filtered
    `$vectorSearch`. This resolves the configured order exactly like
    `build_embedding_fallback` (keyless providers are skipped) but returns only
    the first available provider. If it fails, the provider's own retries and
    the processor's document-level backoff retry the SAME provider; exhausted
    retries quarantine the document instead of corrupting the corpus.
    """
    order = get_settings().embedding_provider_order
    chain = _registry.build_embedding_chain(order)
    if not chain:
        raise ProviderConfigurationError(
            "No embedding provider is available for ingestion; configure at "
            "least one keyed provider in EMBEDDING_PROVIDER_ORDER."
        )
    return chain[0]


def _instantiate(factory: EmbeddingFactory, max_retries: int | None) -> EmbeddingClient:
    """Build a provider, forwarding `max_retries` only when it accepts it."""
    if max_retries is None or "max_retries" not in inspect.signature(factory).parameters:
        return factory()
    return factory(max_retries=max_retries)


async def _is_healthy(provider: EmbeddingClient) -> bool:
    """Non-raising readiness probe used by provider selection at fan-out.

    Providers that expose a `health()` method (all of them) are probed; a
    provider that reports unhealthy (e.g. a rate-limited/failed probe, or
    missing/cleared config) is skipped during selection so a quota-exhausted
    provider is never chosen for a fresh ingestion. A probe failure never
    crashes selection - it just rules that provider out.
    """
    probe = getattr(provider, "health", None)
    if probe is None:
        # Provider with no probe: it passed the key gate in build_embedding_chain.
        return True
    try:
        return bool(await probe())
    except Exception:  # noqa: BLE001 - a probe failure only rules one out
        logger.warning(
            "embedding provider %r failed its health probe during ingestion "
            "selection; skipping it.",
            getattr(provider, "name", "?"),
        )
        return False


async def select_ingestion_embedding_provider(
    *,
    force_provider: str | None = None,
    health: ProviderHealthStore | None = None,
) -> EmbeddingClient:
    """Health-check the configured embedding providers and return exactly ONE
    for a website's ingestion, honoring a per-website provider lock.

    The selected provider is locked to the website for the whole ingestion
    (persisted on the website record): every document and every retry resolves
    through this same function with `force_provider`, so the embedding space
    never changes.

    * When `force_provider` is set (the website is already locked) that exact
      provider is returned - the configured order and health are not consulted
      for selection, so a retry resumes in the SAME embedding space. If the
      locked provider can no longer be built (API key removed / renamed /
      disabled) this raises instead of silently switching to another provider.
    * Without a lock, the available (keyed) providers are health-checked in
      configured order and the first healthy one is selected.
    """
    chain = _registry.build_embedding_chain(get_settings().embedding_provider_order)
    if not chain:
        raise ProviderConfigurationError(
            "No embedding provider is available for ingestion; configure at "
            "least one keyed provider in EMBEDDING_PROVIDER_ORDER."
        )
    if force_provider is not None:
        for provider in chain:
            if provider.name == force_provider:
                return provider
        raise ProviderConfigurationError(
            f"Website is locked to embedding provider {force_provider!r}, which is "
            "no longer available. Refusing to switch embedding spaces mid-ingestion; "
            "re-index the website to select a new provider."
        )
    # No lock yet: health-check in configured order, take the first healthy one.
    for provider in chain:
        health_name = provider_health_name("embedding", provider.name)
        if health is not None and not await health.is_available(health_name):
            continue
        started = time.perf_counter()
        try:
            is_healthy = await asyncio.wait_for(_is_healthy(provider), timeout=2.0)
        except TimeoutError:
            is_healthy = False
        if is_healthy:
            if health is not None:
                await health.record_success(health_name, (time.perf_counter() - started) * 1000.0)
            return provider
        if health is not None:
            await health.record_failure(health_name)
    provider_names = ", ".join(p.name for p in chain) or "none"
    raise ProviderConfigurationError(
        f"No healthy embedding provider is available for ingestion (checked: {provider_names})."
    )


def build_locked_embedding_client(identity: EmbeddingIdentity) -> EmbeddingClient:
    """Build exactly the client matching a persisted corpus identity.

    This intentionally has no fallback: vectors from different providers or
    model revisions inhabit different spaces even when their dimensions match.
    """
    for provider in _registry.build_embedding_chain(get_settings().embedding_provider_order):
        if provider.name != identity.provider:
            continue
        if provider.embedding_identity != identity:
            raise ProviderConfigurationError(
                "Configured embedding provider no longer matches the website corpus identity; "
                "re-index the whole website before serving retrieval."
            )
        return provider
    raise ProviderConfigurationError(
        f"Website is locked to embedding provider {identity.provider!r}, which is unavailable."
    )


__all__ = [
    "ProviderRegistry",
    "build_embedding_fallback",
    "build_generation_fallback",
    "build_generation_providers",
    "build_ingestion_embedding_client",
    "build_locked_embedding_client",
    "select_ingestion_embedding_provider",
]
