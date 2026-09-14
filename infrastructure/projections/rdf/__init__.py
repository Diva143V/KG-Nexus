"""RDF projection backend.

A downstream/redeployable RDF projection. RDF is authoritative and remains
the projection's own format — this backend redeploys a release's RDF dataset
into another RDF deployment, never a second semantic authority. Core never
imports this package; it reaches the backend through the
``ProjectionRegistry``.
"""

from __future__ import annotations

from infrastructure.projections.rdf.backend import RDFProjectionBackend
from infrastructure.projections.rdf.builder import (
    ExpectedAssertion,
    ExpectedRDFDataset,
    MemoryRDFDataSource,
    RDFDataSource,
    RDFProjectionBuilder,
)
from infrastructure.projections.rdf.errors import (
    MissingRDFReleaseError,
    RDFClientError,
    RDFProjectionError,
    RDFReconciliationError,
    RDFSmokeTestError,
    RDFUnsupportedSemanticsError,
    RDFValidationError,
    UnknownRDFProjectionError,
)
from infrastructure.projections.rdf.policy import RDFProjectionPolicy, policy_from_profile
from infrastructure.projections.rdf.reconciler import (
    RDFReconciler,
    RDFReconciliationReport,
)
from infrastructure.projections.rdf.smoke_tests import (
    RDFSmokeTestResult,
    RDFSmokeTestRunner,
)
from infrastructure.projections.rdf.store import (
    MemoryRDFProjectionStore,
    RDFProjectionStore,
    rdf_candidate_name,
)

__all__ = [
    "ExpectedAssertion",
    "ExpectedRDFDataset",
    "MemoryRDFDataSource",
    "MemoryRDFProjectionStore",
    "MissingRDFReleaseError",
    "RDFClientError",
    "RDFDataSource",
    "RDFProjectionBackend",
    "RDFProjectionBuilder",
    "RDFProjectionError",
    "RDFProjectionPolicy",
    "RDFProjectionStore",
    "RDFReconciler",
    "RDFReconciliationError",
    "RDFReconciliationReport",
    "RDFSmokeTestError",
    "RDFSmokeTestResult",
    "RDFSmokeTestRunner",
    "RDFUnsupportedSemanticsError",
    "RDFValidationError",
    "UnknownRDFProjectionError",
    "policy_from_profile",
    "rdf_candidate_name",
]
