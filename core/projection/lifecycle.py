"""Projection lifecycle states and transitions.

Generic projection lifecycle used by the pluggable projection framework.
The lifecycle is backend-independent: Core knows how to manage projections
but never knows what any given projection is.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class ProjectionStatus(StrEnum):
    """States a projection moves through over its lifetime.

    Happy path:

        BUILDING -> VALIDATING -> RECONCILING -> READY -> ACTIVE
            -> RETAINED_FOR_ROLLBACK

    Failure states:

        FAILED
        QUARANTINED

    A projection that has failed validation or reconciliation is never
    activated.
    """

    BUILDING = "building"
    VALIDATING = "validating"
    RECONCILING = "reconciling"
    READY = "ready"
    ACTIVE = "active"
    RETAINED_FOR_ROLLBACK = "retained_for_rollback"
    FAILED = "failed"
    QUARANTINED = "quarantined"


class ProjectionTransition(BaseModel):
    """A single recorded transition in a projection's lifecycle."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    from_status: ProjectionStatus
    to_status: ProjectionStatus
    at: datetime
    reason: str = ""


class ProjectionStatusResolver:
    """Decides which status transitions a projection may take."""

    _TRANSITIONS: dict[ProjectionStatus, tuple[ProjectionStatus, ...]] = {
        ProjectionStatus.BUILDING: (
            ProjectionStatus.VALIDATING,
            ProjectionStatus.FAILED,
            ProjectionStatus.QUARANTINED,
        ),
        ProjectionStatus.VALIDATING: (
            ProjectionStatus.RECONCILING,
            ProjectionStatus.FAILED,
            ProjectionStatus.QUARANTINED,
        ),
        ProjectionStatus.RECONCILING: (
            ProjectionStatus.READY,
            ProjectionStatus.FAILED,
            ProjectionStatus.QUARANTINED,
        ),
        ProjectionStatus.READY: (
            ProjectionStatus.ACTIVE,
            ProjectionStatus.FAILED,
            ProjectionStatus.QUARANTINED,
        ),
        ProjectionStatus.ACTIVE: (
            ProjectionStatus.RETAINED_FOR_ROLLBACK,
            ProjectionStatus.QUARANTINED,
        ),
        ProjectionStatus.RETAINED_FOR_ROLLBACK: (
            ProjectionStatus.ACTIVE,
            ProjectionStatus.QUARANTINED,
        ),
        ProjectionStatus.FAILED: (ProjectionStatus.QUARANTINED,),
        ProjectionStatus.QUARANTINED: (),
    }

    def allowed_transitions(self, status: ProjectionStatus) -> tuple[ProjectionStatus, ...]:
        """Return the statuses reachable from ``status`` in one step."""
        return self._TRANSITIONS[status]

    def can_transition(self, current: ProjectionStatus, target: ProjectionStatus) -> bool:
        """Whether ``target`` is a legal next status from ``current``."""
        return target in self._TRANSITIONS[current]

    def can_activate(self, status: ProjectionStatus) -> bool:
        """Whether a projection in ``status`` may become ACTIVE."""
        return status is ProjectionStatus.READY or status is ProjectionStatus.RETAINED_FOR_ROLLBACK

    def is_terminal(self, status: ProjectionStatus) -> bool:
        """Whether ``status`` is terminal (no further transitions)."""
        return not self._TRANSITIONS[status]

    def is_failure(self, status: ProjectionStatus) -> bool:
        """Whether ``status`` is a failure state."""
        return status in (ProjectionStatus.FAILED, ProjectionStatus.QUARANTINED)


def now_utc() -> datetime:
    """Current UTC timestamp for lifecycle events."""
    return datetime.now(UTC)


def record_transition(
    *,
    from_status: ProjectionStatus,
    to_status: ProjectionStatus,
    at: datetime,
    reason: str,
    transitions: tuple[ProjectionTransition, ...],
) -> tuple[ProjectionTransition, ...]:
    """Return ``transitions`` with one new transition appended."""
    transition = ProjectionTransition(
        from_status=from_status,
        to_status=to_status,
        at=at,
        reason=reason,
    )
    return transitions + (transition,)
