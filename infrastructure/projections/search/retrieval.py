"""Search retrieval.

Retrieval is deliberately separated from indexing. This module turns a query
or an alias into search results: it runs the query through the search index
and returns deterministic hits with their scores and document metadata.

Results are strictly retrieval candidates for full-text search, aliases,
labels, descriptions, and identifiers. Ranking must not directly promote
assertions: nothing here approves anything, and results carry no state. The
downstream consumer decides what a hit means; the search projection never
does.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from infrastructure.projections.search.documents import SearchDocument
from infrastructure.projections.search.index import SearchIndex


class SearchResult(BaseModel):
    """One retrieval candidate: a document and its relevance score."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    doc_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    label: str
    description: str
    score: int = Field(ge=0)
    digest: str = Field(min_length=1)


class SearchRetriever:
    """Searches an indexed document collection for retrieval candidates."""

    def __init__(self, *, index: SearchIndex) -> None:
        self._index = index

    def search(
        self,
        *,
        documents: tuple[SearchDocument, ...],
        query: str,
        k: int = 5,
    ) -> tuple[SearchResult, ...]:
        """Return the ``k`` closest retrieval candidates for ``query``."""
        if k <= 0 or not documents:
            return ()
        by_id = {document.doc_id: document for document in documents}
        results: list[SearchResult] = []
        for doc_id, score in self._index.search(query, k):
            document = by_id[doc_id]
            results.append(
                SearchResult(
                    doc_id=document.doc_id,
                    kind=document.kind,
                    label=document.label,
                    description=document.description,
                    score=score,
                    digest=document.digest,
                )
            )
        return tuple(results)

    def resolve_alias(
        self,
        *,
        documents: tuple[SearchDocument, ...],
        alias: str,
    ) -> tuple[SearchResult, ...]:
        """Return the documents that carry ``alias``, in deterministic order."""
        by_id = {document.doc_id: document for document in documents}
        results: list[SearchResult] = []
        for doc_id in self._index.resolve_alias(alias):
            document = by_id[doc_id]
            results.append(
                SearchResult(
                    doc_id=document.doc_id,
                    kind=document.kind,
                    label=document.label,
                    description=document.description,
                    score=1,
                    digest=document.digest,
                )
            )
        return tuple(results)
