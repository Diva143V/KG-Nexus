"""Projection backend technology implementations.

Core must never import from this package; it only talks to backends
through the ``sdk.projection_backend.ProjectionBackend`` protocol and the
``core.projection.ProjectionBackend`` contract.
"""

from __future__ import annotations

from infrastructure.projections.memory import MemoryProjectionBackend
from infrastructure.projections.neo4j import Neo4jProjectionBackend
from infrastructure.projections.parquet import ParquetProjectionBackend
from infrastructure.projections.rdf import RDFProjectionBackend
from infrastructure.projections.search import SearchProjectionBackend
from infrastructure.projections.vector import VectorProjectionBackend

__all__ = [
    "MemoryProjectionBackend",
    "Neo4jProjectionBackend",
    "ParquetProjectionBackend",
    "RDFProjectionBackend",
    "SearchProjectionBackend",
    "VectorProjectionBackend",
]
