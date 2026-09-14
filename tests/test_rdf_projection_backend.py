"""Phase 15: RDF Projection Backend tests.

Exercises the downstream RDF projection end to end: an authoritative RDF
release is redeployed as a projected RDF dataset — preserving named graphs,
identifiers, assertions, provenance, and release metadata — through the
pluggable ProjectionBackend contract. RDF stays authoritative; the
projection is never a second semantic authority.
"""

from __future__ import annotations

from hashlib import sha256

import pytest

from core.assertions.assertion import Assertion
from core.assertions.assertion_state import AssertionStateEvent
from core.assertions.attribute import AttributeAssertion
from core.assertions.literal import LiteralType, LiteralValue
from core.assertions.state import AssertionState
from core.identifiers.identifier import Identifier
from core.projection import (
    FieldTransformation,
    ProjectionBackend,
    ProjectionManager,
    ProjectionProfile,
    ProjectionReconciler,
    ProjectionRegistry,
    ProjectionStatus,
    ReconciliationStrategy,
    TransformationKind,
    UnsupportedBehavior,
)
from core.projection.errors import InvalidProjectionTransitionError
from core.provenance.provenance import Provenance
from core.rdf import (
    IRI,
    NamedGraph,
    NamedGraphCategory,
    RDFDataset,
    RDFReleaseWriter,
    graph_name,
)
from core.rdf.writer import (
    ASN_PREDICATE,
    ASN_STATE,
    ASN_TYPE_RELATIONSHIP,
    RLS_STATUS,
    RLS_VERSION,
)
from core.releases.manifest import LockfileSet, ReleaseManifest
from core.releases.release import Release, ReleaseGate
from core.releases.status import ReleaseStatus
from infrastructure.projections.rdf import (
    MemoryRDFDataSource,
    MemoryRDFProjectionStore,
    RDFProjectionBackend,
    RDFProjectionBuilder,
    RDFProjectionPolicy,
    RDFReconciler,
    RDFReconciliationReport,
    RDFSmokeTestRunner,
    RDFUnsupportedSemanticsError,
    UnknownRDFProjectionError,
    policy_from_profile,
    rdf_candidate_name,
)
from infrastructure.projections.rdf.terms import term_value
from tests.helpers import ident, utc

RELEASE_ID = "release:kg-2026.1"
PROJECTION_VALUE = "rdf-2026-001"

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


def release() -> Release:
    return Release(
        id=ident("release", "kg-2026.1"),
        version="2026.1",
        status=ReleaseStatus.PUBLISHED,
        manifest=manifest(),
        created_at=utc(2026, 1, 1),
        published_at=utc(2026, 1, 2),
        gate=ReleaseGate(
            structural=True,
            logical=True,
            application=True,
            evidence=True,
            projection=True,
            reconciliation=True,
        ),
    )


def prov(*, agent: str = "curator-1", day: int = 1) -> Provenance:
    return Provenance(
        agent_id=ident("agent", agent),
        activity_id=ident("activity", "act-1"),
        asserted_at=utc(2026, 1, day),
    )


def relationship(*, aid: str, subject: Identifier, predicate: str, obj: Identifier) -> Assertion:
    return Assertion(
        id=ident("assertion", aid),
        subject=subject,
        predicate=predicate,
        object=obj,
        provenance=prov(),
    )


def attribute(
    *,
    aid: str,
    subject: Identifier,
    predicate: str,
    value: LiteralValue,
) -> AttributeAssertion:
    return AttributeAssertion(
        id=ident("assertion", aid),
        subject=subject,
        predicate=predicate,
        value=value,
        provenance=prov(),
    )


