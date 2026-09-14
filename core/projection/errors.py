"""Projection framework errors."""

from __future__ import annotations

from core.projection.lifecycle import ProjectionStatus


class ProjectionError(Exception):
    """Base class for projection errors."""


class UnknownProjectionError(ProjectionError):
    """Raised when operating on a projection the manager does not know."""

    def __init__(self, projection_id: str) -> None:
        self.projection_id = projection_id
        super().__init__(f"unknown projection: {projection_id}")


class InvalidProjectionTransitionError(ProjectionError):
    """Raised when a projection attempts an illegal status transition."""

    def __init__(self, current: ProjectionStatus, target: ProjectionStatus) -> None:
        self.current = current
        self.target = target
        super().__init__(f"invalid projection transition: {current.value} -> {target.value}")


class DuplicateBackendError(ProjectionError):
    """Raised when a backend id is registered more than once."""

    def __init__(self, backend_id: str) -> None:
        self.backend_id = backend_id
        super().__init__(f"backend already registered: {backend_id}")


class UnknownBackendError(ProjectionError):
    """Raised when a backend id is not registered."""

    def __init__(self, backend_id: str) -> None:
        self.backend_id = backend_id
        super().__init__(f"unknown backend: {backend_id}")


class ProjectionBuildError(ProjectionError):
    """Raised when a candidate projection cannot be built."""

    def __init__(self, projection_id: str, detail: str) -> None:
        self.projection_id = projection_id
        self.detail = detail
        super().__init__(f"projection {projection_id} failed to build: {detail}")


class ProjectionValidationError(ProjectionError):
    """Raised when a candidate projection fails validation."""

    def __init__(self, projection_id: str, reasons: tuple[str, ...]) -> None:
        self.projection_id = projection_id
        self.reasons = reasons
        super().__init__(f"projection {projection_id} failed validation: " + "; ".join(reasons))


class ProjectionReconciliationError(ProjectionError):
    """Raised when a candidate projection fails reconciliation."""

    def __init__(self, projection_id: str, detail: str) -> None:
        self.projection_id = projection_id
        self.detail = detail
        super().__init__(f"projection {projection_id} failed reconciliation: {detail}")


class NoActiveProjectionError(ProjectionError):
    """Raised when a rollback is requested with no active projection."""

    def __init__(self, projection_id: str) -> None:
        self.projection_id = projection_id
        super().__init__(f"no active projection to roll back: {projection_id}")


class NoRetainedProjectionError(ProjectionError):
    """Raised when a rollback has nothing retained to restore."""

    def __init__(self, projection_id: str) -> None:
        self.projection_id = projection_id
        super().__init__(f"no retained projection to restore: {projection_id}")


class ActiveProjectionError(ProjectionError):
    """Raised when an ACTIVE projection cannot be modified or destroyed."""

    def __init__(self, projection_id: str) -> None:
        self.projection_id = projection_id
        super().__init__(f"projection is active: {projection_id}")
