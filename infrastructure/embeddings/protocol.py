"""Re-exports embedding contracts for infrastructure subsystem."""

from __future__ import annotations

from contracts.embeddings import (
    EmbeddingModelMetadata,
    EmbeddingProvider,
    EmbeddingProviderUnavailableError,
    register_embedding_resolver,
    resolve_embedding_provider,
)

__all__ = [
    "EmbeddingModelMetadata",
    "EmbeddingProvider",
    "EmbeddingProviderUnavailableError",
    "register_embedding_resolver",
    "resolve_embedding_provider",
]
