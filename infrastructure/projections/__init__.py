"""Projection backend technology implementations.

Core must never import from this package; it only talks to backends
through the ``sdk.projection_backend.ProjectionBackend`` protocol and the
``core.projection.ProjectionBackend`` contract.
"""

from __future__ import annotations

import logging
from typing import Any

from infrastructure.projections.memory import MemoryProjectionBackend
from infrastructure.projections.neo4j import Neo4jProjectionBackend
from infrastructure.projections.parquet import ParquetProjectionBackend
from infrastructure.projections.rdf import RDFProjectionBackend
from infrastructure.projections.search import SearchProjectionBackend
from infrastructure.projections.vector import VectorProjectionBackend

logger = logging.getLogger(__name__)

__all__ = [
    "MemoryProjectionBackend",
    "Neo4jProjectionBackend",
    "ParquetProjectionBackend",
    "RDFProjectionBackend",
    "SearchProjectionBackend",
    "VectorProjectionBackend",
    "create_default_projection_registry",
]


def create_default_projection_registry(
    data_source: Any,
    include_all: bool = True,
) -> Any:
    """Instantiate and register all concrete projection backends into a ProjectionRegistry."""
    from core.projection.registry import ProjectionRegistry
    from infrastructure.projections.memory import MemoryProjectionBackend
    from infrastructure.projections.neo4j import Neo4jProjectionBackend
    from infrastructure.projections.neo4j.client import MemoryNeo4jClient
    from infrastructure.projections.parquet import ParquetProjectionBackend
    from infrastructure.projections.parquet.store import MemoryParquetProjectionStore
    from infrastructure.projections.rdf import RDFProjectionBackend
    from infrastructure.projections.rdf.store import MemoryRDFProjectionStore
    from infrastructure.projections.search import SearchProjectionBackend
    from infrastructure.projections.search.store import MemorySearchProjectionStore
    from infrastructure.projections.vector import VectorProjectionBackend
    from infrastructure.projections.vector.store import MemoryVectorProjectionStore

    registry = ProjectionRegistry()
    registry.register(MemoryProjectionBackend(data_source=data_source, backend_id="memory"))
    registry.register(
        RDFProjectionBackend(
            store=MemoryRDFProjectionStore(), data_source=data_source, backend_id="rdf"
        )
    )

    if include_all:
        try:
            registry.register(
                Neo4jProjectionBackend(
                    client=MemoryNeo4jClient(), data_source=data_source, backend_id="neo4j"
                )
            )
        except Exception as exc:
            logger.warning("Failed to register Neo4j projection backend: %s", exc)
        try:
            registry.register(
                ParquetProjectionBackend(
                    store=MemoryParquetProjectionStore(),
                    data_source=data_source,
                    backend_id="parquet",
                )
            )
        except Exception as exc:
            logger.warning("Failed to register Parquet projection backend: %s", exc)
        try:
            registry.register(
                SearchProjectionBackend(
                    store=MemorySearchProjectionStore(),
                    data_source=data_source,
                    backend_id="search",
                )
            )
        except Exception as exc:
            logger.warning("Failed to register Search projection backend: %s", exc)
        try:
            registry.register(
                VectorProjectionBackend(
                    store=MemoryVectorProjectionStore(),
                    data_source=data_source,
                    backend_id="vector",
                )
            )
        except Exception as exc:
            logger.warning("Failed to register Vector projection backend: %s", exc)

    return registry
