"""RDF backend extension contract.

RDF is authoritative. This protocol defines the abstract contract for storing
and reading authoritative RDF dataset snapshots.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
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
        """Return a single named graph, or None if absent."""
        ...
