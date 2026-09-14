"""Pluggable projection framework.

Backend-independent projection lifecycle: Core manages projections (build,
validate, reconcile, activate, roll back, quarantine, destroy) without
knowing which downstream store a backend uses. RDF remains authoritative;
projections are always reconciled against the RDF release they were derived
from.
"""

from core.projection.backend import ProjectionBackend
from core.projection.errors import (
    ActiveProjectionError,
    DuplicateBackendError,
    InvalidProjectionTransitionError,
    NoActiveProjectionError,
    NoRetainedProjectionError,
    ProjectionBuildError,
    ProjectionError,
    ProjectionReconciliationError,
    ProjectionValidationError,
    UnknownBackendError,
    UnknownProjectionError,
)
from core.projection.lifecycle import (
    ProjectionStatus,
    ProjectionStatusResolver,
    ProjectionTransition,
)
from core.projection.manager import Projection, ProjectionManager
from core.projection.profile import (
    FieldTransformation,
    ProjectionProfile,
    ReconciliationStrategy,
    TransformationKind,
    UnsupportedBehavior,
)
from core.projection.reconciliation import (
    ProjectedRecord,
    ProjectionReconciler,
    ReconciliationReport,
    ReconciliationResult,
)
from core.projection.registry import ProjectionRegistry
from core.projection.result import ProjectionResult, ProjectionValidationResult

__all__ = [
    "ActiveProjectionError",
    "DuplicateBackendError",
    "FieldTransformation",
    "InvalidProjectionTransitionError",
    "NoActiveProjectionError",
    "NoRetainedProjectionError",
    "ProjectedRecord",
    "Projection",
    "ProjectionBackend",
    "ProjectionBuildError",
    "ProjectionError",
    "ProjectionManager",
    "ProjectionProfile",
    "ProjectionReconciler",
    "ProjectionReconciliationError",
    "ProjectionRegistry",
    "ProjectionResult",
    "ProjectionStatus",
    "ProjectionStatusResolver",
    "ProjectionTransition",
    "ProjectionValidationError",
    "ProjectionValidationResult",
    "ReconciliationReport",
    "ReconciliationResult",
    "ReconciliationStrategy",
    "TransformationKind",
    "UnsupportedBehavior",
    "UnknownBackendError",
    "UnknownProjectionError",
]
