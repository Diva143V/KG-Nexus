from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.provenance.provenance import AssertionOrigin, Provenance
from tests.helpers import ident, utc


def base_provenance() -> Provenance:
    return Provenance(
        assertion_origin=AssertionOrigin.SOURCE,
        agent_id=ident("agent", "curator-1"),
        activity_id=ident("activity", "ingest-1"),
        asserted_at=utc(2026, 1, 1),
    )


def test_provenance_constructed() -> None:
    provenance = base_provenance()
    assert provenance.assertion_origin is AssertionOrigin.SOURCE
    assert provenance.input_assertion_refs == ()
    assert provenance.input_resource_refs == ()


def test_provenance_requires_agent_activity_and_time() -> None:
    with pytest.raises(ValidationError):
        Provenance(agent_id=ident("agent", "curator-1"), asserted_at=utc(2026, 1, 1))


def test_provenance_is_frozen() -> None:
    provenance = base_provenance()
    with pytest.raises((ValueError, TypeError)):
        provenance.method = "manual"


def test_derived_provenance_requires_derivation_method() -> None:
    with pytest.raises(ValidationError):
        Provenance(
            assertion_origin=AssertionOrigin.DERIVED,
            agent_id=ident("agent", "curator-1"),
            activity_id=ident("activity", "derive-1"),
            asserted_at=utc(2026, 1, 1),
            input_assertion_refs=(ident("assertion", "a-1"),),
        )


def test_derived_provenance_requires_input_refs() -> None:
    with pytest.raises(ValidationError):
        Provenance(
            assertion_origin=AssertionOrigin.DERIVED,
            agent_id=ident("agent", "curator-1"),
            activity_id=ident("activity", "derive-1"),
            asserted_at=utc(2026, 1, 1),
            derivation_method="merge",
        )


def test_derived_provenance_valid() -> None:
    provenance = Provenance(
        assertion_origin=AssertionOrigin.DERIVED,
        agent_id=ident("agent", "curator-1"),
        activity_id=ident("activity", "derive-1"),
        asserted_at=utc(2026, 1, 1),
        input_assertion_refs=(ident("assertion", "a-1"), ident("assertion", "a-2")),
        input_resource_refs=(ident("record", "p-1"),),
        derivation_method="rule-merge",
    )
    assert provenance.derivation_method == "rule-merge"
    assert len(provenance.input_assertion_refs) == 2
    assert len(provenance.input_resource_refs) == 1


def test_provenance_serialization_roundtrip() -> None:
    provenance = base_provenance()
    restored = Provenance.model_validate(provenance.model_dump(mode="json"))
    assert restored == provenance
