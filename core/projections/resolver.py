"""Projection status resolution: legal transitions and preconditions."""

from __future__ import annotations

from core.projections.status import ProjectionStatus


class ProjectionStatusResolver:
    """Decides which status transitions a projection may take.

    The allowed transitions encode the lifecycle:

        BUILDING -> VALIDATING -> RECONCILED -> READY -> ACTIVE
            -> RETAINED_FOR_ROLLBACK

    ``RETAINED_FOR_ROLLBACK`` is terminal: an actively running projection
    cannot change.
    """

    _TRANSITIONS: dict[ProjectionStatus, tuple[ProjectionStatus, ...]] = {
        ProjectionStatus.BUILDING: (ProjectionStatus.VALIDATING,),
        ProjectionStatus.VALIDATING: (ProjectionStatus.RECONCILED,),
        ProjectionStatus.RECONCILED: (ProjectionStatus.READY,),
        ProjectionStatus.READY: (ProjectionStatus.ACTIVE,),
        ProjectionStatus.ACTIVE: (ProjectionStatus.RETAINED_FOR_ROLLBACK,),
        ProjectionStatus.RETAINED_FOR_ROLLBACK: (),
    }

    def allowed_transitions(self, status: ProjectionStatus) -> tuple[ProjectionStatus, ...]:
        """Return the statuses reachable from ``status`` in one step."""
        return self._TRANSITIONS[status]

    def can_transition(self, current: ProjectionStatus, target: ProjectionStatus) -> bool:
        """Whether ``target`` is a legal next status from ``current``."""
        return target in self._TRANSITIONS[current]

    def can_activate(self, status: ProjectionStatus) -> bool:
        """Whether a projection in ``status`` may become ACTIVE."""
        return status is ProjectionStatus.READY

    def can_retain(self, status: ProjectionStatus) -> bool:
        """Whether a projection in ``status`` may become RETAINED_FOR_ROLLBACK."""
        return status is ProjectionStatus.ACTIVE

    def is_terminal(self, status: ProjectionStatus) -> bool:
        """Whether ``status`` is terminal (no further transitions)."""
        return not self._TRANSITIONS[status]
