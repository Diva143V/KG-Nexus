from __future__ import annotations

import pytest

from core.activities.activity import Activity
from core.activities.agent import Agent, AgentKind
from core.assertions.assertion import Assertion
from core.evidence.evidence import Evidence
from core.provenance.errors import UnresolvedReferenceError
from core.provenance.lineage import Lineage, LineageResolver
from core.provenance.provenance import AssertionOrigin, Provenance
from core.provenance.service import ProvenanceService
from core.resources.artifact import Artifact, ArtifactKind
from core.resources.parsed_record import ParsedRecord
from core.resources.source_release import SourceRelease
from tests.helpers import ident, utc


def register_source(
    service: ProvenanceService,
    *,
    tag: str,
    day: int,
) -> Assertion:
    agent = Agent(id=ident("agent", "curator-1"), label="curator", kind=AgentKind.HUMAN)
    if service.get_agent(agent.id) is None:
        service.register_agent(agent)
    release = SourceRelease(
        id=ident("release", f"rel-{tag}"),
        source_id=ident("source", f"src-{tag}"),
        version="2026.1",
    )
    service.register_release(release)
    artifact = Artifact(
        id=ident("artifact", f"art-{tag}"),
        source_release_id=ident("release", f"rel-{tag}"),
        kind=ArtifactKind.DATASET,
        name=f"{tag}.json",
        media_type="application/ld+json",
        sha256="ab" * 32,
        size_bytes=1,
        retrieved_at=utc(2026, 1, 1),
    )
    service.register_artifact(artifact)
    record = ParsedRecord(
        id=ident("record", f"rec-{tag}"),
        artifact_id=ident("artifact", f"art-{tag}"),
        record_type="csv_row",
        parsed_at=utc(2026, 1, day),
    )
    service.register_record(record)
    activity = Activity(
        id=ident("activity", f"ingest-{tag}"),
        type="ingestion",
        agent_id=agent.id,
        started_at=utc(2026, 1, day),
        outputs=(record.id,),
    )
    service.register_activity(activity)
    assertion = Assertion(
        id=ident("assertion", f"src-{tag}"),
        subject=ident("entity", "e-1"),
        predicate="causes",
        object=ident("entity", "e-2"),
        provenance=Provenance(
            assertion_origin=AssertionOrigin.SOURCE,
            agent_id=agent.id,
            activity_id=activity.id,
            asserted_at=utc(2026, 1, day),
            method="extraction",
            input_resource_refs=(record.id,),
        ),
        evidence=(Evidence(id=ident("evidence", f"ev-{tag}"), record_id=record.id),),
    )
    service.record_assertion(assertion)
    return assertion


def register_derived(
    service: ProvenanceService,
    *,
    assertion_id: str,
    activity_id: str,
    inputs: tuple[Assertion, ...],
    day: int,
) -> Assertion:
    activity = Activity(
        id=ident("activity", activity_id),
        type="derivation",
        agent_id=ident("agent", "curator-1"),
        started_at=utc(2026, 1, day),
        inputs=tuple(item.id for item in inputs),
    )
    service.register_activity(activity)
    assertion = Assertion(
        id=ident("assertion", assertion_id),
        subject=ident("entity", "e-1"),
        predicate="treats",
        object=ident("entity", "e-3"),
        provenance=Provenance(
            assertion_origin=AssertionOrigin.DERIVED,
            agent_id=ident("agent", "curator-1"),
            activity_id=activity.id,
            asserted_at=utc(2026, 1, day),
            input_assertion_refs=tuple(item.id for item in inputs),
            derivation_method="rule-inference",
        ),
    )
    service.record_assertion(assertion)
    return assertion


def build_multi_source() -> tuple[ProvenanceService, dict[str, Assertion]]:
    service = ProvenanceService()
    src_a = register_source(service, tag="a", day=1)
    src_b = register_source(service, tag="b", day=2)
    derived = register_derived(
        service,
        assertion_id="derived-1",
        activity_id="merge-1",
        inputs=(src_a, src_b),
        day=3,
    )
    return service, {"src_a": src_a, "src_b": src_b, "derived": derived}


def test_source_assertion_lineage() -> None:
    service, assertions = build_multi_source()
    resolver = LineageResolver(service)
    lineage = resolver.resolve(assertions["src_a"])
    assert lineage.activity.id == ident("activity", "ingest-a")
    assert lineage.agent.id == ident("agent", "curator-1")
    assert lineage.input_assertions == ()
    assert lineage.input_records == (service.get_record(ident("record", "rec-a")),)
    assert lineage.artifacts == (service.get_artifact(ident("artifact", "art-a")),)
    assert lineage.releases == (service.get_release(ident("release", "rel-a")),)


def test_derived_assertion_lineage() -> None:
    service, assertions = build_multi_source()
    resolver = LineageResolver(service)
    lineage = resolver.resolve(assertions["derived"])
    assert lineage.activity.id == ident("activity", "merge-1")
    assert lineage.agent.id == ident("agent", "curator-1")
    assert lineage.input_assertions == (assertions["src_a"], assertions["src_b"])
    assert lineage.input_records == ()
    assert lineage.artifacts == ()
    assert lineage.releases == ()


def test_multi_source_provenance() -> None:
    service, assertions = build_multi_source()
    resolver = LineageResolver(service)
    ancestors = resolver.ancestors(assertions["derived"])
    assert ancestors == (assertions["src_a"], assertions["src_b"])
    for source in ancestors:
        lineage = resolver.resolve(source)
        assert lineage.releases
        assert lineage.artifacts
        assert lineage.input_records


def test_lineage_traversal_ancestors() -> None:
    service, assertions = build_multi_source()
    resolver = LineageResolver(service)
    derived_2 = register_derived(
        service,
        assertion_id="derived-2",
        activity_id="merge-2",
        inputs=(assertions["derived"],),
        day=4,
    )
    ancestors = resolver.ancestors(derived_2)
    assert ancestors == (
        assertions["derived"],
        assertions["src_a"],
        assertions["src_b"],
    )


def test_lineage_traversal_descendants() -> None:
    service, assertions = build_multi_source()
    resolver = LineageResolver(service)
    assert resolver.descendants(assertions["src_a"]) == (assertions["derived"],)
    assert resolver.descendants(assertions["derived"]) == ()


def test_lineage_is_immutable() -> None:
    service, assertions = build_multi_source()
    resolver = LineageResolver(service)
    lineage = resolver.resolve(assertions["src_a"])
    assert isinstance(lineage, Lineage)
    with pytest.raises((ValueError, TypeError)):
        lineage.activity = service.get_activity(ident("activity", "ingest-b"))


def test_missing_provenance_raises() -> None:
    service = ProvenanceService()
    resolver = LineageResolver(service)
    assertion = Assertion(
        id=ident("assertion", "orphan"),
        subject=ident("entity", "e-1"),
        predicate="causes",
        object=ident("entity", "e-2"),
        provenance=Provenance(
            assertion_origin=AssertionOrigin.SOURCE,
            agent_id=ident("agent", "nobody"),
            activity_id=ident("activity", "nothing"),
            asserted_at=utc(2026, 1, 1),
            input_resource_refs=(ident("record", "missing"),),
        ),
    )
    with pytest.raises(UnresolvedReferenceError):
        resolver.resolve(assertion)
