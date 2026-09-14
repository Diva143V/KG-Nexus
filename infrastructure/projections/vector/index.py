"""Vector indexing.

Indexing is deliberately separated from embedding generation and retrieval.
This module builds a searchable structure over already-produced vectors and
answers nearest-neighbour queries; it never embeds text and never interprets
results.

The built-in ``BruteForceVectorIndex`` is a dependency-free linear-scan index
over L2-normalized vectors, so cosine similarity is the dot product. Query
results are returned in deterministic order (score descending, then key
ascending) regardless of insertion order, keeping retrieval reproducible.
A real ANN index (FAISS, HNSW, ...) can be swapped in at the ``VectorIndex``
boundary.

Similarity is a retrieval score, never an identity or truth claim.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class VectorIndexEntry(BaseModel):
    """One indexable vector under a stable key."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str = Field(min_length=1)
    vector: tuple[float, ...] = Field(min_length=1)


class VectorIndex(Protocol):
    """The boundary where a real vector index plugs in."""

    @property
    def size(self) -> int:
        """Number of indexed vectors."""
        ...

    def search(
        self,
        query: tuple[float, ...],
        k: int,
    ) -> tuple[tuple[str, float], ...]:
        """Return the ``k`` most similar (key, score) pairs, best first."""
        ...


class BruteForceVectorIndex:
    """Deterministic linear-scan cosine-similarity index."""

    def __init__(self, entries: tuple[VectorIndexEntry, ...] = ()) -> None:
        self._entries = tuple(entries)

    @property
    def size(self) -> int:
        return len(self._entries)

    def search(
        self,
        query: tuple[float, ...],
        k: int,
    ) -> tuple[tuple[str, float], ...]:
        """Return the ``k`` nearest vectors by cosine similarity.

        ``k`` is clamped to the index size; ``k <= 0`` returns nothing.
        Ties are broken deterministically by ascending key.
        """
        if k <= 0 or not self._entries:
            return ()
        scored = [(self._dot(query, entry.vector), entry.key) for entry in self._entries]
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        return tuple((key, score) for score, key in scored[:k])

    @staticmethod
    def _dot(left: tuple[float, ...], right: tuple[float, ...]) -> float:
        total = 0.0
        for left_value, right_value in zip(left, right, strict=True):
            total += left_value * right_value
        return total
