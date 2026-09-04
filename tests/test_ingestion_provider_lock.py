"""Focused tests for per-website ingestion embedding provider locking.

Covers:
* health-check selection of exactly ONE healthy provider before ingestion;
* persisting the selected provider/model/dimensions as the website's ingestion
  lock;
* every document/chunk of that ingestion using the locked provider (no mixed
  embedding identity);
* mid-ingestion quota/rate-limit marking documents rate_limited WITHOUT
  switching provider;
* a later retry re-checking the SAME locked provider and resuming with it
  (never silently switching providers).

Selection is exercised through `select_ingestion_embedding_provider` against a
fake `ProviderRegistry`; the processor-level behavior is exercised through a
recording `ProviderResolver` injected into `KnowledgeProcessor`.
"""

from typing import Any

import backend.ai.registry as registry_module
import pytest
from backend.ai.registry import ProviderRegistry, select_ingestion_embedding_provider
from backend.core.config import Settings
from backend.core.embedding_identity import EmbeddingIdentity
from backend.core.errors import (
    EmbeddingRateLimitedError,
    ProviderConfigurationError,
)
from backend.models.document import Document
from backend.models.knowledge_chunk import (
    KNOWLEDGE_STATUS_RATE_LIMITED,
)
from backend.models.website import Website
from backend.services.knowledge.embedding import EmbeddingUsage
from backend.services.knowledge.processor import KnowledgeProcessor

from tests.fakes import (
    FakeAuditLogRepository,
    FakeDocumentRepository,
    FakeKnowledgeChunkRepository,
    FakeUsageRecordRepository,
    FakeVectorRepository,
    FakeWebsiteRepository,
)

TEXT = "Alpha beta. Gamma delta. " * 40


# --------------------------------------------------------------------------- #
# Fake providers / resolver
# --------------------------------------------------------------------------- #


class Provider:
    """Fake embedding provider (registry-level): health + identity + embed."""

    def __init__(
        self,
        name: str,
        *,
        healthy: bool = True,
        dimensions: int = 1024,
    ) -> None:
        self.name = name
        self.healthy = healthy
        self.dimensions = dimensions
        self.model = f"{name}-embedding"
        self.health_calls = 0
        self.embed_calls = 0
        self._usage = EmbeddingUsage()

    @property
    def usage(self) -> EmbeddingUsage:
        return self._usage

    @property
    def embedding_identity(self) -> EmbeddingIdentity:
        return EmbeddingIdentity(
            provider=self.name,
            model=self.model,
            dimensions=self.dimensions,
            version="1",
        )

    async def health(self) -> bool:
        self.health_calls += 1
        return self.healthy

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.embed_calls += 1
        return [[0.1] * self.dimensions for _ in texts]


class RecordingResolver:
    """Processor-level resolver: honors a website's lock, else health-selects.

    Records how it resolved so tests can assert the provider is never silently
    switched mid-ingestion or on retry. `preferred_order` is the order a fresh
    (unlocked) selection would try - the default is insertion order of
    `providers`.
    """

    def __init__(
        self, providers: dict[str, Provider], preferred_order: list[str] | None = None
    ) -> None:
        self.providers = providers
        self.preferred_order = preferred_order or list(providers)
        self.selections: list[str] = []  # health-selected when no lock existed
        self.forced: list[str] = []  # forced from an existing website lock

    async def __call__(self, website: Website) -> Provider:
        locked = website.embedding_identity
        if locked is not None:
            self.forced.append(locked.provider)
            return self.providers[locked.provider]
        name = self.preferred_order[0]
        self.selections.append(name)
        return self.providers[name]


class FailOnRateLimit(Provider):
    """Provider that raises `EmbeddingRateLimitedError` on embed."""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.embed_calls += 1
        raise EmbeddingRateLimitedError(f"{self.name} is rate limited (429)")


class RecoveringRateLimit(Provider):
    """Provider that rate-limits the first `failures` calls, then succeeds.

    Models a quota window recovering between a failed pass and a user retry.
    """

    def __init__(self, name: str, *, failures: int = 1, **kw: Any) -> None:
        super().__init__(name, **kw)
        self._remaining_failures = failures
        self.fail_calls = 0

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.embed_calls += 1
        if self._remaining_failures > 0:
            self._remaining_failures -= 1
            self.fail_calls += 1
            raise EmbeddingRateLimitedError(f"{self.name} is rate limited (429)")
        return [[0.1] * self.dimensions for _ in texts]


# --------------------------------------------------------------------------- #
# Registry-level: provider selection / locking (no silent switch)
# --------------------------------------------------------------------------- #

_REQUIRED_KEYS = {
    "gemini": "gemini_api_key",
    "jina": "jina_api_key",
    "cohere": "cohere_api_key",
}


def _install_registry(monkeypatch: Any, providers: list[Provider]) -> None:
    registry = ProviderRegistry()
    for provider in providers:
        registry.register_embedding(
            provider.name,
            lambda p=provider: p,
            required_key=_REQUIRED_KEYS.get(provider.name),
        )
    monkeypatch.setattr(registry_module, "_registry", registry)


