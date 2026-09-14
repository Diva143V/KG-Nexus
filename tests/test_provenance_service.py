from __future__ import annotations

import pytest

from core.activities.activity import Activity
from core.activities.agent import Agent, AgentKind
from core.assertions.assertion import Assertion
from core.evidence.evidence import Evidence
from core.provenance.errors import IncompleteLineageError
from core.provenance.provenance import AssertionOrigin, Provenance
from core.provenance.service import ProvenanceService
from core.resources.artifact import Artifact, ArtifactKind
from core.resources.parsed_record import ParsedRecord
from core.resources.source_release import SourceRelease
from tests.helpers import ident, utc


def register_source_assertion(
    service: ProvenanceService,
    *,
    assertion_id: str,
    agent_id: str = "curator-1",
    activity_id: str = "ingest-1",
    record_id: str = "p-1",
    artifact_id: str = "a-1",
    release_id: str = "rel-1",
) -> Assertion:
    agent = Agent(id=ident("agent", agent_id), label="curator", kind=AgentKind.HUMAN)
    service.register_agent(agent)
    release = SourceRelease(
        id=ident("release", release_id),
        source_id=ident("source", "s-1"),
        version="2026.1",
    )
    service.register_release(release)
    artifact = Artifact(
        id=ident("artifact", artifact_id),
        source_release_id=ident("release", release_id),
        kind=ArtifactKind.DATASET,
        name="export.json",
        media_type="application/ld+json",
        sha256="ab" * 32,
        size_bytes=1,
        retrieved_at=utc(2026, 1, 1),
    )
    service.register_artifact(artifact)
    record = ParsedRecord(
        id=ident("record", record_id),
        artifact_id=ident("artifact", artifact_id),
        record_type="csv_row",
        parsed_at=utc(2026, 1, 1),
    )
    service.register_record(record)
    activity = Activity(
        id=ident("activity", activity_id),
        type="ingestion",
        agent_id=ident("agent", agent_id),
        started_at=utc(2026, 1, 1),
        outputs=(ident("record", record_id),),
    )
    service.register_activity(activity)
    assertion = Assertion(
        id=ident("assertion", assertion_id),
        subject=ident("entity", "e-1"),
        predicate="causes",
        object=ident("entity", "e-2"),
        provenance=Provenance(
            assertion_origin=AssertionOrigin.SOURCE,
            agent_id=ident("agent", agent_id),
            activity_id=ident("activity", activity_id),
            asserted_at=utc(2026, 1, 1),
            method="extraction",
            input_resource_refs=(ident("record", record_id),),
        ),
        evidence=(Evidence(id=ident("evidence", "ev-1"), record_id=ident("record", record_id)),),
    )
    service.record_assertion(assertion)
    return assertion


def test_source_assertion_is_lineage_complete() -> None:
    service = ProvenanceService()
    assertion = register_source_assertion(service, assertion_id="a-1")
    service.validate_promotable(assertion)
    assert service.is_lineage_complete(assertion)


def test_derived_assertion_promotable_when_lineage_complete() -> None:
    service = ProvenanceService()
    source = register_source_assertion(service, assertion_id="a-1", activity_id="ingest-1")
    derived_activity = Activity(
        id=ident("activity", "derive-1"),
        type="derivation",
        agent_id=ident("agent", "curator-1"),
        started_at=utc(2026, 1, 2),
        inputs=(source.id,),
    )
    service.register_activity(derived_activity)
    derived = Assertion(
        id=ident("assertion", "a-2"),
        subject=ident("entity", "e-1"),
        predicate="treats",
        object=ident("entity", "e-3"),
        provenance=Provenance(
            assertion_origin=AssertionOrigin.DERIVED,
            agent_id=ident("agent", "curator-1"),
            activity_id=ident("activity", "derive-1"),
            asserted_at=utc(2026, 1, 2),
            input_assertion_refs=(source.id,),
            derivation_method="rule-inference",
        ),
    )
    service.record_assertion(derived)
    service.validate_promotable(derived)
    assert service.is_lineage_complete(derived)


