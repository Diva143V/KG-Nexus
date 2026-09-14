"""RDF store abstraction and deterministic in-memory implementation.

``RDFProjectionStore`` is the boundary where a real triplestore adapter
plugs in. ``MemoryRDFProjectionStore`` is the deterministic in-memory
implementation used by tests and demos.

The store is a pure implementation detail of this backend. RDF remains
authoritative and Core never sees the store. Content is scoped by a store
key (the projection's candidate name), so candidates and retained
projections coexist until explicitly deleted.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from core.rdf.graph import NamedGraph, RDFDataset
from infrastructure.projections.rdf.errors import RDFClientError


def rdf_candidate_name(projection_id: str) -> str:
    """Store key for a projection's candidate.

    Candidates are always built under a distinct name and never into the
    active projection.
    """
    return f"rdf_{projection_id}_candidate"


@runtime_checkable
class RDFProjectionStore(Protocol):
    """RDF-dataset operations used by the RDF projection backend."""

    @property
    def store_name(self) -> str:
        """Stable identifier for this store implementation."""
        ...

    def has_projection(self, store_key: str) -> bool:
        """Whether content exists under ``store_key``."""
        ...

    def write_dataset(self, store_key: str, dataset: RDFDataset) -> None:
        """Replace the dataset under ``store_key``."""
        ...

    def read_dataset(self, store_key: str) -> RDFDataset | None:
        """Return the dataset under ``store_key``, if present."""
        ...

    def graph(self, store_key: str, name: str) -> NamedGraph | None:
        """Return a single named graph under ``store_key``, if present."""
        ...

    def graph_names(self, store_key: str) -> tuple[str, ...]:
        """Names of all graphs under ``store_key``, in order."""
        ...

    def triple_count(self, store_key: str) -> int:
        """Total number of triples under ``store_key``."""
        ...

    def activate(self, store_key: str) -> None:
        """Atomically promote the candidate under ``store_key`` to active.

        Content is never moved or deleted; activation flips the store's
        active pointer. Previously active content remains in place and can
        be restored by a later rollback.
        """
        ...

    def active_projection(self) -> str | None:
        """Store key of the currently active projection, if any."""
        ...

    def rollback(self, store_key: str) -> None:
        """Deactivate the projection under ``store_key``.

        Retained content is left untouched so it can be restored without
        rebuilding.
        """
        ...

    def delete_projection(self, store_key: str) -> None:
        """Delete all content under ``store_key``, if present."""
        ...


class MemoryRDFProjectionStore:
    """Deterministic in-memory RDF dataset store."""

    def __init__(self) -> None:
        self._datasets: dict[str, RDFDataset] = {}
        self._active: str | None = None

    @property
    def store_name(self) -> str:
        return "memory-rdf"

    def has_projection(self, store_key: str) -> bool:
        return store_key in self._datasets

    def write_dataset(self, store_key: str, dataset: RDFDataset) -> None:
        self._datasets[store_key] = dataset

    def read_dataset(self, store_key: str) -> RDFDataset | None:
        return self._datasets.get(store_key)

    def graph(self, store_key: str, name: str) -> NamedGraph | None:
        dataset = self._datasets.get(store_key)
        if dataset is None:
            return None
        return dataset.graph(name)

    def graph_names(self, store_key: str) -> tuple[str, ...]:
        dataset = self._datasets.get(store_key)
        if dataset is None:
            return ()
        return dataset.graph_names()

    def triple_count(self, store_key: str) -> int:
        dataset = self._datasets.get(store_key)
        if dataset is None:
            return 0
        return dataset.triple_count()

    def activate(self, store_key: str) -> None:
        if store_key not in self._datasets:
            raise RDFClientError(f"no candidate to activate: {store_key}")
        self._active = store_key

    def active_projection(self) -> str | None:
        return self._active

    def rollback(self, store_key: str) -> None:
        if self._active == store_key:
            self._active = None

    def delete_projection(self, store_key: str) -> None:
        self._datasets.pop(store_key, None)
        if self._active == store_key:
            self._active = None


def conforms_to_store(store: object) -> bool:
    """True when ``store`` implements the RDFProjectionStore contract."""
    return isinstance(store, RDFProjectionStore)
