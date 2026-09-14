from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from core.assertions.assertion import Assertion
from core.assertions.assertion_state import AssertionStateEvent
from core.assertions.confidence import Confidence, ConfidenceMethod
from core.assertions.state import AssertionState
from core.provenance.provenance import Provenance
from tests.helpers import ident, utc


def provenance() -> Provenance:
    return Provenance(
        agent_id=ident("agent", "curator-1"),
        activity_id=ident("activity", "act-1"),
        asserted_at=utc(2026, 1, 1),
    )


def make_assertion() -> Assertion:
    return Assertion(
        id=ident("assertion", "a-1"),
        subject=ident("entity", "e-1"),
        predicate="causes",
        object=ident("entity", "e-2"),
        provenance=provenance(),
    )


def make_state_event(
    to_state: AssertionState = AssertionState.CANDIDATE,
    timestamp: datetime | None = None,
) -> AssertionStateEvent:
    return AssertionStateEvent(
        event_id=ident("event", "e-1"),
        assertion_id=ident("assertion", "a-1"),
        to_state=to_state,
        agent_id=ident("agent", "curator-1"),
        activity_id=ident("activity", "act-1"),
        policy_version="policy-v1",
        reason_code="initial",
        timestamp=timestamp if timestamp is not None else utc(2026, 1, 1),
    )


def test_assertion_constructed() -> None:
    assertion = make_assertion()
    assert assertion.status_at_creation == AssertionState.CANDIDATE
    assert assertion.evidence == ()
    assert assertion.confidence is None


def test_assertion_requires_provenance() -> None:
    with pytest.raises(ValidationError):
        Assertion(
            id=ident("assertion", "a-1"),
            subject=ident("entity", "e-1"),
            predicate="causes",
            object=ident("entity", "e-2"),
        )


def test_assertion_requires_predicate() -> None:
    with pytest.raises(ValidationError):
        Assertion(
            id=ident("assertion", "a-1"),
            subject=ident("entity", "e-1"),
            predicate="",
            object=ident("entity", "e-2"),
            provenance=provenance(),
        )


def test_assertion_is_frozen() -> None:
    assertion = make_assertion()
    with pytest.raises((ValueError, TypeError)):
        assertion.predicate = "associated"


def test_assertion_serialization_roundtrip() -> None:
    assertion = make_assertion()
    restored = Assertion.model_validate(assertion.model_dump(mode="json"))
    assert restored == assertion
    assert assertion.model_dump_json() == restored.model_dump_json()


def test_confidence_valid() -> None:
    confidence = Confidence(score=0.9, method=ConfidenceMethod.MODEL, source="pipeline-v1")
    assert confidence.score == 0.9


def test_confidence_rejects_out_of_range_score() -> None:
    with pytest.raises(ValidationError):
        Confidence(score=1.5)


def test_confidence_rejects_invalid_method() -> None:
    with pytest.raises(ValidationError):
        Confidence(score=0.5, method="guessed")


def test_state_event_constructed() -> None:
    event = make_state_event()
    assert event.to_state == AssertionState.CANDIDATE
    assert event.from_state is None
    assert event.agent_id == ident("agent", "curator-1")
    assert event.activity_id == ident("activity", "act-1")
    assert event.policy_version == "policy-v1"
    assert event.reason_code == "initial"


def test_state_event_requires_full_transition_metadata() -> None:
    with pytest.raises(ValidationError):
        AssertionStateEvent(
            event_id=ident("event", "e-1"),
            assertion_id=ident("assertion", "a-1"),
            to_state=AssertionState.CANDIDATE,
            timestamp=utc(2026, 1, 1),
        )


def test_state_event_requires_aware_datetime() -> None:
    with pytest.raises(ValidationError):
        AssertionStateEvent(
            event_id=ident("event", "e-1"),
            assertion_id=ident("assertion", "a-1"),
            to_state=AssertionState.CANDIDATE,
            agent_id=ident("agent", "curator-1"),
            activity_id=ident("activity", "act-1"),
            policy_version="policy-v1",
            reason_code="initial",
            timestamp=datetime(2026, 1, 1),
        )


def test_state_event_rejects_invalid_state() -> None:
    with pytest.raises(ValidationError):
        AssertionStateEvent(
            event_id=ident("event", "e-1"),
            assertion_id=ident("assertion", "a-1"),
            to_state="definitely",
            agent_id=ident("agent", "curator-1"),
            activity_id=ident("activity", "act-1"),
            policy_version="policy-v1",
            reason_code="initial",
            timestamp=utc(2026, 1, 1),
        )


def test_state_event_is_frozen() -> None:
    event = make_state_event()
    with pytest.raises((ValueError, TypeError)):
        event.to_state = AssertionState.VERIFIED
