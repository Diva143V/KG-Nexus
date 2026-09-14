from __future__ import annotations

import pytest

from core.activities.activity import Activity
from core.activities.agent import Agent, AgentKind
from core.assertions.assertion import Assertion
from core.assertions.state import AssertionState
from core.assertions.state_machine import AssertionStateMachine
from core.provenance.errors import IncompleteLineageError
from core.provenance.provenance import AssertionOrigin, Provenance
from core.provenance.service import ProvenanceService
from tests.helpers import ident, utc


def make_assertion(
    *,
    assertion_id: str,
    provenance: Provenance,
) -> Assertion:
    return Assertion(
        id=ident("assertion", assertion_id),
        subject=ident("entity", "e-1"),
        predicate="causes",
        object=ident("entity", "e-2"),
        provenance=provenance,
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


def walk_to_promotion_review(
    machine: AssertionStateMachine,
    assertion: Assertion,
) -> list[object]:
    events: list[object] = [machine.create(assertion, **metadata("e1", 1))]
    events.append(
        machine.transition(assertion, events, AssertionState.VERIFIED, **metadata("e2", 2))
    )
    events.append(
        machine.transition(
            assertion,
            events,
            AssertionState.PROMOTION_REVIEW,
            **metadata("e3", 3),
        )
    )
    return events


def test_promotion_guard_rejects_derived_with_missing_lineage() -> None:
    service = ProvenanceService()
    agent = Agent(id=ident("agent", "curator-1"), label="curator", kind=AgentKind.HUMAN)
    service.register_agent(agent)
    activity = Activity(
        id=ident("activity", "act-1"),
        type="derivation",
        agent_id=agent.id,
        started_at=utc(2026, 1, 1),
    )
    service.register_activity(activity)
    derived = make_assertion(
        assertion_id="a-2",
        provenance=Provenance(
            assertion_origin=AssertionOrigin.DERIVED,
            agent_id=agent.id,
            activity_id=activity.id,
            asserted_at=utc(2026, 1, 1),
            input_assertion_refs=(ident("assertion", "a-missing"),),
            derivation_method="rule-inference",
        ),
    )
    machine = AssertionStateMachine(promotion_guard=service.validate_promotable)
    events = walk_to_promotion_review(machine, derived)
    with pytest.raises(IncompleteLineageError):
        machine.transition(
            assertion=derived,
            events=events,
            to_state=AssertionState.APPROVED,
            **metadata("e4", 4),
        )


def test_promotion_guard_allows_complete_derived_lineage() -> None:
    service = ProvenanceService()
    agent = Agent(id=ident("agent", "curator-1"), label="curator", kind=AgentKind.HUMAN)
    service.register_agent(agent)
    source = make_assertion(
        assertion_id="a-1",
        provenance=Provenance(
            assertion_origin=AssertionOrigin.SOURCE,
            agent_id=agent.id,
            activity_id=ident("activity", "act-1"),
            asserted_at=utc(2026, 1, 1),
        ),
    )
    service.record_assertion(source)
    activity = Activity(
        id=ident("activity", "act-1"),
        type="derivation",
        agent_id=agent.id,
        started_at=utc(2026, 1, 1),
        inputs=(source.id,),
    )
    service.register_activity(activity)
    derived = make_assertion(
        assertion_id="a-2",
        provenance=Provenance(
            assertion_origin=AssertionOrigin.DERIVED,
            agent_id=agent.id,
            activity_id=activity.id,
            asserted_at=utc(2026, 1, 1),
            input_assertion_refs=(source.id,),
            derivation_method="rule-inference",
        ),
    )
    machine = AssertionStateMachine(promotion_guard=service.validate_promotable)
    events = walk_to_promotion_review(machine, derived)
    approved = machine.transition(
        assertion=derived, events=events, to_state=AssertionState.APPROVED, **metadata("e4", 4)
    )
    assert approved.to_state == AssertionState.APPROVED


def test_promotion_guard_not_called_for_non_approved_transitions() -> None:
    calls: list[str] = []

    def guard(assertion: Assertion) -> None:
        calls.append(assertion.id.canonical)

    machine = AssertionStateMachine(promotion_guard=guard)
    assertion = make_assertion(
        assertion_id="a-1",
        provenance=Provenance(
            assertion_origin=AssertionOrigin.SOURCE,
            agent_id=ident("agent", "curator-1"),
            activity_id=ident("activity", "act-1"),
            asserted_at=utc(2026, 1, 1),
        ),
    )
    created = machine.create(assertion, **metadata("e1", 1))
    machine.transition(assertion, [created], AssertionState.VERIFIED, **metadata("e2", 2))
    assert calls == []
