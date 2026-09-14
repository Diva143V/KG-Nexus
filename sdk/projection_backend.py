"""Projection backend extension contract.

Projection backends persist projection content to a concrete store (e.g. a
graph database such as Neo4j). Core depends only on this interface; backend
implementations live under ``infrastructure/projections`` and never leak
into core. Core never writes RDF semantics into a backend behind a
projection's back.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from contracts.projections import ProjectionBackend
from core.projections.content import ProjectionContent


@runtime_checkable
class LegacyProjectionBackend(Protocol):
    """Legacy extension contract for storing and reading projection content."""

    def write(self, content: ProjectionContent) -> None:
        """Persist projection content (replace any existing content)."""
        ...

    def read(self, projection_id: str) -> ProjectionContent | None:
        """Return the stored content for ``projection_id``, if present."""
        ...

    def delete(self, projection_id: str) -> None:
        """Remove stored content for ``projection_id`` if present."""
        ...


__all__ = ["ProjectionBackend", "LegacyProjectionBackend"]
