"""Phase 11: RDF Authority tests."""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from core.assertions.assertion import Assertion
from core.assertions.assertion_state import AssertionStateEvent
from core.assertions.attribute import AttributeAssertion
from core.assertions.literal import LiteralType, LiteralValue
from core.assertions.state import AssertionState
from core.provenance.provenance import Provenance
from core.rdf import (
    IRI,
    NamedGraph,
    NamedGraphCategory,
    RDFAuthority,
    RDFDataset,
    RDFLiteral,
    RDFReleaseReader,
    RDFReleaseWriter,
    Triple,
    graph_name,
)
from core.rdf.reader import ReleaseSnapshot
from core.rdf.terms import BlankNode, blank, iri, string_literal
from core.rdf.writer import ASN_STATE, RLS_DIGEST, RLS_STATUS, RLS_VERSION
from core.releases.manifest import LockfileSet, ReleaseManifest
from core.releases.release import Release, ReleaseGate
from core.releases.status import ReleaseStatus
from infrastructure.rdf.memory import MemoryRDFBackend, conforms_to_backend
from infrastructure.rdf.serialization import to_nquads
from tests.helpers import ident, utc

LOCK = LockfileSet(
    ontology=ident("lockfile", "ontology-1.0"),
    runtime=ident("lockfile", "runtime-1.0"),
    reasoner=ident("lockfile", "reasoner-1.0"),
    projection=ident("lockfile", "projection-1.0"),
)


def manifest() -> ReleaseManifest:
    return ReleaseManifest(
        source_artifacts=(ident("artifact", "a-1"),),
        assertions=(ident("assertion", "a-1"),),
        policies=(ident("policy", "p-1"),),
        plugins=(ident("plugin", "plug-1"),),
        lockfiles=LOCK,
    )


def release(status: ReleaseStatus = ReleaseStatus.PUBLISHED) -> Release:
    return Release(
        id=ident("release", "kg-2026.1"),
        version="2026.1",
        status=status,
        manifest=manifest(),
        created_at=utc(2026, 1, 1),
        published_at=utc(2026, 1, 2) if status is ReleaseStatus.PUBLISHED else None,
        gate=ReleaseGate(
            structural=True,
            logical=True,
            application=True,
            evidence=True,
            projection=True,
            reconciliation=True,
        ),
    )


def provenance(*, agent: str = "curator-1", day: int = 1) -> Provenance:
    return Provenance(
        agent_id=ident("agent", agent),
        activity_id=ident("activity", "act-1"),
        asserted_at=utc(2026, 1, day),
    )


def relationship(
    *,
    aid: str = "a-1",
    subject: str = "e-1",
    predicate: str = "causes",
    obj: str = "e-2",
) -> Assertion:
    return Assertion(
        id=ident("assertion", aid),
        subject=ident("entity", subject),
        predicate=predicate,
        object=ident("entity", obj),
        provenance=provenance(),
    )


def attribute(
    *,
    aid: str = "at-1",
    subject: str = "e-1",
    predicate: str = "length",
    value: LiteralValue | None = None,
) -> AttributeAssertion:
    return AttributeAssertion(
        id=ident("assertion", aid),
        subject=ident("entity", subject),
        predicate=predicate,
        value=value or LiteralValue(type=LiteralType.INTEGER, value=42),
        provenance=provenance(),
    )


def event(
    seq: str,
    to_state: AssertionState,
    from_state: AssertionState | None,
    *,
    aid: str = "a-1",
    day: int = 1,
) -> AssertionStateEvent:
    return AssertionStateEvent(
        event_id=ident("event", seq),
        assertion_id=ident("assertion", aid),
        from_state=from_state,
        to_state=to_state,
        agent_id=ident("agent", "curator-1"),
        activity_id=ident("activity", "act-1"),
        policy_version="policy-v1",
        reason_code="test",
        timestamp=utc(2026, 1, day),
    )


APPROVED_CHAIN = [
    event("e1", AssertionState.CANDIDATE, None, day=1),
    event("e2", AssertionState.VERIFIED, AssertionState.CANDIDATE, day=2),
    event("e3", AssertionState.PROMOTION_REVIEW, AssertionState.VERIFIED, day=3),
    event("e4", AssertionState.APPROVED, AssertionState.PROMOTION_REVIEW, day=4),
]


