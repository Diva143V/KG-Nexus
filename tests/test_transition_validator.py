from __future__ import annotations

import pytest

from core.assertions.state import AssertionState
from core.assertions.transition_validator import (
    InvalidTransitionError,
    TransitionValidator,
)

validator = TransitionValidator()

VALID_TRANSITIONS = [
    (AssertionState.CANDIDATE, AssertionState.VERIFIED),
    (AssertionState.CANDIDATE, AssertionState.REJECTED),
    (AssertionState.CANDIDATE, AssertionState.ABSTAINED),
    (AssertionState.VERIFIED, AssertionState.PROMOTION_REVIEW),
    (AssertionState.VERIFIED, AssertionState.REJECTED),
    (AssertionState.PROMOTION_REVIEW, AssertionState.APPROVED),
    (AssertionState.PROMOTION_REVIEW, AssertionState.REJECTED),
    (AssertionState.APPROVED, AssertionState.SUPERSEDED),
    (AssertionState.APPROVED, AssertionState.RETRACTED),
]


@pytest.mark.parametrize(("from_state", "to_state"), VALID_TRANSITIONS)
def test_valid_transitions_are_allowed(
    from_state: AssertionState,
    to_state: AssertionState,
) -> None:
    assert validator.is_allowed(from_state, to_state)
    validator.validate(from_state, to_state)


def test_rejected_to_approved_is_forbidden() -> None:
    assert not validator.is_allowed(AssertionState.REJECTED, AssertionState.APPROVED)
    with pytest.raises(InvalidTransitionError):
        validator.validate(AssertionState.REJECTED, AssertionState.APPROVED)


def test_approved_to_candidate_is_forbidden() -> None:
    assert not validator.is_allowed(AssertionState.APPROVED, AssertionState.CANDIDATE)
    with pytest.raises(InvalidTransitionError):
        validator.validate(AssertionState.APPROVED, AssertionState.CANDIDATE)


def test_terminal_states_have_no_outgoing_transitions() -> None:
    terminal = [
        AssertionState.REJECTED,
        AssertionState.ABSTAINED,
        AssertionState.SUPERSEDED,
        AssertionState.RETRACTED,
    ]
    for state in terminal:
        for candidate in AssertionState:
            assert not validator.is_allowed(state, candidate)
