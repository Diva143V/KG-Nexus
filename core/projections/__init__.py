"""Projection framework: generic, profile-driven projections over authoritative RDF."""

from __future__ import annotations

from core.projections.builder import (
    ProjectionBuilder,
    UndeclaredSemanticsError,
    UnsupportedSemanticsError,
)
from core.projections.content import ProjectedEdge, ProjectedNode, ProjectionContent
from core.projections.errors import (
    ActiveProjectionError,
    InvalidProjectionTransitionError,
    ProjectionError,
    ProjectionValidationError,
    UnknownProjectionError,
)
from core.projections.manager import ProjectionManager
from core.projections.profile import (
    FieldTransformation,
    ProjectionProfile,
    ReconciliationMethod,
    TransformationKind,
    UnsupportedBehavior,
)
from core.projections.projection import Projection, ProjectionGate, ProjectionTransition
from core.projections.reconciler import (
    ProjectionReconciler,
    ReconciliationOutcome,
    ReconciliationResult,
)
from core.projections.resolver import ProjectionStatusResolver
from core.projections.status import ProjectionStatus
from core.projections.validator import ProjectionValidator

__all__ = [
    "ActiveProjectionError",
    "FieldTransformation",
    "InvalidProjectionTransitionError",
    "ProjectedEdge",
    "ProjectedNode",
    "Projection",
    "ProjectionBuilder",
    "ProjectionContent",
    "ProjectionError",
    "ProjectionGate",
    "ProjectionManager",
    "ProjectionProfile",
    "ProjectionReconciler",
    "ProjectionStatus",
    "ProjectionStatusResolver",
    "ProjectionTransition",
    "ProjectionValidationError",
    "ProjectionValidator",
    "ReconciliationMethod",
    "ReconciliationOutcome",
    "ReconciliationResult",
    "TransformationKind",
    "UndeclaredSemanticsError",
    "UnknownProjectionError",
    "UnsupportedBehavior",
    "UnsupportedSemanticsError",
]
