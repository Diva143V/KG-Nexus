"""Phase 14: Neo4j Projection Backend tests.

Exercises the first concrete ``ProjectionBackend`` end to end: build a
candidate from the authoritative RDF release, validate it, reconcile it,
run smoke tests, activate it atomically, and roll it back — while Core
remains Neo4j-independent throughout.
"""

from __future__ import annotations

import pytest

from core.identifiers.identifier import Identifier
from core.projection import (
    ProjectionBackend,
    ProjectionManager,
    ProjectionProfile,
    ProjectionReconciler,
    ProjectionRegistry,
    ProjectionStatus,
    ReconciliationStrategy,
)
from core.projection.errors import InvalidProjectionTransitionError
from core.rdf.graph import NamedGraph, RDFDataset
from core.rdf.terms import Triple, iri, string_literal
from infrastructure.projections.neo4j import (
    MemoryNeo4jClient,
    MemoryRDFDataSource,
    Neo4jProjectionBackend,
    Neo4jProjectionBuilder,
    Neo4jReconciler,
    Neo4jReconciliationReport,
    Neo4jSmokeTestRunner,
    neo4j_candidate_name,
)
from infrastructure.projections.neo4j.errors import (
    MissingRDFReleaseError,
    Neo4jProjectionError,
    UnknownNeo4jProjectionError,
)
from infrastructure.projections.neo4j.schema import (
    PROP_ID,
    PROP_PREDICATE,
    Neo4jNode,
    Neo4jRelationship,
)
from tests.helpers import ident

RELEASE_ID = "release:r1"
PROJECTION_VALUE = "neo4j-2026-001"

ASN_SUBJECT = "urn:assertion:subject"
ASN_PREDICATE = "urn:assertion:predicate"
ASN_OBJECT = "urn:assertion:object"
ASN_VALUE = "urn:assertion:value"
ASN_STATE = "urn:assertion:state"
PROV_AGENT = "urn:prov:agent"
PROV_ACTIVITY = "urn:prov:activity"
PROV_ASSERTED_AT = "urn:prov:asserted_at"

P_INTERACTS = "urn:predicate:interacts_with"
P_EXPRESSES = "urn:predicate:expresses"
P_EXPRESSED_IN = "urn:predicate:expressed_in"

ID_EGFR = "urn:identifier:gene:EGFR"
ID_P53 = "urn:identifier:protein:P53"
ID_MYC = "urn:identifier:gene:MYC"


def dataset() -> RDFDataset:
    return RDFDataset(
        graphs=(
            NamedGraph(
                name="urn:graph:approved_assertion",
                triples=(
                    *_relationship("urn:assertion:a1", ID_EGFR, P_INTERACTS, ID_P53),
                    *_relationship("urn:assertion:a2", ID_P53, P_EXPRESSES, ID_MYC),
                    *_attribute("urn:assertion:a3", ID_EGFR, P_EXPRESSED_IN, "lung"),
                ),
            ),
            NamedGraph(
                name="urn:graph:provenance",
                triples=(
                    *_provenance("urn:assertion:a1", "agent:curator-1", "activity:act-1"),
                    *_provenance("urn:assertion:a2", "agent:curator-1", "activity:act-1"),
                ),
            ),
        )
    )


def _relationship(assertion_id: str, subject: str, predicate: str, obj: str) -> tuple[Triple, ...]:
    node = iri(assertion_id)
    return (
        Triple(subject=node, predicate=iri(ASN_SUBJECT), object=iri(subject)),
        Triple(subject=node, predicate=iri(ASN_PREDICATE), object=string_literal(predicate)),
        Triple(subject=node, predicate=iri(ASN_OBJECT), object=iri(obj)),
        Triple(subject=node, predicate=iri(ASN_STATE), object=string_literal("approved")),
    )


def _attribute(assertion_id: str, subject: str, predicate: str, value: str) -> tuple[Triple, ...]:
    node = iri(assertion_id)
    return (
        Triple(subject=node, predicate=iri(ASN_SUBJECT), object=iri(subject)),
        Triple(subject=node, predicate=iri(ASN_PREDICATE), object=string_literal(predicate)),
        Triple(subject=node, predicate=iri(ASN_VALUE), object=string_literal(value)),
        Triple(subject=node, predicate=iri(ASN_STATE), object=string_literal("approved")),
    )


