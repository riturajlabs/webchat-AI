"""Deterministic in-process AI providers for local/performance runs.

`MockGenerationClient` and `MockEmbeddingClient` implement the same
`GenerationClient` / `EmbeddingClient` Protocols as the real providers, but
never touch the network and never require an API key. They are *not* part of
the default provider order: the registry registers them keyless so an operator
can opt in explicitly via `GENERATION_PROVIDER_ORDER`/`EMBEDDING_PROVIDER_ORDER`
(e.g. for load tests and offline development). Output is deterministic so
repeat runs are comparable; the embedding vectors are text-hashed so identical
texts always yield identical vectors (giving cosine search meaningful signal).
"""

import asyncio
import hashlib
import random
import zlib
from collections.abc import AsyncIterator
from dataclasses import dataclass

from backend.ai.gemini import GenerationUsage
from backend.core.config import get_settings
from backend.services.knowledge.embedding import EmbeddingIdentity, EmbeddingUsage

# Fixed answer streamed to every mock request. Deterministic and short so load
# tests measure the pipeline rather than generation.
_MOCK_ANSWER = (
    "This is a deterministic mock answer for load testing. "
    "It exercises the streaming, retrieval and persistence pipeline "
    "without contacting any external AI provider."
)

# Rough token estimate: ~4 chars per token.
_CHARS_PER_TOKEN = 4


@dataclass(frozen=True)
class MockEmbeddingClientConfig:
    """Configuration for `MockEmbeddingClient` (kept dependency-light)."""

    dimensions: int = 3072


class MockGenerationClient:
    """Deterministic streaming generation (no network, no API key)."""

    name = "mock"

    def __init__(
        self,
        *,
        chunk_delay_seconds: float = 0.0,
        words_per_chunk: int = 4,
    ) -> None:
        self._chunk_delay_seconds = chunk_delay_seconds
        self._words_per_chunk = max(1, words_per_chunk)
        self._usage = GenerationUsage()

    @property
    def usage(self) -> GenerationUsage:
        return self._usage

    async def stream_generate(
        self,
        *,
        system: str,
        messages: list[tuple[str, str]],
    ) -> AsyncIterator[str]:
        reply = self._reply_for(messages)
        self._usage = GenerationUsage(
            input_tokens=self._estimate_tokens(system, messages),
            output_tokens=max(1, len(reply) // _CHARS_PER_TOKEN),
        )
        words = reply.split()
        for start in range(0, len(words), self._words_per_chunk):
            if self._chunk_delay_seconds > 0:
                await asyncio.sleep(self._chunk_delay_seconds)
            yield " ".join(words[start : start + self._words_per_chunk])

    @staticmethod
    def _estimate_tokens(system: str, messages: list[tuple[str, str]]) -> int:
        total = len(system)
        for _, text in messages:
            total += len(text)
        return max(1, total // _CHARS_PER_TOKEN)

    @staticmethod
    def _reply_for(messages: list[tuple[str, str]]) -> str:
        """Deterministic-but-question-sensitive answer.

        The seed is derived from the last user turn only, so the answer is
        stable for repeated identical prompts (comparable load-test runs) while
        still varying across distinct prompts.
        """
        user_text = ""
        for role, text in reversed(messages):
            if role == "user":
                user_text = text
                break
        seed = zlib.crc32(user_text.encode("utf-8"))
        return f"[{seed & 0xFFFF:04x}] {_MOCK_ANSWER}"


class MockEmbeddingClient:
    """Deterministic hashed embeddings (no network, no API key).

    Vectors are unit-length so cosine similarity is well defined. Identical
    input text produces an identical vector within a process (the seed uses
    `zlib.crc32`, which is stable across processes too).
    """

    name = "mock"

    def __init__(self, *, dimensions: int | None = None) -> None:
        settings = get_settings()
        self._dimensions = dimensions if dimensions is not None else settings.embedding_dimensions
        self._usage = EmbeddingUsage()

    @property
    def usage(self) -> EmbeddingUsage:
        return self._usage

    @property
    def dimensions(self) -> int:
        """Vector length (registry dimension-compatibility check)."""
        return self._dimensions

    @property
    def embedding_identity(self) -> EmbeddingIdentity:
        return EmbeddingIdentity(
            provider=self.name,
            model="mock-embedding",
            dimensions=self._dimensions,
            version=getattr(get_settings(), "embedding_version", "1"),
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = [self._vector(text) for text in texts]
        self._usage = EmbeddingUsage(
            calls=self._usage.calls + (1 if texts else 0),
            characters=self._usage.characters + sum(len(text) for text in texts),
            estimated_tokens=self._usage.estimated_tokens
            + sum(max(1, len(text) // _CHARS_PER_TOKEN) for text in texts),
            failures=self._usage.failures,
        )
        return vectors

    def _vector(self, text: str) -> list[float]:
        """A deterministic, text-dependent, unit-length vector."""
        seed = zlib.crc32(text.encode("utf-8"))
        digest = hashlib.blake2b(f"{seed}:{self._dimensions}".encode(), digest_size=8).digest()
        rng = random.Random(digest)
        values = [rng.uniform(-1.0, 1.0) for _ in range(self._dimensions)]
        norm = sum(v * v for v in values) ** 0.5
        if norm == 0.0:
            return [0.0] * self._dimensions
        return [v / norm for v in values]


__all__ = ["MockEmbeddingClient", "MockEmbeddingClientConfig", "MockGenerationClient"]
