"""Resolver and factory for embedding providers.

Selects and instantiates the appropriate embedding provider based on domain
and match strategy configuration, enforcing strict fail-closed availability.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from contracts.embeddings import register_embedding_resolver
from infrastructure.embeddings.huggingface_provider import HuggingFaceEmbeddingProvider
from infrastructure.embeddings.ollama_provider import OllamaEmbeddingProvider
from infrastructure.embeddings.protocol import (
    EmbeddingProvider,
    EmbeddingProviderUnavailableError,
)
from infrastructure.embeddings.test_provider import DeterministicTestEmbeddingProvider

if TYPE_CHECKING:
    from sdk.domain_config import MatchStrategyConfig

_OVERRIDE_PROVIDER: EmbeddingProvider | None = None


def set_override_embedding_provider(provider: EmbeddingProvider | None) -> None:
    """Set a global override provider (used for test isolation)."""
    global _OVERRIDE_PROVIDER
    _OVERRIDE_PROVIDER = provider


def get_embedding_provider(
    strategy: MatchStrategyConfig | None = None,
    *,
    provider_name: str | None = None,
    model_id: str | None = None,
) -> EmbeddingProvider:
    """Resolve and return an active EmbeddingProvider instance.

    Args:
        strategy: MatchStrategyConfig from domain configuration.
        provider_name: Explicit provider override ('auto', 'ollama', 'huggingface', 'test_double').
        model_id: Explicit model identifier override.

    Returns:
        Configured EmbeddingProvider instance.

    Raises:
        EmbeddingProviderUnavailableError: If the resolved provider is not reachable/installed.
    """
    if _OVERRIDE_PROVIDER is not None:
        return _OVERRIDE_PROVIDER

    p_name = provider_name or (strategy.embedding_provider if strategy else "auto")
    m_id = model_id or (strategy.embedding_model_id if strategy else "BAAI/bge-large-en-v1.5")

    p_name = p_name.lower().strip()

    if p_name in ("test_double", "test", "mock"):
        return DeterministicTestEmbeddingProvider(model_id=m_id)

    if p_name == "ollama":
        provider = OllamaEmbeddingProvider(model_id=m_id)
        if not provider.is_available():
            raise EmbeddingProviderUnavailableError(
                f"Ollama provider requested for model '{m_id}', but Ollama daemon is offline or model is unavailable."
            )
        return provider

    if p_name in ("huggingface", "hf", "sentence_transformers"):
        hf_provider = HuggingFaceEmbeddingProvider(model_id=m_id)
        if not hf_provider.is_available():
            raise EmbeddingProviderUnavailableError(
                f"HuggingFace provider requested for model '{m_id}', but sentence-transformers is not installed."
            )
        return hf_provider

    if p_name == "auto":
        # Check Ollama first
        ollama = OllamaEmbeddingProvider(model_id=m_id)
        if ollama.is_available():
            return ollama

        # Check HuggingFace second
        hf = HuggingFaceEmbeddingProvider(model_id=m_id)
        if hf.is_available():
            return hf

        raise EmbeddingProviderUnavailableError(
            f"No embedding provider is available for model '{m_id}'. "
            "Neither Ollama daemon nor sentence-transformers package could be contacted/loaded."
        )

    raise ValueError(
        f"Unknown embedding provider '{p_name}'. Valid options: auto, ollama, huggingface, test_double"
    )


register_embedding_resolver(get_embedding_provider)