def _provenance(assertion_id: str, agent: str, activity: str) -> tuple[Triple, ...]:
    node = iri(assertion_id)
    return (
        Triple(subject=node, predicate=iri(PROV_AGENT), object=iri(f"urn:identifier:{agent}")),
        Triple(
            subject=node,
            predicate=iri(PROV_ACTIVITY),
            object=iri(f"urn:identifier:{activity}"),
        ),
        Triple(
            subject=node,
            predicate=iri(PROV_ASSERTED_AT),
            object=iri("urn:identifier:2026-01-01T00:00:00+00:00"),
        ),
    )


def profile(
    *,
    included_relations: tuple[str, ...] = (),
    included_entity_types: tuple[str, ...] = (),
) -> ProjectionProfile:
    return ProjectionProfile(
        profile_id="neo4j-entity-graph",
        profile_version="1",
        source_release_type="approved",
        preserved_fields=("urn:label",),
        included_relations=included_relations,
        included_entity_types=included_entity_types,
        reconciliation_strategy=ReconciliationStrategy.REBUILD,
    )


def make_backend() -> tuple[Neo4jProjectionBackend, MemoryNeo4jClient, MemoryRDFDataSource]:
    client = MemoryNeo4jClient()
    data_source = MemoryRDFDataSource()
    data_source.put(RELEASE_ID, dataset())
    backend = Neo4jProjectionBackend(client=client, data_source=data_source)
    return backend, client, data_source


def projection_id() -> Identifier:
    return ident("projection", PROJECTION_VALUE)


def build_candidate(backend: Neo4jProjectionBackend) -> None:
    backend.build(
        projection_id=projection_id().canonical,
        release_id=RELEASE_ID,
        profile=profile(),
    )


def build_validated(backend: Neo4jProjectionBackend) -> None:
    build_candidate(backend)
    result = backend.validate(projection_id().canonical)
    assert result.passed, result.errors


# --- schema mapping --------------------------------------------------------


def test_identifier_mapping_round_trips() -> None:
    from infrastructure.projections.neo4j.schema import (
        assertion_id_from_iri,
        assertion_iri,
        identifier_from_iri,
        identifier_iri,
    )

    assert identifier_from_iri(identifier_iri("gene:EGFR")) == "gene:EGFR"
    assert assertion_id_from_iri(assertion_iri("a1")) == "a1"


def test_candidate_name_is_scoped() -> None:
    assert neo4j_candidate_name("projection:p1") == "neo4j_projection:p1_candidate"


def test_relationship_type_is_readable() -> None:
    from infrastructure.projections.neo4j.schema import predicate_type

    assert predicate_type(P_INTERACTS) == "interacts_with"


# --- builder ---------------------------------------------------------------


def test_build_materializes_expected_content() -> None:
    backend, client, _ = make_backend()
    result = backend.build(
        projection_id=projection_id().canonical,
        release_id=RELEASE_ID,
        profile=profile(),
    )
    store_key = neo4j_candidate_name(projection_id().canonical)

    assert result.record_count == 5  # 3 entities + 2 relationships
    assert client.node_count(store_key) == 3
    assert client.relationship_count(store_key) == 2

    nodes = {node.id: node for node in client.all_nodes(store_key)}
    assert set(nodes) == {"gene:EGFR", "protein:P53", "gene:MYC"}
    assert nodes["gene:EGFR"].properties[PROP_ID] == "gene:EGFR"

    rels = {rel.id: rel for rel in client.all_relationships(store_key)}
    assert set(rels) == {"a1", "a2"}
    assert rels["a1"].type == "interacts_with"
    assert rels["a1"].start_node_id == "gene:EGFR"
    assert rels["a1"].end_node_id == "protein:P53"
    assert rels["a1"].properties["agent_id"] == "agent:curator-1"
    assert rels["a1"].properties["asserted_at"] == "urn:identifier:2026-01-01T00:00:00+00:00"

    assert nodes["gene:EGFR"].properties["attr_value_urn_predicate_expressed_in"] == "lung"


def test_build_never_touches_active_projection() -> None:
    backend, client, _ = make_backend()
    build_candidate(backend)
    backend.activate(projection_id().canonical)
    store_key = neo4j_candidate_name(projection_id().canonical)

    # A second projection builds alongside the active one without touching it.
    backend.build(
        projection_id="projection:neo4j-2026-002",
        release_id=RELEASE_ID,
        profile=profile(),
    )
    assert client.node_count(store_key) == 3
    assert client.active_projection() == store_key


def test_build_requires_rdf_release() -> None:
    client = MemoryNeo4jClient()
    backend = Neo4jProjectionBackend(
        client=client,
        data_source=MemoryRDFDataSource(),
    )
    with pytest.raises(MissingRDFReleaseError):
        backend.build(
            projection_id=projection_id().canonical,
            release_id="release:missing",
            profile=profile(),
        )


