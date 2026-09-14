"""Backend registry for the pluggable projection framework.

The registry is backend-neutral: it never inspects a backend's concrete
type and never dispatches on backend ids (no ``if backend_id == ...`` style
logic). A backend is keyed by the id it reports itself, and the same
registered instance is returned on every request so that backends holding
projection state stay consistent across the projection lifecycle.
"""

from __future__ import annotations

from collections.abc import Iterable

from core.projection.backend import ProjectionBackend
from core.projection.errors import DuplicateBackendError, UnknownBackendError


class ProjectionRegistry:
    """Registers and resolves projection backends by their own ids."""

    def __init__(self) -> None:
        self._backends: dict[str, ProjectionBackend] = {}

    def register(self, backend: ProjectionBackend) -> None:
        """Register a backend under its self-reported id."""
        if not isinstance(backend, ProjectionBackend):
            raise TypeError("backend does not conform to ProjectionBackend")
        backend_id = backend.backend_id
        if backend_id in self._backends:
            raise DuplicateBackendError(backend_id)
        self._backends[backend_id] = backend

    def get(self, backend_id: str) -> ProjectionBackend:
        """Return the registered backend for ``backend_id``."""
        backend = self._backends.get(backend_id)
        if backend is None:
            raise UnknownBackendError(backend_id)
        return backend

    def create(self, backend_id: str) -> ProjectionBackend:
        """Return a backend for ``backend_id``.

        Backends are registered as instances, so ``create`` returns the same
        registered instance, keeping any projection state it holds intact
        across the lifecycle.
        """
        return self.get(backend_id)

    def has(self, backend_id: str) -> bool:
        """Whether a backend with ``backend_id`` is registered."""
        return backend_id in self._backends

    def list_backends(self) -> tuple[str, ...]:
        """Ids of all registered backends, in sorted order."""
        return tuple(sorted(self._backends))

    def iter_backends(self) -> Iterable[ProjectionBackend]:
        """Iterate over all registered backends."""
        return self._backends.values()
