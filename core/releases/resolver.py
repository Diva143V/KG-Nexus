"""Release status resolution: legal transitions and preconditions."""

from __future__ import annotations

from core.releases.status import ReleaseStatus


class ReleaseStatusResolver:
    """Decides which status transitions a release may take.

    The allowed transitions encode the lifecycle:

        CANDIDATE -> VALIDATING -> VALIDATED -> PROJECTED
            -> RECONCILED -> APPROVED -> PUBLISHED

    plus ``QUARANTINED`` as the failure sink. ``PUBLISHED`` is terminal:
    a published release cannot change.
    """

    _TRANSITIONS: dict[ReleaseStatus, tuple[ReleaseStatus, ...]] = {
        ReleaseStatus.CANDIDATE: (ReleaseStatus.VALIDATING, ReleaseStatus.QUARANTINED),
        ReleaseStatus.VALIDATING: (ReleaseStatus.VALIDATED, ReleaseStatus.QUARANTINED),
        ReleaseStatus.VALIDATED: (ReleaseStatus.PROJECTED, ReleaseStatus.QUARANTINED),
        ReleaseStatus.PROJECTED: (ReleaseStatus.RECONCILED, ReleaseStatus.QUARANTINED),
        ReleaseStatus.RECONCILED: (ReleaseStatus.APPROVED, ReleaseStatus.QUARANTINED),
        ReleaseStatus.APPROVED: (ReleaseStatus.PUBLISHED, ReleaseStatus.QUARANTINED),
        ReleaseStatus.PUBLISHED: (),
        ReleaseStatus.QUARANTINED: (),
    }

    def allowed_transitions(self, status: ReleaseStatus) -> tuple[ReleaseStatus, ...]:
        """Return the statuses reachable from ``status`` in one step."""
        return self._TRANSITIONS[status]

    def can_transition(self, current: ReleaseStatus, target: ReleaseStatus) -> bool:
        """Whether ``target`` is a legal next status from ``current``."""
        return target in self._TRANSITIONS[current]

    def can_approve(self, status: ReleaseStatus) -> bool:
        """Whether a release in ``status`` may become APPROVED.

        Approval requires passing through validation and reconciliation.
        """
        return status is ReleaseStatus.RECONCILED

    def can_publish(self, status: ReleaseStatus) -> bool:
        """Whether a release in ``status`` may become PUBLISHED."""
        return status is ReleaseStatus.APPROVED

    def is_terminal(self, status: ReleaseStatus) -> bool:
        """Whether ``status`` is terminal (no further transitions)."""
        return not self._TRANSITIONS[status]

    def quarantine_sink(self) -> ReleaseStatus:
        """The status failed releases are moved to."""
        return ReleaseStatus.QUARANTINED
