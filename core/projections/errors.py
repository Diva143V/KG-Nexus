"""Projection lifecycle errors."""

from __future__ import annotations

from core.identifiers.identifier import Identifier
from core.projections.status import ProjectionStatus


class ProjectionError(Exception):
    """Base class for projection lifecycle errors."""


class UnknownProjectionError(ProjectionError):
    """Raised when operating on a projection not managed by the manager."""

    def __init__(self, projection_id: Identifier) -> None:
        self.projection_id = projection_id
        super().__init__(f"unknown projection: {projection_id.canonical}")


class InvalidProjectionTransitionError(ProjectionError):
    """Raised when a projection attempts an illegal status transition."""

    def __init__(self, current: ProjectionStatus, target: ProjectionStatus) -> None:
        self.current = current
        self.target = target
        super().__init__(f"invalid projection transition: {current.value} -> {target.value}")


class ActiveProjectionError(ProjectionError):
    """Raised when mutating an ACTIVE or retained projection in place."""

    def __init__(self, projection_id: Identifier) -> None:
        self.projection_id = projection_id
        super().__init__(f"active projections are immutable in place: {projection_id.canonical}")


class ProjectionValidationError(ProjectionError):
    """Raised when a projection fails validation or reconciliation."""

    def __init__(self, projection_id: Identifier, reasons: list[str]) -> None:
        self.projection_id = projection_id
        self.reasons = tuple(reasons)
        super().__init__(f"projection {projection_id.canonical} failed: " + "; ".join(self.reasons))