class TestRDFTerms:
    def test_iri_term(self) -> None:
        term = iri("urn:example:thing")
        assert term.kind == "iri"
        assert term.value == "urn:example:thing"

    def test_blank_node_term(self) -> None:
        term = blank("b-1")
        assert term.kind == "blank"
        assert term.label == "b-1"

    def test_literal_term(self) -> None:
        term = string_literal("hello")
        assert term.kind == "literal"
        assert term.value == "hello"

    def test_literal_rejects_both_datatype_and_language(self) -> None:
        with pytest.raises(ValidationError):
            RDFLiteral(value="x", datatype="urn:d", language="en")

    def test_triple_requires_iri_predicate(self) -> None:
        with pytest.raises(ValidationError):
            Triple(subject=blank("b"), predicate=string_literal("p"), object=blank("b2"))

    def test_triple_rejects_literal_subject(self) -> None:
        with pytest.raises(ValidationError):
            Triple(
                subject=string_literal("x"),
                predicate=iri("urn:p"),
                object=blank("b"),
            )

    def test_term_discriminated_by_kind(self) -> None:
        parsed = IRI.model_validate({"kind": "iri", "value": "urn:x"})
        assert isinstance(parsed, IRI)
        parsed = RDFLiteral.model_validate({"kind": "literal", "value": "v", "datatype": "urn:d"})
        assert isinstance(parsed, RDFLiteral)
        parsed = BlankNode.model_validate({"kind": "blank", "label": "b"})
        assert isinstance(parsed, BlankNode)


class TestNamedGraphs:
    def test_seven_categories(self) -> None:
        assert len(NamedGraphCategory) == 7

    def test_graph_names(self) -> None:
        assert graph_name(NamedGraphCategory.ONTOLOGY) == "urn:graph:ontology"
        assert graph_name(NamedGraphCategory.APPROVED_ASSERTION) == "urn:graph:approved_assertion"

    def test_named_graph_size(self) -> None:
        graph = NamedGraph(
            name="urn:graph:ontology",
            triples=(Triple(subject=iri("urn:s"), predicate=iri("urn:p"), object=iri("urn:o")),),
        )
        assert graph.size == 1

    def test_dataset_graph_lookup(self) -> None:
        dataset = RDFDataset(
            graphs=(NamedGraph(name="urn:graph:ontology"), NamedGraph(name="urn:graph:mapping"))
        )
        assert dataset.graph("urn:graph:ontology") is not None
        assert dataset.graph("urn:graph:nope") is None
        assert dataset.graph_names() == ("urn:graph:ontology", "urn:graph:mapping")


class TestWriterSnapshot:
    def test_builds_seven_named_graphs(self) -> None:
        dataset = RDFReleaseWriter().build_snapshot(release=release())
        names = set(dataset.graph_names())
        assert names == {graph_name(category) for category in NamedGraphCategory}

    def test_release_metadata_triples(self) -> None:
        dataset = RDFReleaseWriter().build_snapshot(release=release())
        metadata = dataset.graph(graph_name(NamedGraphCategory.RELEASE_METADATA))
        assert metadata is not None
        values = {triple.predicate.value: triple.object.value for triple in metadata.triples}
        assert values[RLS_VERSION] == "2026.1"
        assert values[RLS_STATUS] == "published"
        assert RLS_DIGEST in values
        assert len(values[RLS_DIGEST]) == 64

    def test_unpublished_release_has_no_published_at(self) -> None:
        dataset = RDFReleaseWriter().build_snapshot(release=release(status=ReleaseStatus.APPROVED))
        metadata = dataset.graph(graph_name(NamedGraphCategory.RELEASE_METADATA))
        assert metadata is not None
        predicates = {triple.predicate.value for triple in metadata.triples}
        assert "urn:release:published_at" not in predicates

    def test_source_assertions_land_in_source_graph(self) -> None:
        dataset = RDFReleaseWriter().build_snapshot(release=release(), assertions=[relationship()])
        source = dataset.graph(graph_name(NamedGraphCategory.SOURCE_ASSERTION))
        approved = dataset.graph(graph_name(NamedGraphCategory.APPROVED_ASSERTION))
        assert source is not None and approved is not None
        assert source.size >= 5
        assert approved.size == 0

    def test_approved_assertions_land_in_approved_graph(self) -> None:
        dataset = RDFReleaseWriter().build_snapshot(
            release=release(), assertions=[relationship()], events=APPROVED_CHAIN
        )
        source = dataset.graph(graph_name(NamedGraphCategory.SOURCE_ASSERTION))
        approved = dataset.graph(graph_name(NamedGraphCategory.APPROVED_ASSERTION))
        assert source is not None and approved is not None
        assert source.size == 0
        assert approved.size >= 5

    def test_attribute_assertion_in_source_graph(self) -> None:
        dataset = RDFReleaseWriter().build_snapshot(
            release=release(), attribute_assertions=[attribute()]
        )
        source = dataset.graph(graph_name(NamedGraphCategory.SOURCE_ASSERTION))
        assert source is not None
        assert source.size >= 5

    def test_attribute_literal_uses_xsd_datatype(self) -> None:
        dataset = RDFReleaseWriter().build_snapshot(
            release=release(), attribute_assertions=[attribute()]
        )
        source = dataset.graph(graph_name(NamedGraphCategory.SOURCE_ASSERTION))
        assert source is not None
        objects = [triple.object for triple in source.triples]
        literal = next(obj for obj in objects if isinstance(obj, RDFLiteral) and obj.value == "42")
        assert literal.datatype == "http://www.w3.org/2001/XMLSchema#integer"

    def test_provenance_triples_present(self) -> None:
        dataset = RDFReleaseWriter().build_snapshot(release=release(), assertions=[relationship()])
        prov = dataset.graph(graph_name(NamedGraphCategory.PROVENANCE))
        assert prov is not None
        predicates = {triple.predicate.value for triple in prov.triples}
        assert {"urn:prov:agent", "urn:prov:activity", "urn:prov:asserted_at"} <= predicates

    def test_snapshot_is_deterministic(self) -> None:
        writer = RDFReleaseWriter()
        first = writer.build_snapshot(
            release=release(),
            assertions=[relationship()],
            attribute_assertions=[attribute()],
            events=APPROVED_CHAIN,
        )
        second = writer.build_snapshot(
            release=release(),
            assertions=[relationship()],
            attribute_assertions=[attribute()],
            events=APPROVED_CHAIN,
        )
        assert to_nquads(first) == to_nquads(second)

    def test_includes_ontology_mapping_and_validation(self) -> None:
        ontology = NamedGraph(
            name="custom",
            triples=(
                Triple(
                    subject=iri("urn:s"),
                    predicate=iri("urn:p"),
                    object=iri("urn:o"),
                ),
            ),
        )
        mapping = NamedGraph(name="custom-mapping")
        dataset = RDFReleaseWriter().build_snapshot(
            release=release(), ontology=ontology, mapping=mapping
        )
        assert dataset.graph(graph_name(NamedGraphCategory.ONTOLOGY)) is not None
        assert dataset.graph(graph_name(NamedGraphCategory.ONTOLOGY)).size == 1
        assert dataset.graph(graph_name(NamedGraphCategory.MAPPING)).size == 0


