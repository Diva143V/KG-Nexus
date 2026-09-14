"""Phase 10: Canonical Digest tests (metamorphic properties)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.assertions.assertion import Assertion
from core.assertions.assertion_state import AssertionStateEvent
from core.assertions.attribute import AttributeAssertion
from core.assertions.literal import LiteralType, LiteralValue, canonical_literal
from core.assertions.state import AssertionState
from core.digest.digester import CanonicalDigestService, DigestResult
from core.digest.profile import DigestProfile
from core.digest.record import CanonicalRecord
from core.provenance.provenance import Provenance
from tests.helpers import ident, utc

service = CanonicalDigestService()


def provenance(*, agent: str = "curator-1", activity: str = "act-1", day: int = 1) -> Provenance:
    return Provenance(
        agent_id=ident("agent", agent),
        activity_id=ident("activity", activity),
        asserted_at=utc(2026, 1, day),
    )


def relationship(
    *,
    subject: str = "e-1",
    predicate: str = "causes",
    obj: str = "e-2",
    status_at_creation: AssertionState = AssertionState.CANDIDATE,
    prov: Provenance | None = None,
) -> Assertion:
    return Assertion(
        id=ident("assertion", f"{subject}-{predicate}-{obj}"),
        subject=ident("entity", subject),
        predicate=predicate,
        object=ident("entity", obj),
        provenance=prov or provenance(),
        status_at_creation=status_at_creation,
    )


def attribute(
    *,
    subject: str = "e-1",
    predicate: str = "length",
    value: LiteralValue,
    prov: Provenance | None = None,
) -> AttributeAssertion:
    return AttributeAssertion(
        id=ident("assertion", f"{subject}-{predicate}"),
        subject=ident("entity", subject),
        predicate=predicate,
        value=value,
        provenance=prov or provenance(),
    )


def integer(value: int) -> LiteralValue:
    return LiteralValue(type=LiteralType.INTEGER, value=value)


def event(
    seq: str,
    to_state: AssertionState,
    from_state: AssertionState | None = None,
    day: int = 1,
) -> AssertionStateEvent:
    return AssertionStateEvent(
        event_id=ident("event", seq),
        assertion_id=ident("assertion", "e-1-causes-e-2"),
        from_state=from_state,
        to_state=to_state,
        agent_id=ident("agent", "curator-1"),
        activity_id=ident("activity", "act-1"),
        policy_version="policy-v1",
        reason_code="test",
        timestamp=utc(2026, 1, day),
    )


APPROVED_CHAIN = [
    event("e1", AssertionState.CANDIDATE, day=1),
    event("e2", AssertionState.VERIFIED, AssertionState.CANDIDATE, 2),
    event("e3", AssertionState.PROMOTION_REVIEW, AssertionState.VERIFIED, 3),
    event("e4", AssertionState.APPROVED, AssertionState.PROMOTION_REVIEW, 4),
]


class TestDeterminism:
    def test_same_input_same_digest(self) -> None:
        assertions = [relationship(), relationship(subject="e-3")]
        first = service.digest(assertions=assertions)
        second = service.digest(assertions=assertions)
        assert first.digest == second.digest

    def test_digest_result_fields(self) -> None:
        result = service.digest(assertions=[relationship()])
        assert isinstance(result, DigestResult)
        assert result.algorithm == "sha256"
        assert result.record_count == 1
        assert len(result.digest) == 64
        assert int(result.digest, 16) >= 0

    def test_empty_set_is_deterministic(self) -> None:
        assert service.digest().digest == service.digest().digest


class TestMetamorphicOrdering:
    def test_source_ordering_changes_same_digest(self) -> None:
        a = relationship(subject="e-1")
        b = relationship(subject="e-2")
        assert service.digest(assertions=[a, b]).digest == service.digest(assertions=[b, a]).digest

    def test_irrelevant_record_ordering_same_digest(self) -> None:
        svc = CanonicalDigestService()
        records = svc.build_records(
            assertions=[relationship(subject="e-1")],
            attribute_assertions=[attribute(subject="e-1", value=integer(10))],
        )
        assert (
            svc.digest_records(records).digest == svc.digest_records(list(reversed(records))).digest
        )

    def test_event_ordering_same_digest(self) -> None:
        reversed_chain = list(reversed(APPROVED_CHAIN))
        assert (
            service.digest(assertions=[relationship()], events=APPROVED_CHAIN).digest
            == service.digest(assertions=[relationship()], events=reversed_chain).digest
        )

    def test_projection_rebuild_same_digest(self) -> None:
        svc = CanonicalDigestService()
        records = svc.build_records(
            assertions=[relationship()],
            attribute_assertions=[attribute(value=integer(10))],
            events=APPROVED_CHAIN,
        )
        projected = [record.model_dump(mode="json") for record in records]
        rebuilt = [CanonicalRecord.model_validate(entry) for entry in projected]
        assert svc.digest_records(records).digest == svc.digest_records(rebuilt).digest


class TestProvenancePolicy:
    def test_provenance_only_change_same_digest_by_default(self) -> None:
        a = relationship(prov=provenance(agent="curator-1", day=1))
        b = relationship(prov=provenance(agent="curator-2", day=5))
        assert a.model_dump(exclude={"provenance"}) == b.model_dump(exclude={"provenance"})
        assert service.digest(assertions=[a]).digest == service.digest(assertions=[b]).digest

    def test_provenance_changes_digest_when_included(self) -> None:
        with_prov = CanonicalDigestService(profile=DigestProfile(include_provenance=True))
        a = relationship(prov=provenance(agent="curator-1", day=1))
        b = relationship(prov=provenance(agent="curator-2", day=5))
        assert with_prov.digest(assertions=[a]).digest != with_prov.digest(assertions=[b]).digest

    def test_provenance_inclusion_changes_digest(self) -> None:
        a = relationship()
        plain = CanonicalDigestService().digest(assertions=[a]).digest
        with_prov = (
            CanonicalDigestService(profile=DigestProfile(include_provenance=True))
            .digest(assertions=[a])
            .digest
        )
        assert plain != with_prov


class TestKinds:
    def test_relationship_assertion_digests(self) -> None:
        result = service.digest(assertions=[relationship()])
        assert result.record_count == 1

    def test_attribute_assertion_digests(self) -> None:
        result = service.digest(attribute_assertions=[attribute(value=integer(10))])
        assert result.record_count == 1

    def test_mixed_kinds_differ_by_target(self) -> None:
        rel = service.digest(assertions=[relationship()]).digest
        attr = service.digest(attribute_assertions=[attribute(value=integer(10))]).digest
        assert rel != attr

    def test_relationship_subject_predicate_object_deterministic(self) -> None:
        result = service.digest(assertions=[relationship(subject="e-1", predicate="p", obj="e-2")])
        other = service.digest(assertions=[relationship(subject="e-1", predicate="p", obj="e-3")])
        assert result.digest != other.digest


class TestStateResolution:
    def test_state_affects_digest(self) -> None:
        candidate = service.digest(assertions=[relationship()]).digest
        approved = service.digest(assertions=[relationship()], events=APPROVED_CHAIN).digest
        assert candidate != approved


class TestLiteralCanonicalization:
    def test_integer_canonical_form(self) -> None:
        assert canonical_literal(integer(10)) == "10"

    def test_float_round_trip(self) -> None:
        value = LiteralValue(type=LiteralType.FLOAT, value=1.5)
        assert canonical_literal(value) == "1.5"

    def test_boolean_canonical_form(self) -> None:
        assert canonical_literal(LiteralValue(type=LiteralType.BOOLEAN, value=True)) == "true"
        assert canonical_literal(LiteralValue(type=LiteralType.BOOLEAN, value=False)) == "false"

    def test_datetime_normalized_to_utc(self) -> None:
        aware = LiteralValue(type=LiteralType.DATETIME, value=utc(2026, 1, 1))
        assert canonical_literal(aware) == "2026-01-01T00:00:00+00:00"

    def test_string_canonical_form(self) -> None:
        value = LiteralValue(type=LiteralType.STRING, value="hello")
        assert canonical_literal(value) == "hello"

    def test_naive_datetime_rejected(self) -> None:
        naive = LiteralValue(
            type=LiteralType.DATETIME,
            value=utc(2026, 1, 1).replace(tzinfo=None),
        )
        with pytest.raises(ValueError, match="timezone-aware"):
            canonical_literal(naive)

    def test_value_must_match_type(self) -> None:
        with pytest.raises(ValidationError):
            LiteralValue(type=LiteralType.INTEGER, value="ten")
        with pytest.raises(ValidationError):
            LiteralValue(type=LiteralType.STRING, value=10)
        with pytest.raises(ValidationError):
            LiteralValue(type=LiteralType.BOOLEAN, value="yes")

    def test_equivalent_floats_same_digest(self) -> None:
        one = LiteralValue(type=LiteralType.FLOAT, value=1.0)
        also_one = LiteralValue(type=LiteralType.FLOAT, value=1.00)
        assert (
            service.digest(attribute_assertions=[attribute(value=one)]).digest
            == service.digest(attribute_assertions=[attribute(value=also_one)]).digest
        )

    def test_datetime_same_instant_same_digest(self) -> None:
        a = LiteralValue(type=LiteralType.DATETIME, value=utc(2026, 1, 1))
        assert (
            service.digest(attribute_assertions=[attribute(value=a)]).digest
            == service.digest(attribute_assertions=[attribute(value=a)]).digest
        )


class TestAttributeAssertion:
    def test_attribute_assertion_immutable(self) -> None:
        a = attribute(value=integer(10))
        with pytest.raises(ValidationError):
            a.value = integer(20)

    def test_attribute_assertion_requires_value(self) -> None:
        with pytest.raises(ValidationError):
            AttributeAssertion(  # type: ignore[call-arg]
                id=ident("assertion", "x"),
                subject=ident("entity", "e-1"),
                predicate="length",
                provenance=provenance(),
            )