def test_derived_assertion_missing_input_assertion_raises() -> None:
    service = ProvenanceService()
    agent = Agent(id=ident("agent", "curator-1"), label="curator", kind=AgentKind.HUMAN)
    service.register_agent(agent)
    activity = Activity(
        id=ident("activity", "derive-1"),
        type="derivation",
        agent_id=agent.id,
        started_at=utc(2026, 1, 2),
    )
    service.register_activity(activity)
    derived = Assertion(
        id=ident("assertion", "a-2"),
        subject=ident("entity", "e-1"),
        predicate="treats",
        object=ident("entity", "e-3"),
        provenance=Provenance(
            assertion_origin=AssertionOrigin.DERIVED,
            agent_id=agent.id,
            activity_id=activity.id,
            asserted_at=utc(2026, 1, 2),
            input_assertion_refs=(ident("assertion", "a-missing"),),
            derivation_method="rule-inference",
        ),
    )
    service.record_assertion(derived)
    assert not service.is_lineage_complete(derived)
    with pytest.raises(IncompleteLineageError):
        service.validate_promotable(derived)


def test_derived_assertion_missing_input_resource_raises() -> None:
    service = ProvenanceService()
    agent = Agent(id=ident("agent", "curator-1"), label="curator", kind=AgentKind.HUMAN)
    service.register_agent(agent)
    activity = Activity(
        id=ident("activity", "derive-1"),
        type="derivation",
        agent_id=agent.id,
        started_at=utc(2026, 1, 2),
    )
    service.register_activity(activity)
    derived = Assertion(
        id=ident("assertion", "a-2"),
        subject=ident("entity", "e-1"),
        predicate="treats",
        object=ident("entity", "e-3"),
        provenance=Provenance(
            assertion_origin=AssertionOrigin.DERIVED,
            agent_id=agent.id,
            activity_id=activity.id,
            asserted_at=utc(2026, 1, 2),
            input_resource_refs=(ident("record", "p-missing"),),
            derivation_method="rule-inference",
        ),
    )
    service.record_assertion(derived)
    with pytest.raises(IncompleteLineageError):
        service.validate_promotable(derived)


def test_missing_activity_raises() -> None:
    service = ProvenanceService()
    agent = Agent(id=ident("agent", "curator-1"), label="curator", kind=AgentKind.HUMAN)
    service.register_agent(agent)
    assertion = Assertion(
        id=ident("assertion", "a-1"),
        subject=ident("entity", "e-1"),
        predicate="causes",
        object=ident("entity", "e-2"),
        provenance=Provenance(
            assertion_origin=AssertionOrigin.SOURCE,
            agent_id=agent.id,
            activity_id=ident("activity", "not-registered"),
            asserted_at=utc(2026, 1, 1),
        ),
    )
    service.record_assertion(assertion)
    assert not service.is_lineage_complete(assertion)
    with pytest.raises(IncompleteLineageError):
        service.validate_promotable(assertion)


def test_missing_agent_raises() -> None:
    service = ProvenanceService()
    assertion = Assertion(
        id=ident("assertion", "a-1"),
        subject=ident("entity", "e-1"),
        predicate="causes",
        object=ident("entity", "e-2"),
        provenance=Provenance(
            assertion_origin=AssertionOrigin.SOURCE,
            agent_id=ident("agent", "not-registered"),
            activity_id=ident("activity", "act-1"),
            asserted_at=utc(2026, 1, 1),
        ),
    )
    service.record_assertion(assertion)
    with pytest.raises(IncompleteLineageError):
        service.validate_promotable(assertion)


def test_duplicate_registration_rejected() -> None:
    service = ProvenanceService()
    agent = Agent(id=ident("agent", "curator-1"), label="curator", kind=AgentKind.HUMAN)
    service.register_agent(agent)
    with pytest.raises(ValueError):
        service.register_agent(agent)
