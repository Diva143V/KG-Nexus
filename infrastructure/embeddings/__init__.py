"""Semantic Embedding Subsystem.

Provides typed, fail-closed embedding providers for general and domain-specific
knowledge graph entity alignment and candidate matching.
"""

from __future__ import annotations

from infrastructure.embeddings.huggingface_provider import HuggingFaceEmbeddingProvider
from infrastructure.embeddings.ollama_provider import OllamaEmbeddingProvider
from infrastructure.embeddings.protocol import (
    EmbeddingModelMetadata,
    EmbeddingProvider,
    EmbeddingProviderUnavailableError,
)
from infrastructure.embeddings.resolver import (
    get_embedding_provider,
    set_override_embedding_provider,
)
from infrastructure.embeddings.test_provider import DeterministicTestEmbeddingProvider

__all__ = [
    "DeterministicTestEmbeddingProvider",
    "EmbeddingModelMetadata",
    "EmbeddingProvider",
    "EmbeddingProviderUnavailableError",
    "HuggingFaceEmbeddingProvider",
    "OllamaEmbeddingProvider",
    "get_embedding_provider",
    "set_override_embedding_provider",
]
