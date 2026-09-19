"""Projection backend extension contract.

Projection backends persist projection content to a concrete store (e.g. a
graph database such as Neo4j). Core depends only on this interface; backend
implementations live under ``infrastructure/projections`` and never leak
into core. Core never writes RDF semantics into a backend behind a
projection's back.
"""

from __future__ import annotations

from contracts.projections import ProjectionBackend

__all__ = ["ProjectionBackend"]
