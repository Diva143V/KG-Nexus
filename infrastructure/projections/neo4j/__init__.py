"""Neo4j projection backend.

The first concrete ``ProjectionBackend`` implementation. Neo4j is a derived
projection: RDF remains authoritative. Core never imports this package; it
reaches the backend through the ``ProjectionRegistry``.
"""

from __future__ import annotations

from infrastructure.projections.neo4j.backend import (
    Neo4jProjectionBackend,
    attribute_records,
    digest,
)
from infrastructure.projections.neo4j.builder import (
    ExpectedAttribute,
    ExpectedEntity,
    ExpectedProjection,
    ExpectedRelationship,
    MemoryRDFDataSource,
    Neo4jProjectionBuilder,
    RDFDataSource,
)
from infrastructure.projections.neo4j.client import (
    MemoryNeo4jClient,
    Neo4jClient,
    conforms_to_client,
)
from infrastructure.projections.neo4j.errors import (
    MissingRDFReleaseError,
    Neo4jClientError,
    Neo4jProjectionError,
    Neo4jReconciliationError,
    Neo4jSmokeTestError,
    Neo4jValidationError,
    UnknownNeo4jProjectionError,
)
from infrastructure.projections.neo4j.reconciler import (
    Neo4jReconciler,
    Neo4jReconciliationReport,
)
from infrastructure.projections.neo4j.schema import (
    Neo4jNode,
    Neo4jRelationship,
    neo4j_candidate_name,
)
from infrastructure.projections.neo4j.smoke_tests import (
    Neo4jSmokeTestResult,
    Neo4jSmokeTestRunner,
)

__all__ = [
    "ExpectedAttribute",
    "ExpectedEntity",
    "ExpectedProjection",
    "ExpectedRelationship",
    "MemoryNeo4jClient",
    "MemoryRDFDataSource",
    "MissingRDFReleaseError",
    "Neo4jClient",
    "Neo4jClientError",
    "Neo4jNode",
    "Neo4jProjectionBackend",
    "Neo4jProjectionBuilder",
    "Neo4jProjectionError",
    "Neo4jReconciler",
    "Neo4jReconciliationError",
    "Neo4jReconciliationReport",
    "Neo4jRelationship",
    "Neo4jSmokeTestError",
    "Neo4jSmokeTestResult",
    "Neo4jSmokeTestRunner",
    "Neo4jValidationError",
    "RDFDataSource",
    "UnknownNeo4jProjectionError",
    "attribute_records",
    "conforms_to_client",
    "digest",
    "neo4j_candidate_name",
]
