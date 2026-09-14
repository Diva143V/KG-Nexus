"""RDFAuthority: the single interface Core uses for the semantic layer.

RDF is authoritative. ``RDFAuthority`` talks to an ``RDFBackend`` and
exposes snapshot writing and reading. Core never depends on a concrete
RDF backend; backends live under ``infrastructure/rdf``.
"""

from __future__ import annotations

from core.rdf.graph import NamedGraph, RDFDataset
from sdk.rdf_backend import RDFBackend


class RDFAuthority:
    """Front door to the authoritative RDF store."""

    def __init__(self, *, backend: RDFBackend) -> None:
        self._backend = backend

    def write_snapshot(self, dataset: RDFDataset) -> None:
        """Persist a full dataset snapshot, replacing any existing content."""
        self._backend.write_dataset(dataset)

    def read_snapshot(self) -> RDFDataset:
        """Read the full dataset snapshot from the authoritative store."""
        return self._backend.read_dataset()

    def read_graph(self, name: str) -> NamedGraph | None:
        """Read a single named graph, if present."""
        return self._backend.read_graph(name)

    @property
    def backend(self) -> RDFBackend:
        """Expose the adapter (read-only access for tests and tooling)."""
        return self._backend