class TestAuthority:
    def test_write_read_snapshot_roundtrip(self) -> None:
        writer = RDFReleaseWriter()
        dataset = writer.build_snapshot(release=release(), assertions=[relationship()])
        backend = MemoryRDFBackend()
        authority = RDFAuthority(backend=backend)
        authority.write_snapshot(dataset)
        read = authority.read_snapshot()
        assert read == dataset

    def test_read_graph(self) -> None:
        backend = MemoryRDFBackend()
        authority = RDFAuthority(backend=backend)
        authority.write_snapshot(RDFReleaseWriter().build_snapshot(release=release()))
        graph = authority.read_graph(graph_name(NamedGraphCategory.RELEASE_METADATA))
        assert graph is not None
        assert graph.name == graph_name(NamedGraphCategory.RELEASE_METADATA)

    def test_missing_graph_returns_none(self) -> None:
        authority = RDFAuthority(backend=MemoryRDFBackend())
        assert authority.read_graph("urn:graph:unknown") is None

    def test_backend_conforms_to_protocol(self) -> None:
        assert conforms_to_backend(MemoryRDFBackend())
        assert not conforms_to_backend(object())


class TestReader:
    def test_reads_release_metadata(self) -> None:
        dataset = RDFReleaseWriter().build_snapshot(release=release())
        snapshot = RDFReleaseReader().read(dataset)
        assert isinstance(snapshot, ReleaseSnapshot)
        assert snapshot.release_id.endswith("release:kg-2026.1")
        assert snapshot.version == "2026.1"
        assert snapshot.status == "published"
        assert snapshot.digest is not None

    def test_reads_assertion_counts(self) -> None:
        dataset = RDFReleaseWriter().build_snapshot(
            release=release(),
            assertions=[relationship()],
            attribute_assertions=[attribute()],
            events=APPROVED_CHAIN,
        )
        snapshot = RDFReleaseReader().read(dataset)
        assert snapshot.source_assertion_count == 1
        assert snapshot.approved_assertion_count == 1

    def test_reader_requires_metadata_graph(self) -> None:
        with pytest.raises(ValueError, match="metadata"):
            RDFReleaseReader().read(RDFDataset())


class TestNQuads:
    def test_serializes_deterministically(self) -> None:
        dataset = RDFReleaseWriter().build_snapshot(release=release())
        first = to_nquads(dataset)
        second = to_nquads(dataset)
        assert first == second

    def test_serialization_shape(self) -> None:
        dataset = RDFReleaseWriter().build_snapshot(release=release())
        text = to_nquads(dataset)
        assert "<urn:graph:release_metadata>" in text
        for line in text.splitlines():
            assert line.endswith("> .")


def test_state_predicate_is_constant() -> None:
    assert ASN_STATE == "urn:assertion:state"
    assert RLS_STATUS == "urn:release:status"


def test_datetime_must_be_aware() -> None:
    writer = RDFReleaseWriter()
    naive = Release(
        id=ident("release", "x"),
        version="1.0",
        status=ReleaseStatus.CANDIDATE,
        manifest=manifest(),
        created_at=datetime(2026, 1, 1),
    )
    with pytest.raises(ValueError):
        writer.build_snapshot(release=naive)
