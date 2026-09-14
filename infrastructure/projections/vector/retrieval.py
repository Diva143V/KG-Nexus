"""Vector retrieval.

Retrieval is deliberately separated from embedding generation and indexing.
This module turns a query into retrieval candidates: it embeds the query with
the configured model, searches the index, and returns deterministic results
with their metadata and similarity scores.

Retrieval is strictly a candidate layer for semantic search, similarity
search, and retrieval augmentation. Results are candidates with scores —
nothing here approves assertions, establishes identity, or carries state.
The downstream consumer decides what the candidates mean; the vector
projection never does.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from infrastructure.projections.vector.embedder import EmbeddingModel
from infrastructure.projections.vector.index import (
    BruteForceVectorIndex,
    VectorIndexEntry,
)
from infrastructure.projections.vector.models import EmbeddedItem


class VectorSearchResult(BaseModel):
    """One retrieval candidate: a vector and its similarity score."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    score: float
    source: str | None = None
    digest: str = Field(min_length=1)


class VectorRetriever:
    """Searches an embedded collection for retrieval candidates."""

    def __init__(self, *, embedder: EmbeddingModel) -> None:
        self._embedder = embedder

    def search(
        self,
        *,
        items: tuple[EmbeddedItem, ...],
        query: str,
        k: int = 5,
    ) -> tuple[VectorSearchResult, ...]:
        """Embed ``query`` and return the ``k`` closest retrieval candidates."""
        return self.search_vector(
            items=items,
            query_vector=self._embedder.embed(query),
            k=k,
        )

    def search_vector(
        self,
        *,
        items: tuple[EmbeddedItem, ...],
        query_vector: tuple[float, ...],
        k: int = 5,
    ) -> tuple[VectorSearchResult, ...]:
        """Search the collection with an already-produced query vector."""
        if k <= 0 or not items:
            return ()
        index = self._index(items)
        by_key = {item.key: item for item in items}
        results: list[VectorSearchResult] = []
        for key, score in index.search(query_vector, k):
            item = by_key[key]
            results.append(
                VectorSearchResult(
                    key=item.key,
                    kind=item.kind,
                    score=score,
                    source=item.source,
                    digest=item.digest,
                )
            )
        return tuple(results)

    def similar(
        self,
        *,
        items: tuple[EmbeddedItem, ...],
        key: str,
        k: int = 5,
    ) -> tuple[VectorSearchResult, ...]:
        """Return the vectors most similar to the item identified by ``key``."""
        if k <= 0 or not items:
            return ()
        by_key = {item.key: item for item in items}
        item = by_key.get(key)
        if item is None:
            return ()
        return self.search_vector(items=items, query_vector=item.vector, k=k)

    @staticmethod
    def _index(items: tuple[EmbeddedItem, ...]) -> BruteForceVectorIndex:
        return BruteForceVectorIndex(
            tuple(VectorIndexEntry(key=item.key, vector=item.vector) for item in items)
        )
