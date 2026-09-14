from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.assertions.assertion import Assertion
from core.assertions.assertion_state import AssertionStateEvent
from core.assertions.resolver import AssertionStateResolver, CreationEventError
from core.assertions.state import AssertionState
from core.assertions.state_machine import AssertionStateMachine
from core.assertions.transition_validator import InvalidTransitionError
from core.provenance.provenance import Provenance
from tests.helpers import ident, utc

machine = AssertionStateMachine()
resolver = AssertionStateResolver()

MANDATORY_PASS = [
    (AssertionState.CANDIDATE, AssertionState.VERIFIED),
    (AssertionState.VERIFIED, AssertionState.PROMOTION_REVIEW),
    (AssertionState.PROMOTION_REVIEW, AssertionState.APPROVED),
    (AssertionState.APPROVED, AssertionState.RETRACTED),
]


def make_assertion(status_at_creation: AssertionState = AssertionState.CANDIDATE) -> Assertion:
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
        status_at_creation=status_at_creation,
    )


def metadata(seq: str, day: int) -> dict[str, object]:
    return {
        "event_id": ident("event", seq),
        "agent_id": ident("agent", "curator-1"),
        "activity_id": ident("activity", "act-1"),
        "policy_version": "policy-v1",
        "reason_code": "step",
        "timestamp": utc(2026, 1, day),
    }


def test_create_produces_initial_event() -> None:
    assertion = make_assertion()
    created = machine.create(assertion, **metadata("e1", 1))
    assert created.from_state is None
    assert created.to_state == AssertionState.CANDIDATE
    assert created.assertion_id == assertion.id
    assert resolver.resolve(assertion, [created]) == AssertionState.CANDIDATE


@pytest.mark.parametrize(("from_state", "to_state"), MANDATORY_PASS)
def test_mandatory_valid_transitions(
    from_state: AssertionState,
    to_state: AssertionState,
) -> None:
    assertion = make_assertion(status_at_creation=from_state)
    created = machine.create(assertion, **metadata("e1", 1))
    transitioned = machine.transition(
        assertion,
        [created],
        to_state,
        **metadata("e2", 2),
    )
    assert transitioned.from_state == from_state
    assert transitioned.to_state == to_state
    assert resolver.resolve(assertion, [created, transitioned]) == to_state


def test_full_chain_via_machine() -> None:
    assertion = make_assertion()
    created = machine.create(assertion, **metadata("e1", 1))
    verified = machine.transition(
        assertion, [created], AssertionState.VERIFIED, **metadata("e2", 2)
    )
    review = machine.transition(
        assertion,
        [created, verified],
        AssertionState.PROMOTION_REVIEW,
        **metadata("e3", 3),
    )
    approved = machine.transition(
        assertion,
        [created, verified, review],
        AssertionState.APPROVED,
        **metadata("e4", 4),
    )
    retracted = machine.transition(
        assertion,
        [created, verified, review, approved],
        AssertionState.RETRACTED,
        **metadata("e5", 5),
    )
    assert (
        resolver.resolve(assertion, [created, verified, review, approved, retracted])
        == AssertionState.RETRACTED
    )


def test_rejected_to_approved_fails() -> None:
    assertion = make_assertion(status_at_creation=AssertionState.REJECTED)
    created = machine.create(assertion, **metadata("e1", 1))
    with pytest.raises(InvalidTransitionError):
        machine.transition(
            assertion,
            [created],
            AssertionState.APPROVED,
            **metadata("e2", 2),
        )


def test_approved_to_candidate_fails() -> None:
    assertion = make_assertion(status_at_creation=AssertionState.APPROVED)
    created = machine.create(assertion, **metadata("e1", 1))
    with pytest.raises(InvalidTransitionError):
        machine.transition(
            assertion,
            [created],
            AssertionState.CANDIDATE,
            **metadata("e2", 2),
        )


def test_rejected_assertion_reasserts_via_new_assertion() -> None:
    original = make_assertion(status_at_creation=AssertionState.REJECTED)
    created = machine.create(original, **metadata("e1", 1))
    with pytest.raises(InvalidTransitionError):
        machine.transition(original, [created], AssertionState.APPROVED, **metadata("e2", 2))
    reasserted = make_assertion()
    reasserted_event = machine.create(reasserted, **metadata("r1", 1))
    assert reasserted_event.to_state == AssertionState.CANDIDATE


def test_corrupted_chain_fails_before_producing_event() -> None:
    assertion = make_assertion()
    forged = AssertionStateEvent(
        event_id=ident("event", "e1"),
        assertion_id=assertion.id,
        to_state=AssertionState.VERIFIED,
        agent_id=ident("agent", "curator-1"),
        activity_id=ident("activity", "act-1"),
        policy_version="policy-v1",
        reason_code="step",
        timestamp=utc(2026, 1, 2),
    )
    with pytest.raises(CreationEventError):
        machine.transition(
            assertion,
            [forged],
            AssertionState.PROMOTION_REVIEW,
            **metadata("e2", 3),
        )


def test_transition_requires_valid_metadata() -> None:
    assertion = make_assertion()
    created = machine.create(assertion, **metadata("e1", 1))
    with pytest.raises(ValidationError):
        machine.transition(
            assertion,
            [created],
            AssertionState.VERIFIED,
            event_id=ident("event", "e2"),
            agent_id=ident("agent", "curator-1"),
            activity_id=ident("activity", "act-1"),
            policy_version="",
            reason_code="step",
            timestamp=utc(2026, 1, 2),
        )


def test_machine_does_not_mutate_assertion() -> None:
    assertion = make_assertion()
    before = assertion.model_dump()
    created = machine.create(assertion, **metadata("e1", 1))
    machine.transition(assertion, [created], AssertionState.VERIFIED, **metadata("e2", 2))
    assert assertion.model_dump() == before
