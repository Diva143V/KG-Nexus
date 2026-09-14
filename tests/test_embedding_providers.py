"""Unit tests for semantic embedding providers and resolver."""

from __future__ import annotations

import math

import pytest

from infrastructure.embeddings.huggingface_provider import HuggingFaceEmbeddingProvider
from infrastructure.embeddings.ollama_provider import OllamaEmbeddingProvider
from infrastructure.embeddings.protocol import (
    EmbeddingProvider,
    EmbeddingProviderUnavailableError,
)
from infrastructure.embeddings.resolver import (
    get_embedding_provider,
    set_override_embedding_provider,
)
from infrastructure.embeddings.test_provider import DeterministicTestEmbeddingProvider
from sdk.domain_config import MatchStrategyConfig


def test_deterministic_test_provider_properties():
    provider = DeterministicTestEmbeddingProvider(model_id="test/model-v1", dimensions=64)
    assert provider.model_id == "test/model-v1"
    assert provider.provider_type == "test_double"
    assert provider.dimensions == 64
    assert provider.is_available() is True
    assert isinstance(provider, EmbeddingProvider)

    meta = provider.get_metadata()
    assert meta.model_id == "test/model-v1"
    assert meta.dimensions == 64
    assert meta.provider_type == "test_double"


def test_deterministic_test_provider_vectors():
    provider = DeterministicTestEmbeddingProvider(dimensions=64)
    texts = ["Metformin [Drug]", "Glucophage [Drug]", "Metformin [Drug]"]
    vectors = provider.embed(texts)

    assert len(vectors) == 3
    for v in vectors:
        assert len(v) == 64
        # Assert unit length (L2 norm == 1.0)
        norm = math.sqrt(sum(x * x for x in v))
        assert abs(norm - 1.0) < 1e-5

    # Identical texts must produce identical vectors
    assert vectors[0] == vectors[2]

    # Different texts produce distinct vectors
    assert vectors[0] != vectors[1]

    # Cosine similarity between texts
    cos_sim = sum(u * v for u, v in zip(vectors[0], vectors[1], strict=False))
    assert -1.0 <= cos_sim <= 1.0


def test_deterministic_test_provider_empty_string():
    provider = DeterministicTestEmbeddingProvider(dimensions=32)
    vectors = provider.embed(["", "   "])
    assert len(vectors) == 2
    assert all(x == 0.0 for x in vectors[0])


def test_ollama_provider_unavailable_handling():
    # Point to a guaranteed non-existent local port
    provider = OllamaEmbeddingProvider(
        model_id="BAAI/bge-large-en-v1.5",
        base_url="http://127.0.0.1:59999",
        timeout=1.0,
    )
    assert provider.is_available() is False
    with pytest.raises(EmbeddingProviderUnavailableError):
        provider.embed(["test entity"])


def test_huggingface_provider_missing_dependency():
    provider = HuggingFaceEmbeddingProvider(model_id="BAAI/bge-large-en-v1.5")
    # If sentence_transformers is not installed in the environment,
    # is_available must return False and embed must raise EmbeddingProviderUnavailableError
    try:
        import sentence_transformers  # noqa: F401

        has_st = True
    except ImportError:
        has_st = False

    if not has_st:
        assert provider.is_available() is False
        with pytest.raises(EmbeddingProviderUnavailableError) as exc_info:
            provider.embed(["test entity"])
        assert "sentence-transformers is not installed" in str(exc_info.value)


def test_resolver_dispatch():
    # Test double
    p_test = get_embedding_provider(provider_name="test_double")
    assert isinstance(p_test, DeterministicTestEmbeddingProvider)

    # Invalid provider
    with pytest.raises(ValueError, match="Unknown embedding provider"):
        get_embedding_provider(provider_name="nonexistent_provider")

    # Override provider
    custom_provider = DeterministicTestEmbeddingProvider(model_id="custom/override", dimensions=32)
    set_override_embedding_provider(custom_provider)
    resolved = get_embedding_provider(MatchStrategyConfig(embedding_provider="ollama"))
    assert resolved.model_id == "custom/override"
    set_override_embedding_provider(None)


def test_resolver_strategy_config():
    strategy = MatchStrategyConfig(
        enable_embeddings=True,
        embedding_provider="test_double",
        embedding_model_id="microsoft/BiomedNLP-PubMedBERT-base-uncased-abstract",
    )
    resolved = get_embedding_provider(strategy)
    assert resolved.model_id == "microsoft/BiomedNLP-PubMedBERT-base-uncased-abstract"
    assert resolved.provider_type == "test_double"
