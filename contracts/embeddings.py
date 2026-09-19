"""Contracts and protocols for semantic embedding providers.

Defines the dependency-free boundary for embedding models, metadata models,
and resolver dispatch. Allows core components to interact with embeddings
without importing concrete infrastructure backends.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from sdk.domain_config import MatchStrategyConfig


class EmbeddingModelMetadata(BaseModel):
    """Immutable audit metadata recorded for every embedding operation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_id: str = Field(
        description="Unique model identifier (e.g. HuggingFace repo ID or Ollama tag)"
    )
    provider_type: str = Field(
        description="Provider implementation ('ollama', 'huggingface', 'test_double')"
    )
    dimensions: int = Field(ge=1, description="Dimensionality of vectors produced by this model")
    model_digest: str = Field(
        default="", description="Digest or checksum of the model configuration/weights"
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Operational parameters (batch size, pooling, etc.)",
    )


class EmbeddingProviderUnavailableError(RuntimeError):
    """Raised when an embedding provider cannot reach its service or load its model weights.

    Guarantees strict fail-closed behavior: no silent fallback to lexical string matching.
    """


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Protocol implemented by all embedding providers."""

    @property
    def model_id(self) -> str:
        """The identifier of the active embedding model."""
        ...

    @property
    def provider_type(self) -> str:
        """The category of this provider ('ollama', 'huggingface', 'test_double')."""
        ...

    @property
    def dimensions(self) -> int:
        """The vector dimension produced by this model."""
        ...

    def is_available(self) -> bool:
        """Check if the provider and model are reachable and ready for inference."""
        ...

    def embed(self, texts: list[str]) -> list[tuple[float, ...]]:
        """Compute unit-normalized embedding vectors for a list of text surfaces.

        Args:
            texts: List of strings to embed.

        Returns:
            List of L2-normalized float tuples of length `self.dimensions`.

        Raises:
            EmbeddingProviderUnavailableError: If the model or backend fails or is unreachable.
        """
        ...

    def get_metadata(self) -> EmbeddingModelMetadata:
        """Return the immutable audit metadata for this provider and model."""
        ...


_RESOLVER_LOCK = threading.Lock()
_RESOLVER: Callable[[MatchStrategyConfig], EmbeddingProvider] | None = None


def register_embedding_resolver(
    resolver: Callable[[MatchStrategyConfig], EmbeddingProvider],
) -> None:
    """Register the active embedding provider resolver function."""
    global _RESOLVER
    with _RESOLVER_LOCK:
        _RESOLVER = resolver


def resolve_embedding_provider(strategy: MatchStrategyConfig) -> EmbeddingProvider:
    """Resolve an embedding provider via the registered resolver."""
    with _RESOLVER_LOCK:
        resolver = _RESOLVER
    if resolver is None:
        raise EmbeddingProviderUnavailableError(
            "No embedding resolver registered. Infrastructure backend not initialized."
        )
    return resolver(strategy)
