"""Deterministic Test Embedding Provider.

Dependency-free, mathematically deterministic test double for offline CI
and fast automated testing. Tokenizes alphanumeric substrings and applies signed
feature-hashing with L2-normalization so cosine similarity is the dot product.
"""

from __future__ import annotations

import math
import re
from hashlib import sha256

from infrastructure.embeddings.protocol import (
    EmbeddingModelMetadata,
    EmbeddingProvider,
)

_ALNUM = re.compile(r"[a-z0-9]+")
_FEATURES_PER_TOKEN = 8


class DeterministicTestEmbeddingProvider(EmbeddingProvider):
    """Fast, reproducible embedding test double for CI and deterministic unit testing."""

    def __init__(
        self,
        model_id: str = "hybridkg/deterministic-test-embedder",
        dimensions: int = 128,
    ) -> None:
        if dimensions < 1:
            raise ValueError("Dimensions must be >= 1")
        self._model_id = model_id
        self._dimensions = dimensions

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def provider_type(self) -> str:
        return "test_double"

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def is_available(self) -> bool:
        return True

    def _embed_single(self, text: str) -> tuple[float, ...]:
        vector = [0.0] * self._dimensions
        tokens = _ALNUM.findall(text.lower())
        if not tokens:
            return tuple(vector)

        for token in tokens:
            digest = sha256(token.encode("utf-8")).digest()
            for offset in range(0, min(len(digest), _FEATURES_PER_TOKEN * 4), 4):
                bucket_bytes = digest[offset : offset + 4]
                index = int.from_bytes(bucket_bytes, "big") % self._dimensions
                sign = 1.0 if digest[offset + 3] % 2 == 0 else -1.0
                vector[index] += sign

        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0.0:
            return tuple(vector)
        return tuple(v / norm for v in vector)

    def embed(self, texts: list[str]) -> list[tuple[float, ...]]:
        return [self._embed_single(t) for t in texts]

    def get_metadata(self) -> EmbeddingModelMetadata:
        return EmbeddingModelMetadata(
            model_id=self._model_id,
            provider_type=self.provider_type,
            dimensions=self._dimensions,
            model_digest="sha256:deterministic_test_double",
            parameters={"features_per_token": _FEATURES_PER_TOKEN, "normalization": "l2"},
        )
