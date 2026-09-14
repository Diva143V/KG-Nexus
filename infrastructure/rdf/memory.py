"""In-memory RDF backend.

Technology implementation. Core never imports this package; it only talks
to ``RDFAuthority`` through the ``sdk.rdf_backend.RDFBackend`` protocol.
"""

from __future__ import annotations

from core.rdf.graph import NamedGraph, RDFDataset
from sdk.rdf_backend import RDFBackend


class MemoryRDFBackend:
    """Deterministic in-memory store for RDF datasets.

    Conforms to ``sdk.rdf_backend.RDFBackend``. Writes replace the
    previous dataset; reads return the current dataset unchanged.
    """

    def __init__(self) -> None:
        self._dataset = RDFDataset()

    def write_dataset(self, dataset: RDFDataset) -> None:
        self._dataset = dataset

    def read_dataset(self) -> RDFDataset:
        return self._dataset

    def read_graph(self, name: str) -> NamedGraph | None:
        return self._dataset.graph(name)


def conforms_to_backend(backend: object) -> bool:
    """True when ``backend`` implements the RDFBackend protocol."""
    return isinstance(backend, RDFBackend)