def test_build_rejects_duplicate_candidate() -> None:
    backend, _, _ = make_backend()
    build_candidate(backend)
    with pytest.raises(Neo4jProjectionError):
        backend.build(
            projection_id=projection_id().canonical,
            release_id=RELEASE_ID,
            profile=profile(),
        )


def test_profile_filters_relations_and_entity_types() -> None:
    backend, client, _ = make_backend()
    backend.build(
        projection_id="projection:neo4j-2026-001",
        release_id=RELEASE_ID,
        profile=profile(included_relations=(P_INTERACTS,)),
    )
    store_key = neo4j_candidate_name("projection:neo4j-2026-001")
    assert [rel.id for rel in client.all_relationships(store_key)] == ["a1"]
    assert client.node_count(store_key) == 3

    backend, client, _ = make_backend()
    backend.build(
        projection_id="projection:neo4j-2026-002",
        release_id=RELEASE_ID,
        profile=profile(included_entity_types=("gene",)),
    )
    store_key = neo4j_candidate_name("projection:neo4j-2026-002")
    nodes = {node.id: node for node in client.all_nodes(store_key)}
    assert set(nodes) == {"gene:EGFR", "gene:MYC"}
    assert client.relationship_count(store_key) == 0
    assert nodes["gene:EGFR"].properties["attr_value_urn_predicate_expressed_in"] == "lung"


# --- validation ------------------------------------------------------------


def test_validation_passes_for_complete_candidate() -> None:
    backend, _, _ = make_backend()
    build_candidate(backend)
    result = backend.validate(projection_id().canonical)
    assert result.passed, result.errors
    assert result.errors == ()


def test_validation_fails_on_missing_entity() -> None:
    backend, client, _ = make_backend()
    build_candidate(backend)
    store_key = neo4j_candidate_name(projection_id().canonical)
    client.delete_projection(store_key)
    client.create_node(
        store_key,
        Neo4jNode(id="gene:EGFR", labels=("Entity",), properties={PROP_ID: "gene:EGFR"}),
    )
    result = backend.validate(projection_id().canonical)
    assert not result.passed
    assert any("required identifiers missing" in error for error in result.errors)


def test_validation_fails_on_required_provenance_gap() -> None:
    backend, client, _ = make_backend()
    build_candidate(backend)
    store_key = neo4j_candidate_name(projection_id().canonical)
    rel = client.get_relationship(store_key, "a1")
    assert rel is not None
    client._relationships[store_key]["a1"] = rel.model_copy(
        update={"properties": dict(rel.properties) | {"agent_id": "wrong"}}
    )
    result = backend.validate(projection_id().canonical)
    assert not result.passed


# --- reconciliation --------------------------------------------------------


def test_reconciliation_passes_for_complete_candidate() -> None:
    backend, _, _ = make_backend()
    build_candidate(backend)
    report = backend.reconcile(projection_id().canonical)
    assert report.reconciled
    assert report.missing_entities == ()
    assert report.unexpected_entities == ()
    assert report.missing_relations == ()
    assert report.assertion_mismatches == ()


def test_reconciliation_detects_missing_entities() -> None:
    backend, client, _ = make_backend()
    build_candidate(backend)
    store_key = neo4j_candidate_name(projection_id().canonical)
    client.delete_projection(store_key)
    client.create_node(
        store_key,
        Neo4jNode(id="gene:EGFR", labels=("Entity",), properties={PROP_ID: "gene:EGFR"}),
    )
    report = backend.reconcile(projection_id().canonical)
    assert not report.reconciled
    assert "gene:MYC" in report.missing_entities
    assert "protein:P53" in report.missing_entities


def test_reconciliation_detects_unexpected_entities() -> None:
    backend, client, _ = make_backend()
    build_candidate(backend)
    store_key = neo4j_candidate_name(projection_id().canonical)
    client.create_node(
        store_key,
        Neo4jNode(id="drug:X", labels=("Entity",), properties={PROP_ID: "drug:X"}),
    )
    report = backend.reconcile(projection_id().canonical)
    assert not report.reconciled
    assert report.unexpected_entities == ("drug:X",)