def _patch_settings(monkeypatch: Any, **overrides: Any) -> Settings:
    settings = Settings(_env_file=None, **overrides)
    monkeypatch.setattr(registry_module, "get_settings", lambda: settings)
    return settings


async def test_select_returns_first_healthy_provider(monkeypatch) -> None:
    gemini = Provider("gemini", healthy=False)
    jina = Provider("jina", healthy=True)
    cohere = Provider("cohere", healthy=True)
    _install_registry(monkeypatch, [gemini, jina, cohere])
    _patch_settings(
        monkeypatch,
        embedding_provider_order=["gemini", "jina", "cohere"],
        gemini_api_key="gk",
        jina_api_key="jk",
        cohere_api_key="ck",
    )

    client = await select_ingestion_embedding_provider()

    assert client is jina  # unhealthy gemini skipped -> jina selected
    assert gemini.health_calls == 1


async def test_select_force_provider_ignores_order_and_health(monkeypatch) -> None:
    gemini = Provider("gemini", healthy=True)
    jina = Provider("jina", healthy=True)
    _install_registry(monkeypatch, [jina, gemini])
    _patch_settings(
        monkeypatch,
        embedding_provider_order=["jina", "gemini"],
        gemini_api_key="gk",
        jina_api_key="jk",
    )

    # Locked to gemini even though jina is first/healthy: the lock wins.
    client = await select_ingestion_embedding_provider(force_provider="gemini")

    assert client is gemini
    assert jina.embed_calls == 0


async def test_select_force_provider_raises_when_locked_provider_unavailable(monkeypatch) -> None:
    """A website locked to a provider that is gone must NOT silently switch."""
    jina = Provider("jina", healthy=True)
    _install_registry(monkeypatch, [jina])
    _patch_settings(
        monkeypatch,
        embedding_provider_order=["jina"],
        jina_api_key="jk",
    )

    with pytest.raises(ProviderConfigurationError, match="no longer available"):
        await select_ingestion_embedding_provider(force_provider="gemini")


async def test_select_raises_when_no_healthy_provider(monkeypatch) -> None:
    gemini = Provider("gemini", healthy=False)
    jina = Provider("jina", healthy=False)
    _install_registry(monkeypatch, [gemini, jina])
    _patch_settings(
        monkeypatch,
        embedding_provider_order=["gemini", "jina"],
        gemini_api_key="gk",
        jina_api_key="jk",
    )

    with pytest.raises(ProviderConfigurationError, match="No healthy"):
        await select_ingestion_embedding_provider()
    assert jina.embed_calls == 0


# --------------------------------------------------------------------------- #
# Processor-level: lock persisted, no mixed identity, no silent switch
# --------------------------------------------------------------------------- #


async def _env(provider: Provider, resolver: RecordingResolver):
    documents = FakeDocumentRepository()
    vector = FakeVectorRepository()
    chunks = FakeKnowledgeChunkRepository(vector=vector)
    websites = FakeWebsiteRepository()
    audit = FakeAuditLogRepository()
    usage = FakeUsageRecordRepository()

    website = Website.new(tenant_id="tenant-a", name="Acme", url="https://acme.example/")
    await websites.create(website)
    document = Document.new(
        tenant_id="tenant-a",
        website_id=website.id,
        url="https://acme.example/",
        title="Home",
        content=TEXT,
        checksum="abc123",
    )
    await documents.upsert(document)

    processor = KnowledgeProcessor(
        documents=documents,
        vector=vector,
        chunks=chunks,
        websites=websites,
        audit=audit,
        embedder=provider,
        usage=usage,
        provider_resolver=resolver,
    )
    return {
        "documents": documents,
        "vector": vector,
        "chunks": chunks,
        "websites": websites,
        "audit": audit,
        "website": website,
        "document": document,
        "processor": processor,
    }


async def test_fanout_locks_provider_and_docs_share_one_identity() -> None:
    jina = Provider("jina")
    resolver = RecordingResolver({jina.name: jina})
    env = await _env(jina, resolver)

    queued: list[str] = []

    async def enqueue(document_id: str) -> None:
        queued.append(document_id)

    result = await env["processor"].process_website_documents(env["website"].id, enqueue=enqueue)

    assert result["status"] == "queued"
    # The selected provider was persisted as the website's ingestion lock.
    assert env["website"].embedding_identity == jina.embedding_identity
    assert env["websites"].websites[env["website"].id].embedding_identity == jina.embedding_identity
    # Fan-out health-selected (no lock yet), then a per-doc resolve forces the lock.
    assert resolver.selections == ["jina"]
    assert queued == [env["document"].id]


