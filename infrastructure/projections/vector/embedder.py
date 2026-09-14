"""Embedding generation for the vector projection.

Embedding generation is deliberately separated from vector indexing and
vector retrieval. This module only knows how to turn a deterministic text
surface into a fixed-dimensional vector; it never stores, searches, or judges
content.

The built-in ``DeterministicHashEmbedder`` is a domain-neutral, dependency-free
embedding model: it feature-hashes tokens into a fixed-dimensional vector and
L2-normalizes it. It is deterministic (identical surfaces always produce
identical vectors) so the projection is rebuildable from RDF and verifiable.
A real semantic model (a plug-in encoder, an 8B retriever, ...) can be swapped
in at the ``EmbeddingModel`` boundary without touching the rest of the
backend.

Vector similarity MUST NOT be treated as identity: two surfaces can be
embeddably close without denoting the same entity or assertion, and nothing
here assigns state or authority to anything.
"""

from __future__ import annotations

import math
import re
from hashlib import sha256
from typing import Protocol

_ALNUM = re.compile(r"[a-z0-9]+")

DEFAULT_MODEL_ID = "hybridkg/deterministic-hash-embedder"
DEFAULT_MODEL_VERSION = "1.0.0"
DEFAULT_DIMENSIONS = 64


class EmbeddingModel(Protocol):
    """The boundary where an embedding model plugs in."""

    @property
    def model_id(self) -> str:
        """Stable identifier for this embedding model."""
        ...

    @property
    def model_version(self) -> str:
        """Version of this embedding model."""
        ...

    @property
    def dimensions(self) -> int:
        """Dimensionality of every produced vector."""
        ...

    @property
    def embedding_config(self) -> dict[str, object]:
        """Configuration the vectors were produced with."""
        ...

    def embed(self, surface: str) -> tuple[float, ...]:
        """Embed ``surface`` into a fixed-dimensional vector."""
        ...


class DeterministicHashEmbedder:
    """Deterministic, dependency-free embedding model.

    Tokens (lower-cased alphanumeric runs) are feature-hashed into a
    fixed-dimensional accumulator: each token contributes several independent
    signed buckets derived from non-overlapping chunks of its SHA-256 digest,
    which keeps short surfaces discriminative. The accumulator is L2-normalized
    so cosine similarity equals the dot product. Produces the empty vector for
    a surface with no tokens.
    """

    def __init__(self, *, dimensions: int = DEFAULT_DIMENSIONS) -> None:
        if dimensions < 1:
            raise ValueError("embedding dimensions must be >= 1")
        self._dimensions = dimensions

    @property
    def model_id(self) -> str:
        return DEFAULT_MODEL_ID

    @property
    def model_version(self) -> str:
        return DEFAULT_MODEL_VERSION

    @property
    def dimensions(self) -> int:
        return self._dimensions

    @property
    def embedding_config(self) -> dict[str, object]:
        return {
            "model": self.model_id,
            "model_version": self.model_version,
            "dimensions": self._dimensions,
            "tokenization": "lower-alnum",
            "features_per_token": _FEATURES_PER_TOKEN,
            "normalization": "l2",
        }

    def embed(self, surface: str) -> tuple[float, ...]:
        vector = [0.0] * self._dimensions
        for token in _ALNUM.findall(surface.lower()):
            digest = sha256(token.encode("utf-8")).digest()
            for offset in range(0, _FEATURES_PER_TOKEN * 4, 4):
                bucket_bytes = digest[offset : offset + 4]
                index = int.from_bytes(bucket_bytes, "big") % self._dimensions
                sign = 1.0 if digest[offset + 3] % 2 == 0 else -1.0
                vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            return tuple(vector)
        return tuple(value / norm for value in vector)


_FEATURES_PER_TOKEN = 8
