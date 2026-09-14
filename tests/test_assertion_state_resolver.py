from __future__ import annotations

import pytest

from core.assertions.assertion import Assertion
from core.assertions.assertion_state import AssertionStateEvent
from core.assertions.resolver import (
    AssertionStateResolver,
    CreationEventError,
    DuplicateEventError,
    StateMismatchError,
)
from core.assertions.state import AssertionState
from core.assertions.transition_validator import InvalidTransitionError
from core.provenance.provenance import Provenance
from tests.helpers import ident, utc

resolver = AssertionStateResolver()


def make_assertion(state: AssertionState = AssertionState.CANDIDATE) -> Assertion:
    return Assertion(
        id=ident("assertion", "a-1"),
        subject=ident("entity", "e-1"),
        predicate="causes",
        object=ident("entity", "e-2"),
        provenance=Provenance(
            agent_id=ident("agent", "curator-1"),
            activity_id=ident("activity", "act-1"),
            asserted_at=utc(2026, 1, 1),
        ),
        status_at_creation=state,
    )


def event(
    seq: str,
    to_state: AssertionState,
    from_state: AssertionState | None = None,
    day: int = 1,
) -> AssertionStateEvent:
    return AssertionStateEvent(
        event_id=ident("event", seq),
        assertion_id=ident("assertion", "a-1"),
        from_state=from_state,
        to_state=to_state,
        agent_id=ident("agent", "curator-1"),
        activity_id=ident("activity", "act-1"),
        policy_version="policy-v1",
        reason_code="initial",
        timestamp=utc(2026, 1, day),
    )


def test_no_events_returns_creation_state() -> None:
    assertion = make_assertion()
    assert resolver.resolve(assertion, []) == AssertionState.CANDIDATE


def test_valid_chain_resolves_current_state() -> None:
    assertion = make_assertion()
    events = [
        event("e1", AssertionState.CANDIDATE, day=1),
        event("e2", AssertionState.VERIFIED, from_state=AssertionState.CANDIDATE, day=2),
        event("e3", AssertionState.PROMOTION_REVIEW, from_state=AssertionState.VERIFIED, day=3),
        event("e4", AssertionState.APPROVED, from_state=AssertionState.PROMOTION_REVIEW, day=4),
    ]
    assert resolver.resolve(assertion, events) == AssertionState.APPROVED


def test_retraction_chain() -> None:
    assertion = make_assertion()
    events = [
        event("e1", AssertionState.CANDIDATE, day=1),
        event("e2", AssertionState.VERIFIED, from_state=AssertionState.CANDIDATE, day=2),
        event("e3", AssertionState.PROMOTION_REVIEW, from_state=AssertionState.VERIFIED, day=3),
        event("e4", AssertionState.APPROVED, from_state=AssertionState.PROMOTION_REVIEW, day=4),
        event("e5", AssertionState.RETRACTED, from_state=AssertionState.APPROVED, day=5),
    ]
    assert resolver.resolve(assertion, events) == AssertionState.RETRACTED


def test_ordering_is_deterministic_regardless_of_input_order() -> None:
    assertion = make_assertion()
    events = [
        event("e4", AssertionState.APPROVED, from_state=AssertionState.PROMOTION_REVIEW, day=4),
        event("e1", AssertionState.CANDIDATE, day=1),
        event("e3", AssertionState.PROMOTION_REVIEW, from_state=AssertionState.VERIFIED, day=3),
        event("e2", AssertionState.VERIFIED, from_state=AssertionState.CANDIDATE, day=2),
    ]
    assert resolver.resolve(assertion, events) == AssertionState.APPROVED


def test_ordering_by_event_id_when_timestamps_equal() -> None:
    assertion = make_assertion()
    events = [
        event("e-b", AssertionState.VERIFIED, from_state=AssertionState.CANDIDATE, day=1),
        event("e-a", AssertionState.CANDIDATE, day=1),
    ]
    assert resolver.resolve(assertion, events) == AssertionState.VERIFIED


def test_from_state_mismatch_raises() -> None:
    assertion = make_assertion()
    events = [
        event("e1", AssertionState.CANDIDATE, day=1),
        event("e2", AssertionState.VERIFIED, from_state=AssertionState.APPROVED, day=2),
    ]
    with pytest.raises(StateMismatchError):
        resolver.resolve(assertion, events)


def test_illegal_transition_raises() -> None:
    assertion = make_assertion()
    events = [
        event("e1", AssertionState.CANDIDATE, day=1),
        event("e2", AssertionState.APPROVED, from_state=AssertionState.CANDIDATE, day=2),
    ]
    with pytest.raises(InvalidTransitionError):
        resolver.resolve(assertion, events)


def test_first_event_from_state_must_be_none() -> None:
    assertion = make_assertion()
    events = [event("e1", AssertionState.CANDIDATE, from_state=AssertionState.CANDIDATE, day=1)]
    with pytest.raises(CreationEventError):
        resolver.resolve(assertion, events)


def test_first_event_must_match_creation_state() -> None:
    assertion = make_assertion(state=AssertionState.CANDIDATE)
    events = [event("e1", AssertionState.VERIFIED, day=1)]
    with pytest.raises(CreationEventError):
        resolver.resolve(assertion, events)


def test_corrupted_chain_missing_creation_event_raises() -> None:
    assertion = make_assertion()
    events = [
        event("e2", AssertionState.VERIFIED, from_state=AssertionState.CANDIDATE, day=2),
    ]
    with pytest.raises(CreationEventError):
        resolver.resolve(assertion, events)


def test_duplicate_events_raise() -> None:
    assertion = make_assertion()
    duplicate = event("e1", AssertionState.CANDIDATE, day=1)
    events = [
        duplicate,
        duplicate,
        event("e2", AssertionState.VERIFIED, from_state=AssertionState.CANDIDATE, day=2),
    ]
    with pytest.raises(DuplicateEventError):
        resolver.resolve(assertion, events)


def test_resolver_does_not_mutate_assertion() -> None:
    assertion = make_assertion()
    events = [
        event("e1", AssertionState.CANDIDATE, day=1),
        event("e2", AssertionState.VERIFIED, from_state=AssertionState.CANDIDATE, day=2),
    ]
    resolver.resolve(assertion, events)
    assert assertion.status_at_creation == AssertionState.CANDIDATE