async def test_process_document_uses_locked_provider_and_stores_its_identity() -> None:
    jina = Provider("jina")
    resolver = RecordingResolver({jina.name: jina})
    env = await _env(jina, resolver)
    # Simulate a prior fan-out that already locked the website to jina.
    locked_website = env["websites"].websites[env["website"].id]
    locked_website.ingestion_embedding_provider = "jina"
    locked_website.ingestion_embedding_model = jina.model
    locked_website.ingestion_embedding_dimensions = jina.dimensions
    locked_website.ingestion_embedding_version = "1"

    result = await env["processor"].process_document(env["document"].id)

    assert result["status"] == "processed"
    assert resolver.forced == ["jina"]  # lock forced, not re-selected
    assert resolver.selections == []
    stored = env["vector"].by_document(env["document"].tenant_id, env["document"].id)
    assert stored
    for chunk in stored:
        assert (chunk.embedding_provider, chunk.embedding_model, chunk.embedding_dimensions) == (
            "jina",
            jina.model,
            jina.dimensions,
        )
    # The lock is recorded on the website.
    assert env["websites"].websites[env["website"].id].ingestion_embedding_provider == "jina"


async def test_mid_ingestion_rate_limit_marks_rate_limited_no_switch() -> None:
    gemini = FailOnRateLimit("gemini")
    jina = Provider("jina")
    resolver = RecordingResolver({gemini.name: gemini, jina.name: jina})
    env = await _env(gemini, resolver)
    # Fan-out selects gemini (first) and locks it.
    queued: list[str] = []

    async def enqueue(document_id: str) -> None:
        queued.append(document_id)

    await env["processor"].process_website_documents(env["website"].id, enqueue=enqueue)
    assert (
        env["websites"].websites[env["website"].id].embedding_identity == gemini.embedding_identity
    )

    # Per-doc processing hits the locked provider's quota mid-ingestion.
    result = await env["processor"].process_document(env["document"].id)

    # Marked rate_limited (non-terminal), NOT failed to another provider.
    assert (
        env["documents"].documents[env["document"].id].knowledge_status
        == KNOWLEDGE_STATUS_RATE_LIMITED
    )
    assert result["status"] in ("failed", "retry_scheduled")
    # The provider was forced from the lock; gemini never switched to jina.
    assert resolver.forced == ["gemini"]
    assert jina.embed_calls == 0
    assert gemini.embed_calls == 1


async def test_retry_honors_lock_over_healthy_alternative() -> None:
    jina = Provider("jina")
    gemini = Provider("gemini")
    # A fresh (unlocked) selection would prefer gemini, but the website is
    # already locked to jina - so the retry must use jina, never gemini.
    resolver = RecordingResolver(
        {jina.name: jina, gemini.name: gemini}, preferred_order=[gemini.name]
    )
    env = await _env(jina, resolver)
    locked = env["websites"].websites[env["website"].id]
    locked.ingestion_embedding_provider = "jina"
    locked.ingestion_embedding_model = jina.model
    locked.ingestion_embedding_dimensions = jina.dimensions
    locked.ingestion_embedding_version = "1"

    result = await env["processor"].process_document(env["document"].id)

    assert result["status"] == "processed"
    assert resolver.forced == ["jina"]  # lock forced the prior provider
    assert resolver.selections == []  # no fresh health-selection happened
    assert gemini.embed_calls == 0  # healthy alternative never consulted
    stored = env["vector"].by_document(env["document"].tenant_id, env["document"].id)
    assert stored and all(chunk.embedding_provider == "jina" for chunk in stored)


async def test_retry_after_quota_recovery_stays_on_locked_provider() -> None:
    gemini = RecoveringRateLimit("gemini", failures=1)
    jina = Provider("jina")
    # A fresh selection would pick jina, but the website is ALREADY locked to
    # gemini (e.g. it was selected on the previous pass) - so the retry keeps
    # gemini even though jina is healthy and first.
    resolver = RecordingResolver(
        {gemini.name: gemini, jina.name: jina}, preferred_order=[jina.name]
    )
    env = await _env(gemini, resolver)
    locked = env["websites"].websites[env["website"].id]
    locked.ingestion_embedding_provider = "gemini"
    locked.ingestion_embedding_model = gemini.model
    locked.ingestion_embedding_dimensions = gemini.dimensions
    locked.ingestion_embedding_version = "1"

    # First pass: the locked provider rate-limits -> doc marked rate_limited,
    # provider NOT switched to jina.
    await env["processor"].process_document(env["document"].id)
    assert resolver.forced == ["gemini"]
    assert jina.embed_calls == 0
    assert gemini.fail_calls == 1

    # User retries later: gemini's quota recovered; the SAME locked provider is
    # still forced (never re-selected to jina) and now succeeds.
    result = await env["processor"].process_document(env["document"].id)

    assert result["status"] == "processed"
    assert resolver.forced == ["gemini", "gemini"]
    assert resolver.selections == []
    assert jina.embed_calls == 0
    assert gemini.embed_calls == 2
    stored = env["vector"].by_document(env["document"].tenant_id, env["document"].id)
    assert stored and all(chunk.embedding_provider == "gemini" for chunk in stored)