def test_reconciliation_detects_missing_and_unexpected_relations() -> None:
    backend, client, _ = make_backend()
    build_candidate(backend)
    store_key = neo4j_candidate_name(projection_id().canonical)
    client._relationships[store_key].pop("a1")
    client.create_relationship(
        store_key,
        Neo4jRelationship(
            id="x9",
            type="ghost",
            start_node_id="gene:EGFR",
            end_node_id="gene:MYC",
            properties={"predicate": P_INTERACTS},
        ),
    )
    report = backend.reconcile(projection_id().canonical)
    assert "a1" in report.missing_relations
    assert report.unexpected_relations == ("x9",)


def test_reconciliation_detects_assertion_mismatch() -> None:
    backend, client, _ = make_backend()
    build_candidate(backend)
    store_key = neo4j_candidate_name(projection_id().canonical)
    rel = client.get_relationship(store_key, "a2")
    assert rel is not None
    client._relationships[store_key]["a2"] = rel.model_copy(
        update={"properties": dict(rel.properties) | {PROP_PREDICATE: P_INTERACTS}}
    )
    report = backend.reconcile(projection_id().canonical)
    assert not report.reconciled
    assert report.assertion_mismatches == ("a2",)


# --- smoke tests -----------------------------------------------------------


def test_smoke_tests_pass_for_complete_candidate() -> None:
    backend, _, _ = make_backend()
    build_candidate(backend)
    smoke = backend.smoke_test(projection_id().canonical)
    assert smoke.passed, smoke.errors
    assert smoke.entity_retrieval
    assert smoke.relation_traversal
    assert smoke.identifier_resolution
    assert smoke.provenance_access


def test_smoke_tests_fail_on_dangling_relation() -> None:
    backend, client, _ = make_backend()
    build_candidate(backend)
    store_key = neo4j_candidate_name(projection_id().canonical)
    client._nodes[store_key].pop("gene:MYC")
    smoke = backend.smoke_test(projection_id().canonical)
    assert not smoke.passed
    assert "gene:MYC" in smoke.errors[0]


# --- backend records (Core reconciliation format) --------------------------


def test_records_match_authoritative_rdf() -> None:
    backend, _, _ = make_backend()
    build_candidate(backend)
    authoritative = ProjectionReconciler().authoritative_records(dataset())
    projected = backend.records(projection_id().canonical)

    authoritative_by_key = {(r.kind, r.key): r.digest for r in authoritative}
    projected_by_key = {(r.kind, r.key): r.digest for r in projected}
    assert set(projected_by_key) == set(authoritative_by_key)
    assert projected_by_key == authoritative_by_key


# --- atomic switch and rollback --------------------------------------------


def test_activation_is_atomic_and_retains_previous() -> None:
    backend, client, _ = make_backend()
    first = "projection:neo4j-001"
    second = "projection:neo4j-002"
    backend.build(projection_id=first, release_id=RELEASE_ID, profile=profile())
    assert backend.validate(first).passed
    backend.activate(first)
    first_key = neo4j_candidate_name(first)
    assert client.active_projection() == first_key

    backend.build(projection_id=second, release_id=RELEASE_ID, profile=profile())
    assert backend.validate(second).passed
    backend.activate(second)
    second_key = neo4j_candidate_name(second)
    assert client.active_projection() == second_key
    # previous active content is retained, not deleted
    assert client.node_count(first_key) == 3


def test_rollback_restores_previous_without_rebuild() -> None:
    backend, client, _ = make_backend()
    first = "projection:neo4j-001"
    second = "projection:neo4j-002"
    backend.build(projection_id=first, release_id=RELEASE_ID, profile=profile())
    backend.activate(first)
    backend.build(projection_id=second, release_id=RELEASE_ID, profile=profile())
    backend.activate(second)

    backend.rollback(second)
    first_key = neo4j_candidate_name(first)
    assert client.active_projection() is None
    assert client.node_count(first_key) == 3

    # restoring the retained projection needs no rebuild
    backend.activate(first)
    assert client.active_projection() == first_key


def test_destroy_removes_content() -> None:
    backend, client, _ = make_backend()
    build_candidate(backend)
    store_key = neo4j_candidate_name(projection_id().canonical)
    assert client.node_count(store_key) == 3
    backend.destroy(projection_id().canonical)
    assert client.node_count(store_key) == 0


def test_unknown_projection_raises() -> None:
    backend, _, _ = make_backend()
    with pytest.raises(UnknownNeo4jProjectionError):
        backend.validate("projection:ghost")


# --- Core integration ------------------------------------------------------


def test_registered_through_projection_registry() -> None:
    backend, _, _ = make_backend()
    registry = ProjectionRegistry()
    registry.register(backend)
    assert registry.has("neo4j")
    assert registry.get("neo4j") is backend
    assert isinstance(backend, ProjectionBackend)


