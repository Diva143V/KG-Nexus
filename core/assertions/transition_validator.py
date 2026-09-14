"""Validation of assertion state transitions.

The transition table is the single source of truth for which transitions the
lifecycle allows. Rejected, abstained, superseded, and retracted assertions
are terminal: they have no outgoing transitions. Re-assertion must create a
new assertion rather than reviving a rejected one.
"""

from __future__ import annotations

from core.assertions.state import AssertionState


class AssertionStateError(Exception):
    """Base class for assertion-state resolution failures."""


class InvalidTransitionError(AssertionStateError):
    """A state transition that is not allowed."""


_ALLOWED_TRANSITIONS: dict[AssertionState, frozenset[AssertionState]] = {
    AssertionState.CANDIDATE: frozenset(
        {AssertionState.VERIFIED, AssertionState.REJECTED, AssertionState.ABSTAINED}
    ),
    AssertionState.VERIFIED: frozenset({AssertionState.PROMOTION_REVIEW, AssertionState.REJECTED}),
    AssertionState.PROMOTION_REVIEW: frozenset({AssertionState.APPROVED, AssertionState.REJECTED}),
    AssertionState.APPROVED: frozenset({AssertionState.SUPERSEDED, AssertionState.RETRACTED}),
    AssertionState.REJECTED: frozenset(),
    AssertionState.ABSTAINED: frozenset(),
    AssertionState.SUPERSEDED: frozenset(),
    AssertionState.RETRACTED: frozenset(),
}


class TransitionValidator:
    """Validates a single assertion state transition."""

    def is_allowed(self, from_state: AssertionState, to_state: AssertionState) -> bool:
        """Return whether ``from_state -> to_state`` is a legal transition."""
        return to_state in _ALLOWED_TRANSITIONS[from_state]

    def validate(self, from_state: AssertionState, to_state: AssertionState) -> None:
        """Raise ``InvalidTransitionError`` if the transition is illegal."""
        if not self.is_allowed(from_state, to_state):
            raise InvalidTransitionError(f"transition {from_state} -> {to_state} is not allowed")
