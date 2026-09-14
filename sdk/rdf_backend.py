"""RDF backend extension contract.

Core depends only on ``RDFAuthority``, which talks to an ``RDFBackend``
through this interface. Backend implementations (in-memory, turtle, etc.)
live under ``infrastructure/rdf`` and never leak into core.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from core.rdf.graph import NamedGraph, RDFDataset


@runtime_checkable
class RDFBackend(Protocol):
    """Extension contract for storing and reading RDF datasets."""

    def write_dataset(self, dataset: RDFDataset) -> None:
        """Persist the entire dataset (replace any existing content)."""
        ...

    def read_dataset(self) -> RDFDataset:
        """Return the full dataset currently stored."""
        ...

    def read_graph(self, name: str) -> NamedGraph | None:
        """Return a single named graph, or ``None`` if absent."""
        ...
