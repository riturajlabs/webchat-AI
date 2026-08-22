"""Embedding-space identity shared by ingestion, retrieval, and storage."""

from dataclasses import asdict, dataclass
from typing import Any

from backend.core.errors import EmbeddingCompatibilityError


@dataclass(frozen=True)
class EmbeddingIdentity:
    """The compatibility contract for vectors in one embedding space."""

    provider: str
    model: str
    dimensions: int
    version: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def ensure_embedding_compatibility(chunk: Any, identity: EmbeddingIdentity) -> None:
    """Reject a stored chunk that belongs to another embedding space."""
    actual = (
        getattr(chunk, "embedding_provider", None),
        getattr(chunk, "embedding_model", None),
        getattr(chunk, "embedding_dimensions", None),
        getattr(chunk, "embedding_version", None),
    )
    expected = (
        identity.provider,
        identity.model,
        identity.dimensions,
        identity.version,
    )
    if actual != expected:
        raise EmbeddingCompatibilityError(
            "Stored knowledge chunk embedding identity is incompatible with the "
            f"active query embedding (stored={actual}, query={expected}). Re-index "
            "the website with one consistent embedding provider and model."
        )


__all__ = ["EmbeddingIdentity", "ensure_embedding_compatibility"]