def event(
    seq: str,
    to_state: AssertionState,
    from_state: AssertionState | None,
    *,
    aid: str,
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


def approved_events(aid: str) -> tuple[AssertionStateEvent, ...]:
    return (
        event(f"e1-{aid}", AssertionState.CANDIDATE, None, aid=aid, day=1),
        event(f"e2-{aid}", AssertionState.VERIFIED, AssertionState.CANDIDATE, aid=aid, day=2),
        event(
            f"e3-{aid}",
            AssertionState.PROMOTION_REVIEW,
            AssertionState.VERIFIED,
            aid=aid,
            day=3,
        ),
        event(
            f"e4-{aid}",
            AssertionState.APPROVED,
            AssertionState.PROMOTION_REVIEW,
            aid=aid,
            day=4,
        ),
    )


def release_dataset() -> RDFDataset:
    assertions = [
        relationship(
            aid="a-1",
            subject=ident("gene", "EGFR"),
            predicate="interacts_with",
            obj=ident("protein", "P53"),
        ),
        relationship(
            aid="a-2",
            subject=ident("gene", "EGFR"),
            predicate="regulates",
            obj=ident("gene", "MYC"),
        ),
        # source (non-approved) assertion: stays in the source graph
        relationship(
            aid="a-9",
            subject=ident("entity", "e-9"),
            predicate="causes",
            obj=ident("entity", "e-10"),
        ),
    ]
    attributes = [
        attribute(
            aid="at-1",
            subject=ident("gene", "EGFR"),
            predicate="length",
            value=LiteralValue(type=LiteralType.INTEGER, value=42),
        ),
    ]
    events = approved_events("a-1") + approved_events("a-2") + approved_events("at-1")
    return RDFReleaseWriter().build_snapshot(
        release=release(),
        assertions=assertions,
        attribute_assertions=attributes,
        events=events,
    )


def profile(
    *,
    included_relations: tuple[str, ...] = (),
    included_entity_types: tuple[str, ...] = (),
    included_assertion_types: tuple[str, ...] = (),
    transformations: tuple[FieldTransformation, ...] = (),
    dropped_semantics: tuple[str, ...] = (),
    unsupported_semantics: tuple[str, ...] = (),
    unsupported_behavior: UnsupportedBehavior = UnsupportedBehavior.ERROR,
) -> ProjectionProfile:
    return ProjectionProfile(
        profile_id="rdf-redeploy",
        profile_version="1",
        source_release_type="approved",
        preserved_fields=("urn:graph:release_metadata",),
        included_relations=included_relations,
        included_entity_types=included_entity_types,
        included_assertion_types=included_assertion_types,
        transformations=transformations,
        dropped_semantics=dropped_semantics,
        unsupported_semantics=unsupported_semantics,
        unsupported_behavior=unsupported_behavior,
        reconciliation_strategy=ReconciliationStrategy.REBUILD,
    )


def make_backend() -> tuple[RDFProjectionBackend, MemoryRDFProjectionStore, MemoryRDFDataSource]:
    store = MemoryRDFProjectionStore()
    data_source = MemoryRDFDataSource()
    data_source.put(RELEASE_ID, release_dataset())
    backend = RDFProjectionBackend(store=store, data_source=data_source)
    return backend, store, data_source


def projection_id() -> Identifier:
    return ident("projection", PROJECTION_VALUE)


def assertion_node(aid: str) -> str:
    """RDF IRI of an assertion node, matching the Phase 11 writer."""
    return f"urn:assertion:{ident('assertion', aid).canonical}"


def nodes(*aids: str) -> set[str]:
    """Set of assertion-node IRIs for the given assertion ids."""
    return {assertion_node(aid) for aid in aids}


def build_candidate(backend: RDFProjectionBackend) -> None:
    backend.build(
        projection_id=projection_id().canonical,
        release_id=RELEASE_ID,
        profile=profile(),
    )


def approved_subjects(
    store: MemoryRDFProjectionStore,
    projection_value: str = PROJECTION_VALUE,
) -> set[str]:
    store_key = rdf_candidate_name(f"projection:{projection_value}")
    dataset = store.read_dataset(store_key)
    assert dataset is not None
    approved = dataset.graph(graph_name(NamedGraphCategory.APPROVED_ASSERTION))
    assert approved is not None
    return {
        term_value(triple.subject)
        for triple in approved.triples
        if triple.predicate.value == ASN_PREDICATE
    }


def provenance_subjects(
    store: MemoryRDFProjectionStore,
    projection_value: str = PROJECTION_VALUE,
) -> set[str]:
    store_key = rdf_candidate_name(f"projection:{projection_value}")
    dataset = store.read_dataset(store_key)
    assert dataset is not None
    prov = dataset.graph(graph_name(NamedGraphCategory.PROVENANCE))
    assert prov is not None
    return {triple.subject.value for triple in prov.triples if isinstance(triple.subject, IRI)}


# --- store / naming --------------------------------------------------------


def test_candidate_name_is_scoped() -> None:
    assert rdf_candidate_name("projection:p1") == "rdf_projection:p1_candidate"


def test_memory_store_roundtrip() -> None:
    store = MemoryRDFProjectionStore()
    dataset = release_dataset()
    store.write_dataset("k1", dataset)
    assert store.read_dataset("k1") == dataset
    assert store.triple_count("k1") == dataset.triple_count()
    assert store.graph_names("k1") == dataset.graph_names()


# --- full copy -------------------------------------------------------------


def test_full_copy_projection_equals_release() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    projected = store.read_dataset(rdf_candidate_name(projection_id().canonical))
    assert projected == release_dataset()


def test_projection_preserves_graphs_metadata_provenance_and_identifiers() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    projected = store.read_dataset(rdf_candidate_name(projection_id().canonical))
    assert projected is not None
    assert set(projected.graph_names()) == {graph_name(category) for category in NamedGraphCategory}

    metadata = projected.graph(graph_name(NamedGraphCategory.RELEASE_METADATA))
    assert metadata is not None
    values = {triple.predicate.value: triple.object.value for triple in metadata.triples}
    assert values[RLS_VERSION] == "2026.1"
    assert values[RLS_STATUS] == "published"

    prov = projected.graph(graph_name(NamedGraphCategory.PROVENANCE))
    assert prov is not None
    predicates = {triple.predicate.value for triple in prov.triples}
    assert {"urn:prov:agent", "urn:prov:activity", "urn:prov:asserted_at"} <= predicates

    approved = projected.graph(graph_name(NamedGraphCategory.APPROVED_ASSERTION))
    assert approved is not None
    objects = {triple.object.value for triple in approved.triples if isinstance(triple.object, IRI)}
    assert "urn:identifier:gene:EGFR" in objects


def test_build_is_deterministic() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    first = store.read_dataset(rdf_candidate_name(projection_id().canonical))

    other = MemoryRDFProjectionStore()
    data_source = MemoryRDFDataSource()
    data_source.put(RELEASE_ID, release_dataset())
    builder = RDFProjectionBackend(store=other, data_source=data_source)
    other_projection = "projection:rdf-002"
    builder.build(
        projection_id=other_projection,
        release_id=RELEASE_ID,
        profile=profile(),
    )
    second = other.read_dataset(rdf_candidate_name(other_projection))

    assert first == second
    assert first is not None and second is not None
    assert first.triple_count() == second.triple_count()


def test_derive_matches_build() -> None:
    backend, store, data_source = make_backend()
    build_candidate(backend)
    derived = backend._builder.derive(RELEASE_ID, profile())
    projected = store.read_dataset(rdf_candidate_name(projection_id().canonical))
    assert projected == derived
    assert data_source is not None


# --- profile policy --------------------------------------------------------


def test_policy_documents_copy_and_transform() -> None:
    policy = policy_from_profile(
        profile(
            included_relations=("interacts_with",),
            included_entity_types=("gene",),
            transformations=(
                FieldTransformation(
                    name="remap",
                    source="interacts_with",
                    target="associates",
                    kind=TransformationKind.EDGE,
                ),
            ),
            dropped_semantics=("regulates", "urn:graph:validation"),
        )
    )
    assert isinstance(policy, RDFProjectionPolicy)
    assert policy.included_relations == ("interacts_with",)
    assert policy.included_entity_types == ("gene",)
    assert policy.transformed_predicates == (("interacts_with", "associates"),)
    assert policy.dropped_predicates == ("regulates",)
    assert policy.excluded_graphs == ("urn:graph:validation",)
    assert policy.transformed_map == {"interacts_with": "associates"}
    assert not policy.copies("urn:graph:validation")
    assert policy.copies("urn:graph:approved_assertion")


# --- filters ---------------------------------------------------------------


def test_included_relations_filter() -> None:
    backend, store, _ = make_backend()
    backend.build(
        projection_id=projection_id().canonical,
        release_id=RELEASE_ID,
        profile=profile(included_relations=("interacts_with",)),
    )
    assert approved_subjects(store) == nodes("a-1")
    # provenance is pruned to the surviving assertions (approved + source)
    assert provenance_subjects(store) == nodes("a-1", "a-9")


def test_included_entity_types_filter() -> None:
    backend, store, _ = make_backend()
    backend.build(
        projection_id=projection_id().canonical,
        release_id=RELEASE_ID,
        profile=profile(included_entity_types=("gene",)),
    )
    # a-1 dropped (protein object), a-2 kept (gene subject+object), at-1 kept
    assert approved_subjects(store) == nodes("a-2", "at-1")
    assert provenance_subjects(store) == nodes("a-2", "at-1", "a-9")


def test_included_assertion_types_filter() -> None:
    backend, store, _ = make_backend()
    backend.build(
        projection_id=projection_id().canonical,
        release_id=RELEASE_ID,
        profile=profile(included_assertion_types=(ASN_TYPE_RELATIONSHIP,)),
    )
    assert approved_subjects(store) == nodes("a-1", "a-2")


def test_dropped_predicate_filter() -> None:
    backend, store, _ = make_backend()
    backend.build(
        projection_id=projection_id().canonical,
        release_id=RELEASE_ID,
        profile=profile(dropped_semantics=("regulates",)),
    )
    assert approved_subjects(store) == nodes("a-1", "at-1")
    assert provenance_subjects(store) == nodes("a-1", "at-1", "a-9")


def test_dropped_graph_filter() -> None:
    backend, store, _ = make_backend()
    backend.build(
        projection_id=projection_id().canonical,
        release_id=RELEASE_ID,
        profile=profile(dropped_semantics=("urn:graph:validation", "urn:graph:source_assertion")),
    )
    projected = store.read_dataset(rdf_candidate_name(projection_id().canonical))
    assert projected is not None
    names = set(projected.graph_names())
    assert "urn:graph:validation" not in names
    assert "urn:graph:source_assertion" not in names
    # provenance of the dropped source assertion is pruned too
    assert provenance_subjects(store) == nodes("a-1", "a-2", "at-1")


# --- transformation --------------------------------------------------------


def test_predicate_transformation_remaps_assertions() -> None:
    backend, store, _ = make_backend()
    backend.build(
        projection_id=projection_id().canonical,
        release_id=RELEASE_ID,
        profile=profile(
            transformations=(
                FieldTransformation(
                    name="remap",
                    source="interacts_with",
                    target="associates",
                    kind=TransformationKind.EDGE,
                ),
            ),
        ),
    )
    projected = store.read_dataset(rdf_candidate_name(projection_id().canonical))
    assert projected is not None
    approved = projected.graph(graph_name(NamedGraphCategory.APPROVED_ASSERTION))
    assert approved is not None
    values = {
        term_value(triple.subject): term_value(triple.object)
        for triple in approved.triples
        if triple.predicate.value == ASN_PREDICATE
    }
    assert values[assertion_node("a-1")] == "associates"
    assert values[assertion_node("a-2")] == "regulates"


def test_transformation_is_detected_by_core_reconciliation() -> None:
    backend, _, _ = make_backend()
    backend.build(
        projection_id=projection_id().canonical,
        release_id=RELEASE_ID,
        profile=profile(
            transformations=(
                FieldTransformation(
                    name="remap",
                    source="interacts_with",
                    target="associates",
                    kind=TransformationKind.EDGE,
                ),
            ),
        ),
    )
    authoritative = ProjectionReconciler().authoritative_records(release_dataset())
    projected = backend.records(projection_id().canonical)
    report = ProjectionReconciler().compare(
        strategy=ReconciliationStrategy.REBUILD,
        authoritative_records=authoritative,
        projected_records=projected,
    )
    assert any(assertion_node("a-1") in entry for entry in report.transformed_records)
    # the unchanged assertion still matches exactly
    assert not any(assertion_node("a-2") in entry for entry in report.transformed_records)
    # a legitimate declared transformation still passes backend validation
    assert backend.validate(projection_id().canonical).passed


# --- unsupported semantics -------------------------------------------------


def test_unsupported_error_blocks_build() -> None:
    backend, _, _ = make_backend()
    with pytest.raises(RDFUnsupportedSemanticsError):
        backend.build(
            projection_id=projection_id().canonical,
            release_id=RELEASE_ID,
            profile=profile(
                unsupported_semantics=("regulates",),
                unsupported_behavior=UnsupportedBehavior.ERROR,
            ),
        )


def test_unsupported_skip_omits_assertions() -> None:
    backend, store, _ = make_backend()
    backend.build(
        projection_id=projection_id().canonical,
        release_id=RELEASE_ID,
        profile=profile(
            unsupported_semantics=("regulates",),
            unsupported_behavior=UnsupportedBehavior.SKIP,
        ),
    )
    assert approved_subjects(store) == nodes("a-1", "at-1")


def test_unsupported_flatten_copies_as_is() -> None:
    backend, store, _ = make_backend()
    backend.build(
        projection_id=projection_id().canonical,
        release_id=RELEASE_ID,
        profile=profile(
            unsupported_semantics=("regulates",),
            unsupported_behavior=UnsupportedBehavior.FLATTEN,
        ),
    )
    assert approved_subjects(store) == nodes("a-1", "a-2", "at-1")


# --- records ---------------------------------------------------------------


def test_records_match_authoritative_rdf() -> None:
    backend, _, _ = make_backend()
    build_candidate(backend)
    authoritative = ProjectionReconciler().authoritative_records(release_dataset())
    projected = backend.records(projection_id().canonical)
    assert {(r.kind, r.key): r.digest for r in projected} == {
        (r.kind, r.key): r.digest for r in authoritative
    }


def test_records_reflect_transformed_predicates() -> None:
    backend, _, _ = make_backend()
    backend.build(
        projection_id=projection_id().canonical,
        release_id=RELEASE_ID,
        profile=profile(
            transformations=(
                FieldTransformation(
                    name="remap",
                    source="interacts_with",
                    target="associates",
                    kind=TransformationKind.EDGE,
                ),
            ),
        ),
    )
    records = backend.records(projection_id().canonical)
    a1 = next(r for r in records if r.kind == "assertion" and r.key == assertion_node("a-1"))
    assert a1.digest == sha256(b"associates").hexdigest()


# --- validation / reconciliation / smoke -----------------------------------


def test_validate_passes_for_complete_candidate() -> None:
    backend, _, _ = make_backend()
    build_candidate(backend)
    result = backend.validate(projection_id().canonical)
    assert result.passed, result.errors
    assert result.errors == ()


def test_reconciliation_passes_for_complete_candidate() -> None:
    backend, _, _ = make_backend()
    build_candidate(backend)
    report = backend.reconcile(projection_id().canonical)
    assert report.reconciled
    assert report.missing_graphs == ()
    assert report.unexpected_graphs == ()
    assert report.missing_triples == ()
    assert report.unexpected_triples == ()


def _tamper(store: MemoryRDFProjectionStore, projection_value: str) -> None:
    store_key = rdf_candidate_name(f"projection:{projection_value}")
    dataset = store.read_dataset(store_key)
    assert dataset is not None
    graphs = []
    for graph in dataset.graphs:
        if graph.name == graph_name(NamedGraphCategory.APPROVED_ASSERTION):
            triples = tuple(
                triple
                for triple in graph.triples
                if not (
                    term_value(triple.subject) == assertion_node("a-2")
                    and triple.predicate.value == ASN_STATE
                )
            )
            graphs.append(NamedGraph(name=graph.name, triples=triples))
        else:
            graphs.append(graph)
    store.write_dataset(store_key, RDFDataset(graphs=tuple(graphs)))


def test_validate_fails_on_tampered_store() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    _tamper(store, PROJECTION_VALUE)
    result = backend.validate(projection_id().canonical)
    assert not result.passed
    assert any("reconciliation" in error for error in result.errors)


def test_reconcile_detects_tampering() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    _tamper(store, PROJECTION_VALUE)
    report = backend.reconcile(projection_id().canonical)
    assert not report.reconciled
    assert report.missing_triples != ()
    assert report.unexpected_triples == ()


def test_reconciliation_is_deterministic() -> None:
    backend, _, _ = make_backend()
    build_candidate(backend)
    first = backend.reconcile(projection_id().canonical)
    second = backend.reconcile(projection_id().canonical)
    assert first == second
    assert first.missing_triples == second.missing_triples


def test_smoke_tests_pass_for_complete_candidate() -> None:
    backend, _, _ = make_backend()
    build_candidate(backend)
    smoke = backend.smoke_test(projection_id().canonical)
    assert smoke.passed, smoke.errors
    assert smoke.metadata_readable
    assert smoke.identifier_resolution
    assert smoke.assertion_access
    assert smoke.provenance_access


def test_smoke_tests_fail_on_missing_metadata() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    store_key = rdf_candidate_name(projection_id().canonical)
    dataset = store.read_dataset(store_key)
    assert dataset is not None
    store.write_dataset(
        store_key,
        RDFDataset(
            graphs=tuple(
                graph
                for graph in dataset.graphs
                if graph.name != graph_name(NamedGraphCategory.RELEASE_METADATA)
            )
        ),
    )
    smoke = backend.smoke_test(projection_id().canonical)
    assert not smoke.passed
    assert not smoke.metadata_readable
    assert "release metadata is not readable" in smoke.errors


def test_reconciler_and_smoke_runner_are_standalone() -> None:
    store = MemoryRDFProjectionStore()
    data_source = MemoryRDFDataSource()
    data_source.put(RELEASE_ID, release_dataset())
    builder = RDFProjectionBuilder(store=store, data_source=data_source)
    builder.build(
        projection_id=projection_id().canonical,
        release_id=RELEASE_ID,
        profile=profile(),
    )
    reconciler = RDFReconciler(store=store, data_source=data_source)
    report = reconciler.reconcile(
        projection_id=projection_id().canonical,
        release_id=RELEASE_ID,
        profile=profile(),
    )
    assert isinstance(report, RDFReconciliationReport)
    assert report.reconciled

    expected = RDFProjectionBuilder(store=store, data_source=data_source).expected(
        RELEASE_ID, profile()
    )
    smoke = RDFSmokeTestRunner(store=store).run(
        projection_id=projection_id().canonical,
        expected=expected,
    )
    assert smoke.passed


# --- atomic switch and rollback --------------------------------------------


def test_activation_is_atomic_and_retains_previous() -> None:
    backend, store, _ = make_backend()
    first = "projection:rdf-001"
    second = "projection:rdf-002"
    backend.build(projection_id=first, release_id=RELEASE_ID, profile=profile())
    assert backend.validate(first).passed
    backend.activate(first)
    first_key = rdf_candidate_name(first)
    assert store.active_projection() == first_key

    backend.build(projection_id=second, release_id=RELEASE_ID, profile=profile())
    assert backend.validate(second).passed
    backend.activate(second)
    second_key = rdf_candidate_name(second)
    assert store.active_projection() == second_key
    assert store.has_projection(first_key)


def test_rollback_restores_previous_without_rebuild() -> None:
    backend, store, _ = make_backend()
    first = "projection:rdf-001"
    second = "projection:rdf-002"
    backend.build(projection_id=first, release_id=RELEASE_ID, profile=profile())
    backend.activate(first)
    backend.build(projection_id=second, release_id=RELEASE_ID, profile=profile())
    backend.activate(second)

    backend.rollback(second)
    assert store.active_projection() is None
    assert store.has_projection(rdf_candidate_name(first))

    backend.activate(first)
    assert store.active_projection() == rdf_candidate_name(first)


def test_destroy_removes_content() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    store_key = rdf_candidate_name(projection_id().canonical)
    assert store.has_projection(store_key)
    backend.destroy(projection_id().canonical)
    assert not store.has_projection(store_key)
    assert store.triple_count(store_key) == 0


def test_unknown_projection_raises() -> None:
    backend, _, _ = make_backend()
    with pytest.raises(UnknownRDFProjectionError):
        backend.validate("projection:ghost")


# --- Core integration ------------------------------------------------------


def test_registered_through_projection_registry() -> None:
    backend, _, _ = make_backend()
    registry = ProjectionRegistry()
    registry.register(backend)
    assert registry.has("rdf")
    assert registry.get("rdf") is backend
    assert isinstance(backend, ProjectionBackend)


def test_core_drives_rdf_lifecycle_independently() -> None:
    backend, _, data_source = make_backend()
    registry = ProjectionRegistry()
    registry.register(backend)
    manager = ProjectionManager(registry=registry)

    projection = manager.create_projection(
        projection_id=projection_id(),
        profile=profile(),
        backend_id="rdf",
        release_id=RELEASE_ID,
    )
    assert projection.status is ProjectionStatus.BUILDING

    projection = manager.build_candidate(projection.id)
    assert projection.status is ProjectionStatus.VALIDATING

    projection = manager.validate_candidate(projection.id)
    assert projection.status is ProjectionStatus.RECONCILING
    assert projection.validation_result is not None
    assert projection.validation_result.passed

    release_dataset_for_compare = data_source.get(RELEASE_ID)
    assert release_dataset_for_compare is not None
    projection = manager.reconcile_candidate(projection.id, release_dataset_for_compare)
    assert projection.status is ProjectionStatus.READY
    assert projection.reconciliation_result is not None
    assert projection.reconciliation_result.reconciled

    projection = manager.activate_candidate(projection.id)
    assert projection.status is ProjectionStatus.ACTIVE
    active = manager.active_projection()
    assert active is not None
    assert active.id == projection.id


def test_core_rollback_switches_back_to_retained_rdf() -> None:
    backend, _, data_source = make_backend()
    registry = ProjectionRegistry()
    registry.register(backend)
    manager = ProjectionManager(registry=registry)

    def activate(value: str) -> Identifier:
        p = manager.create_projection(
            projection_id=ident("projection", value),
            profile=profile(),
            backend_id="rdf",
            release_id=RELEASE_ID,
        )
        p = manager.build_candidate(p.id)
        p = manager.validate_candidate(p.id)
        release_dataset_for_compare = data_source.get(RELEASE_ID)
        assert release_dataset_for_compare is not None
        p = manager.reconcile_candidate(p.id, release_dataset_for_compare)
        return manager.activate_candidate(p.id).id

    first = activate("rdf-101")
    second = activate("rdf-102")

    restored = manager.rollback(second)
    assert restored.id == first
    assert restored.status is ProjectionStatus.ACTIVE
    active = manager.active_projection()
    assert active is not None
    assert active.id == first


def test_failed_candidate_is_never_activated() -> None:
    backend, store, _ = make_backend()
    registry = ProjectionRegistry()
    registry.register(backend)
    manager = ProjectionManager(registry=registry)
    projection = manager.create_projection(
        projection_id=projection_id(),
        profile=profile(),
        backend_id="rdf",
        release_id=RELEASE_ID,
    )
    projection = manager.build_candidate(projection.id)
    assert projection.status is ProjectionStatus.VALIDATING

    # Corrupt the candidate before validation: drop the approved graph.
    store_key = rdf_candidate_name(projection.id.canonical)
    dataset = store.read_dataset(store_key)
    assert dataset is not None
    store.write_dataset(
        store_key,
        RDFDataset(
            graphs=tuple(
                graph
                for graph in dataset.graphs
                if graph.name != graph_name(NamedGraphCategory.APPROVED_ASSERTION)
            )
        ),
    )
    projection = manager.validate_candidate(projection.id)
    assert projection.status is ProjectionStatus.FAILED
    with pytest.raises(InvalidProjectionTransitionError):
        manager.activate_candidate(projection.id)
