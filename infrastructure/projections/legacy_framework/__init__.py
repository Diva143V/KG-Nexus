"""Projection framework: generic, profile-driven projections over authoritative RDF."""

from __future__ import annotations

from infrastructure.projections.legacy_framework.builder import (
    ProjectionBuilder,
    UndeclaredSemanticsError,
    UnsupportedSemanticsError,
)
from infrastructure.projections.legacy_framework.content import (
    ProjectedEdge,
    ProjectedNode,
    ProjectionContent,
)
from infrastructure.projections.legacy_framework.errors import (
    ActiveProjectionError,
    InvalidProjectionTransitionError,
    ProjectionError,
    ProjectionValidationError,
    UnknownProjectionError,
)
from infrastructure.projections.legacy_framework.manager import ProjectionManager
from infrastructure.projections.legacy_framework.profile import (
    FieldTransformation,
    ProjectionProfile,
    ReconciliationMethod,
    TransformationKind,
    UnsupportedBehavior,
)
from infrastructure.projections.legacy_framework.projection import (
    Projection,
    ProjectionGate,
    ProjectionTransition,
)
from infrastructure.projections.legacy_framework.reconciler import (
    ProjectionReconciler,
    ReconciliationOutcome,
    ReconciliationResult,
)
from infrastructure.projections.legacy_framework.resolver import ProjectionStatusResolver
from infrastructure.projections.legacy_framework.status import ProjectionStatus
from infrastructure.projections.legacy_framework.validator import ProjectionValidator

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
