"""Text indexing for the search projection.

Indexing is deliberately separated from retrieval. This module tokenizes
text, builds a searchable structure over the materialized documents, and
answers term-based queries; it never decides what a result means.

The built-in ``DefaultTextSearchEngine`` and ``InvertedSearchIndex`` are a
dependency-free, deterministic stand-in for an OpenSearch / Elasticsearch
index: terms (lower-cased alphanumeric runs) map to documents with term
counts, full-text queries score documents by the sum of matching term counts,
and exact aliases resolve deterministically. Full-text coverage spans the
document text, aliases, and identifiers, so aliases, labels, descriptions,
and identifiers are all discoverable. A real search engine cluster can be
swapped in at the ``SearchEngine`` boundary without touching the rest of the
backend.

Search results are retrieval candidates only. Ranking a document high must
not be treated as promoting the assertion it describes.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Protocol

from infrastructure.projections.search.documents import SearchDocument

_ALNUM = re.compile(r"[a-z0-9]+")

DEFAULT_ENGINE_ID = "hybridkg/text-search"
DEFAULT_ENGINE_VERSION = "1.0.0"


def tokenize(text: str) -> tuple[str, ...]:
    """Deterministic lower-cased alphanumeric tokenization."""
    return tuple(_ALNUM.findall(text.lower()))


class SearchIndex(Protocol):
    """The boundary where a real search index plugs in."""

    @property
    def size(self) -> int:
        """Number of indexed documents."""
        ...

    def search(
        self,
        query: str,
        k: int,
    ) -> tuple[tuple[str, int], ...]:
        """Return the ``k`` most relevant (doc_id, score) pairs, best first."""
        ...

    def resolve_alias(self, alias: str) -> tuple[str, ...]:
        """Document ids carrying ``alias``, in deterministic order."""
        ...


class SearchEngine(Protocol):
    """The boundary where a real search engine (OpenSearch, ES) plugs in."""

    @property
    def engine_id(self) -> str:
        """Stable identifier for this search engine."""
        ...

    @property
    def engine_version(self) -> str:
        """Version of this search engine."""
        ...

    @property
    def engine_config(self) -> dict[str, object]:
        """Configuration the documents were indexed with."""
        ...

    def index(self, documents: tuple[SearchDocument, ...]) -> SearchIndex:
        """Build a search index over ``documents``."""
        ...


class InvertedSearchIndex:
    """Deterministic term-frequency index over search documents.

    Full-text coverage spans the text (the concise discovery description),
    every alias, and every identifier, so aliases, labels, descriptions, and
    identifiers are all searchable. Term counts come from the document fields
    exactly as materialized; ranking stays deterministic.
    """

    def __init__(self, documents: tuple[SearchDocument, ...] = ()) -> None:
        self._documents = tuple(documents)
        self._postings: dict[str, Counter[str]] = {}
        self._aliases: dict[str, set[str]] = {}
        for document in documents:
            for field in (
                document.text,
                *document.aliases,
                *document.identifiers,
            ):
                for term in tokenize(field):
                    self._postings.setdefault(term, Counter())[document.doc_id] += 1
            for alias in document.aliases:
                self._aliases.setdefault(alias.lower(), set()).add(document.doc_id)

    @property
    def size(self) -> int:
        return len(self._documents)

    def search(
        self,
        query: str,
        k: int,
    ) -> tuple[tuple[str, int], ...]:
        """Return the ``k`` most relevant documents by term-frequency score.

        ``k`` is clamped to the index size; ``k <= 0`` returns nothing.
        Ties are broken deterministically by ascending document id.
        """
        if k <= 0 or not self._documents:
            return ()
        terms = tokenize(query)
        if not terms:
            return ()
        scores: Counter[str] = Counter()
        for term in terms:
            scores.update(self._postings.get(term, Counter()))
        ranked = sorted(
            ((doc_id, score) for doc_id, score in scores.items() if score > 0),
            key=lambda pair: (-pair[1], pair[0]),
        )
        return tuple(ranked[:k])

    def resolve_alias(self, alias: str) -> tuple[str, ...]:
        """Document ids carrying ``alias``, in deterministic order."""
        return tuple(sorted(self._aliases.get(alias.lower(), set())))


class DefaultTextSearchEngine:
    """Deterministic, dependency-free search engine."""

    @property
    def engine_id(self) -> str:
        return DEFAULT_ENGINE_ID

    @property
    def engine_version(self) -> str:
        return DEFAULT_ENGINE_VERSION

    @property
    def engine_config(self) -> dict[str, object]:
        return {
            "engine": self.engine_id,
            "engine_version": self.engine_version,
            "tokenization": "lower-alnum",
            "scoring": "term-frequency",
        }

    def index(self, documents: tuple[SearchDocument, ...]) -> InvertedSearchIndex:
        return InvertedSearchIndex(documents)