def test_core_drives_neo4j_lifecycle_independently() -> None:
    backend, _, data_source = make_backend()
    registry = ProjectionRegistry()
    registry.register(backend)
    manager = ProjectionManager(registry=registry)

    projection = manager.create_projection(
        projection_id=projection_id(),
        profile=profile(),
        backend_id="neo4j",
        release_id=RELEASE_ID,
    )
    assert projection.status is ProjectionStatus.BUILDING

    projection = manager.build_candidate(projection.id)
    assert projection.status is ProjectionStatus.VALIDATING
    assert projection.build_result is not None
    assert projection.build_result.record_count == 5

    projection = manager.validate_candidate(projection.id)
    assert projection.status is ProjectionStatus.RECONCILING
    assert projection.validation_result is not None
    assert projection.validation_result.passed

    release_dataset = data_source.get(RELEASE_ID)
    assert release_dataset is not None
    projection = manager.reconcile_candidate(projection.id, release_dataset)
    assert projection.status is ProjectionStatus.READY
    assert projection.reconciliation_result is not None
    assert projection.reconciliation_result.reconciled

    projection = manager.activate_candidate(projection.id)
    assert projection.status is ProjectionStatus.ACTIVE
    active = manager.active_projection()
    assert active is not None
    assert active.id == projection.id


def test_core_rollback_switches_back_to_retained_neo4j() -> None:
    backend, _, data_source = make_backend()
    registry = ProjectionRegistry()
    registry.register(backend)
    manager = ProjectionManager(registry=registry)

    def activate(value: str) -> Identifier:
        p = manager.create_projection(
            projection_id=ident("projection", value),
            profile=profile(),
            backend_id="neo4j",
            release_id=RELEASE_ID,
        )
        p = manager.build_candidate(p.id)
        p = manager.validate_candidate(p.id)
        release_dataset = data_source.get(RELEASE_ID)
        assert release_dataset is not None
        p = manager.reconcile_candidate(p.id, release_dataset)
        return manager.activate_candidate(p.id).id

    first = activate("neo4j-101")
    second = activate("neo4j-102")

    restored = manager.rollback(second)
    assert restored.id == first
    assert restored.status is ProjectionStatus.ACTIVE
    active = manager.active_projection()
    assert active is not None
    assert active.id == first


def test_failed_candidate_is_never_activated() -> None:
    backend, _, _ = make_backend()
    registry = ProjectionRegistry()
    registry.register(backend)
    manager = ProjectionManager(registry=registry)
    projection = manager.create_projection(
        projection_id=projection_id(),
        profile=profile(),
        backend_id="neo4j",
        release_id=RELEASE_ID,
    )
    projection = manager.build_candidate(projection.id)
    assert projection.status is ProjectionStatus.VALIDATING

    # Simulate a failed deployment by corrupting the candidate before validation.
    store_key = neo4j_candidate_name(projection.id.canonical)
    backend._client.delete_projection(store_key)
    projection = manager.validate_candidate(projection.id)
    assert projection.status is ProjectionStatus.FAILED
    with pytest.raises(InvalidProjectionTransitionError):
        manager.activate_candidate(projection.id)


# --- reconciler module -----------------------------------------------------


def test_reconciler_is_standalone() -> None:
    client = MemoryNeo4jClient()
    data_source = MemoryRDFDataSource()
    data_source.put(RELEASE_ID, dataset())
    builder = Neo4jProjectionBuilder(client=client, data_source=data_source)
    builder.build(
        projection_id=projection_id().canonical,
        release_id=RELEASE_ID,
        profile=profile(),
    )
    reconciler = Neo4jReconciler(client=client, data_source=data_source)
    report = reconciler.reconcile(
        projection_id=projection_id().canonical,
        release_id=RELEASE_ID,
        profile=profile(),
    )
    assert isinstance(report, Neo4jReconciliationReport)
    assert report.reconciled


def test_smoke_runner_is_standalone() -> None:
    client = MemoryNeo4jClient()
    data_source = MemoryRDFDataSource()
    data_source.put(RELEASE_ID, dataset())
    builder = Neo4jProjectionBuilder(client=client, data_source=data_source)
    expected = builder.derive(RELEASE_ID, profile())
    builder.build(
        projection_id=projection_id().canonical,
        release_id=RELEASE_ID,
        profile=profile(),
    )
    smoke = Neo4jSmokeTestRunner(client=client).run(
        projection_id=projection_id().canonical,
        expected=expected,
    )
    assert smoke.passed
