"""Search store abstraction and deterministic in-memory implementation.

``SearchProjectionStore`` is the boundary where a real search engine (an
OpenSearch / Elasticsearch cluster, a filesystem of indexed documents, ...)
plugs in. ``MemorySearchProjectionStore`` is the deterministic in-memory
implementation used by tests and demos; it stores the exact serialized
manifest and document bytes so validation, reconciliation, and smoke tests
always exercise the real format.

The store is a pure implementation detail of this backend. The search
projection remains a derived discovery layer — RDF stays authoritative and
Core never sees the store. Content is scoped by a store key (the projection's
candidate name), so candidates and retained projections coexist until
explicitly deleted.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from infrastructure.projections.search.errors import SearchClientError
from infrastructure.projections.search.writer import try_documents_from_bytes


def search_candidate_name(projection_id: str) -> str:
    """Store key for a projection's candidate.

    Candidates are always built under a distinct name and never into the
    active projection.
    """
    return f"search_{projection_id}_candidate"


@runtime_checkable
class SearchProjectionStore(Protocol):
    """Search-store operations used by the search projection backend."""

    @property
    def store_name(self) -> str:
        """Stable identifier for this store implementation."""
        ...

    def has_projection(self, store_key: str) -> bool:
        """Whether content exists under ``store_key``."""
        ...

    def write_dataset(self, store_key: str, name: str, data: bytes) -> None:
        """Replace the named dataset under ``store_key``."""
        ...

    def read_dataset(self, store_key: str, name: str) -> bytes | None:
        """Return the named dataset under ``store_key``, if present."""
        ...

    def dataset_names(self, store_key: str) -> tuple[str, ...]:
        """Names of all datasets under ``store_key``, in order."""
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


class MemorySearchProjectionStore:
    """Deterministic in-memory store holding exact serialized bytes."""

    def __init__(self) -> None:
        self._datasets: dict[str, dict[str, bytes]] = {}
        self._active: str | None = None

    @property
    def store_name(self) -> str:
        return "memory-search"

    def has_projection(self, store_key: str) -> bool:
        return store_key in self._datasets

    def write_dataset(self, store_key: str, name: str, data: bytes) -> None:
        self._datasets.setdefault(store_key, {})[name] = data

    def read_dataset(self, store_key: str, name: str) -> bytes | None:
        return self._datasets.get(store_key, {}).get(name)

    def dataset_names(self, store_key: str) -> tuple[str, ...]:
        return tuple(sorted(self._datasets.get(store_key, {})))

    def dataset_count(self, store_key: str, name: str) -> int:
        """Number of records in the named dataset, if present."""
        data = self.read_dataset(store_key, name)
        if data is None:
            return 0
        documents = try_documents_from_bytes(data)
        if documents is None:
            return 0
        return len(documents)

    def activate(self, store_key: str) -> None:
        if store_key not in self._datasets:
            raise SearchClientError(f"no candidate to activate: {store_key}")
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
    """True when ``store`` implements the SearchProjectionStore contract."""
    return isinstance(store, SearchProjectionStore)
