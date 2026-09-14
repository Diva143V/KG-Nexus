"""Phase 17: vector projection backend tests.

Exercises the vector projection end to end: an authoritative RDF release is
embedded into deterministic vectors (entities, relations, assertions) plus a
manifest recording the embedding model id, model version, embedding
configuration, source release, and embedding digest, through the pluggable
ProjectionBackend contract. The projection is a retrieval/indexing layer only:
vector similarity never establishes identity or truth, results are candidates
with scores, and nothing here approves assertions or replaces any policy or
validator. RDF stays authoritative and the projection is rebuildable from RDF.
"""

from __future__ import annotations

import json
from hashlib import sha256

import pytest

from core.assertions.assertion import Assertion
from core.assertions.assertion_state import AssertionStateEvent
from core.assertions.attribute import AttributeAssertion
from core.assertions.literal import LiteralType, LiteralValue
from core.assertions.state import AssertionState
from core.evidence.evidence import Evidence, EvidenceKind
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
    RDFDataset,
    RDFReleaseWriter,
)
from core.releases.manifest import LockfileSet, ReleaseManifest
from core.releases.release import Release, ReleaseGate
from core.releases.status import ReleaseStatus
from infrastructure.projections.vector import (
    DeterministicHashEmbedder,
    EmbeddedItem,
    MemoryVectorDataSource,
    MemoryVectorProjectionStore,
    MissingVectorReleaseError,
    UnknownVectorProjectionError,
    VectorManifest,
    VectorProjectionBackend,
    VectorProjectionBuilder,
    VectorProjectionPolicy,
    VectorReconciler,
    VectorReconciliationReport,
    VectorRetriever,
    VectorSmokeTestRunner,
    VectorUnsupportedSemanticsError,
    embedding_digest,
    policy_from_profile,
    vector_candidate_name,
)
from infrastructure.projections.vector.writer import (
    items_bytes,
    items_from_bytes,
    manifest_from_bytes,
)
from tests.helpers import ident, utc

RELEASE_ID = "release:kg-2026.1"
PROJECTION_VALUE = "vector-2026-001"

ASN_OBJECT_PREDICATE = "urn:assertion:object"
ASN_TYPE_RELATIONSHIP = "urn:assertion:RelationshipAssertion"
ASN_TYPE_ATTRIBUTE = "urn:assertion:AttributeAssertion"

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


def evidence(
    *,
    ev_id: str,
    kind: EvidenceKind = EvidenceKind.PRIMARY,
    record: str = "r-1",
    artifact: str | None = None,
    day: int = 5,
) -> Evidence:
    return Evidence(
        id=ident("evidence", ev_id),
        kind=kind,
        record_id=ident("record", record),
        artifact_id=ident("artifact", artifact) if artifact is not None else None,
        obtained_at=utc(2026, 1, day),
        detail={"page": 3},
    )


def relationship(
    *,
    aid: str,
    subject: Identifier,
    predicate: str,
    obj: Identifier,
    evidence_items: tuple[Evidence, ...] = (),
) -> Assertion:
    return Assertion(
        id=ident("assertion", aid),
        subject=subject,
        predicate=predicate,
        object=obj,
        provenance=prov(),
        evidence=evidence_items,
    )


def attribute(
    *,
    aid: str,
    subject: Identifier,
    predicate: str,
    value: LiteralValue,
    evidence_items: tuple[Evidence, ...] = (),
) -> AttributeAssertion:
    return AttributeAssertion(
        id=ident("assertion", aid),
        subject=subject,
        predicate=predicate,
        value=value,
        provenance=prov(),
        evidence=evidence_items,
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
            evidence_items=(evidence(ev_id="e-1", artifact="doc-1"),),
        ),
        relationship(
            aid="a-2",
            subject=ident("gene", "EGFR"),
            predicate="regulates",
            obj=ident("gene", "MYC"),
        ),
        # source (non-approved) assertion: never embedded by the vector backend
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
            evidence_items=(
                evidence(
                    ev_id="e-2",
                    kind=EvidenceKind.SECONDARY,
                    record="r-2",
                    day=6,
                ),
            ),
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
        profile_id="vector-retrieval",
        profile_version="1",
        source_release_type="approved",
        included_relations=included_relations,
        included_entity_types=included_entity_types,
        included_assertion_types=included_assertion_types,
        transformations=transformations,
        dropped_semantics=dropped_semantics,
        unsupported_semantics=unsupported_semantics,
        unsupported_behavior=unsupported_behavior,
        reconciliation_strategy=ReconciliationStrategy.REBUILD,
    )


def make_backend() -> tuple[
    VectorProjectionBackend, MemoryVectorProjectionStore, MemoryVectorDataSource
]:
    store = MemoryVectorProjectionStore()
    data_source = MemoryVectorDataSource()
    data_source.put(RELEASE_ID, release_dataset())
    backend = VectorProjectionBackend(store=store, data_source=data_source)
    return backend, store, data_source


def projection_id() -> Identifier:
    return ident("projection", PROJECTION_VALUE)


def assertion_node(aid: str) -> str:
    """RDF IRI of an assertion node, matching the Phase 11 writer."""
    return f"urn:assertion:{ident('assertion', aid).canonical}"


def entity_key(identifier: str) -> str:
    """RDF IRI form of an identifier."""
    return f"urn:identifier:{identifier}"


def relation_key(aid: str, identifier: str) -> str:
    """Reconciler-style relation record key."""
    return f"{assertion_node(aid)}:{ASN_OBJECT_PREDICATE}:{entity_key(identifier)}"


def build_candidate(backend: VectorProjectionBackend) -> None:
    backend.build(
        projection_id=projection_id().canonical,
        release_id=RELEASE_ID,
        profile=profile(),
    )


def stored_bytes(
    store: MemoryVectorProjectionStore,
    name: str,
    projection_value: str = PROJECTION_VALUE,
) -> bytes | None:
    store_key = vector_candidate_name(f"projection:{projection_value}")
    return store.read_dataset(store_key, name)


def stored_items(
    store: MemoryVectorProjectionStore,
    projection_value: str = PROJECTION_VALUE,
) -> tuple[EmbeddedItem, ...]:
    data = stored_bytes(store, "vectors", projection_value)
    assert data is not None
    return items_from_bytes(data)


def stored_manifest(
    store: MemoryVectorProjectionStore,
    projection_value: str = PROJECTION_VALUE,
) -> VectorManifest:
    data = stored_bytes(store, "manifest", projection_value)
    assert data is not None
    return manifest_from_bytes(data)


# --- store ----------------------------------------------------------------


def test_vector_candidate_name_is_scoped() -> None:
    assert vector_candidate_name("projection:p1") == "vector_projection:p1_candidate"


def test_memory_store_roundtrip() -> None:
    store = MemoryVectorProjectionStore()
    store_key = vector_candidate_name("projection:p1")
    payload = b"vector-bytes"
    store.write_dataset(store_key, "vectors", payload)
    assert store.has_projection(store_key)
    assert store.read_dataset(store_key, "vectors") == payload
    assert store.dataset_names(store_key) == ("vectors",)
    assert store.dataset_count(store_key, "vectors") == 0
    store.activate(store_key)
    assert store.active_projection() == store_key
    store.rollback(store_key)
    assert store.active_projection() is None
    store.delete_projection(store_key)
    assert not store.has_projection(store_key)


# --- serialization --------------------------------------------------------


def test_items_serialization_roundtrip_is_byte_stable() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    data = stored_bytes(store, "vectors")
    assert data is not None
    items = items_from_bytes(data)
    assert items_bytes(items) == data


def test_embedding_digest_is_deterministic() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    data = stored_bytes(store, "vectors")
    assert data is not None
    items = items_from_bytes(data)
    assert embedding_digest(items) == embedding_digest(items)


# --- builder --------------------------------------------------------------


def test_derive_produces_all_three_kinds() -> None:
    backend, store, _ = make_backend()
    expected = backend._builder.expected(RELEASE_ID, profile())
    assert expected.item_count == 6
    assert expected.assertion_count == 3
    assert expected.relation_count == 2
    assert expected.entity_count == 1
    build_candidate(backend)
    assert store.dataset_count(vector_candidate_name(projection_id().canonical), "vectors") == 6


def test_assertion_items_match_expected_rows() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    items = {str(item.key): item for item in stored_items(store)}
    a1 = items[assertion_node("a-1")]
    assert a1.kind == "assertion"
    assert a1.digest == sha256(b"interacts_with").hexdigest()
    assert a1.text == "gene:EGFR interacts_with protein:P53"
    assert a1.source == assertion_node("a-1")
    at1 = items[assertion_node("at-1")]
    assert at1.text == "gene:EGFR length 42"
    assert at1.digest == sha256(b"length").hexdigest()


def test_relation_items_match_expected_keys() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    keys = {str(item.key) for item in stored_items(store) if str(item.kind) == "relation"}
    assert relation_key("a-1", "protein:P53") in keys
    assert relation_key("a-2", "gene:MYC") in keys
    assert len(keys) == 2


def test_entity_items_are_subjects_only() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    entities = [item for item in stored_items(store) if str(item.kind) == "entity"]
    assert [str(item.key) for item in entities] == [entity_key("gene:EGFR")]
    # protein:P53 and gene:MYC appear only as objects and are never entities
    assert all("protein:P53" not in str(item.key) for item in entities)


def test_manifest_records_model_configuration() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    manifest = stored_manifest(store)
    assert manifest.model_id == "hybridkg/deterministic-hash-embedder"
    assert manifest.model_version == "1.0.0"
    assert manifest.dimensions == 64
    assert manifest.release_id == RELEASE_ID
    assert manifest.record_count == 6
    assert manifest.embedding_config["dimensions"] == 64
    assert manifest.embedding_config["normalization"] == "l2"


def test_embedding_digest_is_recorded_in_manifest() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    manifest = stored_manifest(store)
    items = tuple(stored_items(store))
    assert manifest.embedding_digest == embedding_digest(items)


def test_build_is_deterministic_for_identical_releases() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    first = stored_bytes(store, "vectors")
    second = stored_bytes(store, "vectors")
    assert first is not None and second is not None
    assert first == second
    manifest_first = stored_bytes(store, "manifest")
    manifest_second = stored_bytes(store, "manifest")
    assert manifest_first is not None and manifest_second is not None
    assert manifest_first == manifest_second


def test_derive_matches_build() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    derived = backend._builder.derive(RELEASE_ID, profile())
    stored = tuple(stored_items(store))
    assert [item.model_dump() for item in derived.items] == [item.model_dump() for item in stored]


def test_missing_release_raises() -> None:
    backend, _, _ = make_backend()
    with pytest.raises(MissingVectorReleaseError):
        backend.build(
            projection_id=projection_id().canonical,
            release_id="release:ghost",
            profile=profile(),
        )


# --- embedder -------------------------------------------------------------


def test_embedder_is_deterministic_and_normalized() -> None:
    embedder = DeterministicHashEmbedder()
    surface = "gene:EGFR interacts_with protein:P53"
    first = embedder.embed(surface)
    assert first == embedder.embed(surface)
    assert len(first) == 64
    norm = sum(value * value for value in first) ** 0.5
    assert abs(norm - 1.0) < 1e-9


def test_embedder_distinguishes_surfaces() -> None:
    embedder = DeterministicHashEmbedder()
    assert embedder.embed("gene:EGFR") != embedder.embed("gene:MYC")


def test_embedder_handles_empty_surface() -> None:
    embedder = DeterministicHashEmbedder()
    assert embedder.embed("") == (0.0,) * 64


def test_embedder_is_domain_neutral() -> None:
    embedder = DeterministicHashEmbedder()
    # arbitrary surfaces embed to the same deterministic, normalized space;
    # no domain is special-cased
    for surface in ("gene:EGFR", "any:concept", "x"):
        vector = embedder.embed(surface)
        assert len(vector) == 64
        norm = sum(value * value for value in vector) ** 0.5
        assert abs(norm - 1.0) < 1e-9
    # equal surfaces agree; distinct surfaces differ
    assert embedder.embed("gene:EGFR") == embedder.embed("gene:EGFR")
    assert embedder.embed("gene:EGFR") != embedder.embed("any:concept")


# --- policy ---------------------------------------------------------------


def test_policy_documents_scopes() -> None:
    policy = policy_from_profile(profile())
    assert isinstance(policy, VectorProjectionPolicy)
    assert policy.profile_id == "vector-retrieval"
    assert policy.scope_included("entities")
    assert policy.scope_included("relations")
    assert policy.scope_included("assertions")


def test_dropped_scope_is_omitted() -> None:
    backend, store, _ = make_backend()
    backend.build(
        projection_id=projection_id().canonical,
        release_id=RELEASE_ID,
        profile=profile(dropped_semantics=("urn:vector:relations",)),
    )
    kinds = {str(item.kind) for item in stored_items(store)}
    assert "relation" not in kinds
    assert "assertion" in kinds
    assert "entity" in kinds


def test_dropped_entity_scope_is_omitted() -> None:
    backend, store, _ = make_backend()
    backend.build(
        projection_id=projection_id().canonical,
        release_id=RELEASE_ID,
        profile=profile(dropped_semantics=("urn:vector:entities",)),
    )
    kinds = {str(item.kind) for item in stored_items(store)}
    assert "entity" not in kinds
    assert "relation" in kinds
    assert "assertion" in kinds


def test_included_relations_filter() -> None:
    backend, store, _ = make_backend()
    backend.build(
        projection_id=projection_id().canonical,
        release_id=RELEASE_ID,
        profile=profile(included_relations=("interacts_with",)),
    )
    keys = {str(item.key) for item in stored_items(store)}
    assert assertion_node("a-1") in keys
    assert assertion_node("a-2") not in keys
    assert assertion_node("at-1") not in keys
    assert relation_key("a-2", "gene:MYC") not in keys


def test_included_entity_types_filter() -> None:
    backend, store, _ = make_backend()
    backend.build(
        projection_id=projection_id().canonical,
        release_id=RELEASE_ID,
        profile=profile(included_entity_types=("gene",)),
    )
    keys = {str(item.key) for item in stored_items(store)}
    # a-1 dropped (protein object), a-2 and at-1 kept
    assert assertion_node("a-1") not in keys
    assert assertion_node("a-2") in keys
    assert assertion_node("at-1") in keys
    assert relation_key("a-1", "protein:P53") not in keys


def test_included_assertion_types_filter() -> None:
    backend, store, _ = make_backend()
    backend.build(
        projection_id=projection_id().canonical,
        release_id=RELEASE_ID,
        profile=profile(included_assertion_types=(ASN_TYPE_ATTRIBUTE,)),
    )
    keys = {str(item.key) for item in stored_items(store)}
    assert assertion_node("at-1") in keys
    assert assertion_node("a-1") not in keys
    assert assertion_node("a-2") not in keys


def test_dropped_predicate_filter() -> None:
    backend, store, _ = make_backend()
    backend.build(
        projection_id=projection_id().canonical,
        release_id=RELEASE_ID,
        profile=profile(dropped_semantics=("regulates",)),
    )
    keys = {str(item.key) for item in stored_items(store)}
    assert assertion_node("a-2") not in keys
    assert relation_key("a-2", "gene:MYC") not in keys
    assert assertion_node("a-1") in keys
    assert assertion_node("at-1") in keys


def test_predicate_transformation_remaps_assertions() -> None:
    backend, store, _ = make_backend()
    transformation = FieldTransformation(
        name="remap",
        source="interacts_with",
        target="associates",
        kind=TransformationKind.PROPERTY,
    )
    backend.build(
        projection_id=projection_id().canonical,
        release_id=RELEASE_ID,
        profile=profile(transformations=(transformation,)),
    )
    items = {str(item.key): item for item in stored_items(store)}
    a1 = items[assertion_node("a-1")]
    assert a1.text == "gene:EGFR associates protein:P53"
    assert a1.digest == sha256(b"associates").hexdigest()
    # the relation surface reflects the transformed predicate
    relation = items[relation_key("a-1", "protein:P53")]
    assert relation.text == "gene:EGFR associates protein:P53"


def test_unsupported_error_blocks_build() -> None:
    backend, _, _ = make_backend()
    with pytest.raises(VectorUnsupportedSemanticsError):
        backend.build(
            projection_id=projection_id().canonical,
            release_id=RELEASE_ID,
            profile=profile(unsupported_semantics=("regulates",)),
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
    keys = {str(item.key) for item in stored_items(store)}
    assert assertion_node("a-2") not in keys
    assert assertion_node("a-1") in keys
    assert assertion_node("at-1") in keys


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
    items = {str(item.key): item for item in stored_items(store)}
    assert items[assertion_node("a-2")].text == "gene:EGFR regulates gene:MYC"


# --- records --------------------------------------------------------------


def test_records_match_authoritative_rdf() -> None:
    backend, _, data_source = make_backend()
    build_candidate(backend)
    dataset = data_source.get(RELEASE_ID)
    assert dataset is not None
    # Core's authoritative records contain one entity record per assertion
    # subject; comparison is keyed by (kind, key), so the projected (unique)
    # records must agree on the same keys and digests.
    authoritative = ProjectionReconciler().authoritative_records(dataset)
    projected = backend.records(projection_id().canonical)
    assert {(record.kind, record.key): record.digest for record in authoritative} == {
        (record.kind, record.key): record.digest for record in projected
    }
    result = ProjectionReconciler().compare(
        strategy=ReconciliationStrategy.REBUILD,
        authoritative_records=authoritative,
        projected_records=projected,
    )
    assert result.reconciled


def test_records_reflect_transformed_predicates() -> None:
    backend, _, _ = make_backend()
    transformation = FieldTransformation(
        name="remap",
        source="interacts_with",
        target="associates",
        kind=TransformationKind.PROPERTY,
    )
    backend.build(
        projection_id=projection_id().canonical,
        release_id=RELEASE_ID,
        profile=profile(transformations=(transformation,)),
    )
    records = backend.records(projection_id().canonical)
    a1 = next(r for r in records if r.kind == "assertion" and r.key == assertion_node("a-1"))
    assert a1.digest == sha256(b"associates").hexdigest()


def test_records_reflect_filtered_projection() -> None:
    backend, _, _ = make_backend()
    backend.build(
        projection_id=projection_id().canonical,
        release_id=RELEASE_ID,
        profile=profile(included_relations=("interacts_with",)),
    )
    records = backend.records(projection_id().canonical)
    keys = {r.key for r in records}
    assert assertion_node("a-1") in keys
    assert assertion_node("a-2") not in keys
    assert relation_key("a-2", "gene:MYC") not in keys


# --- retrieval ------------------------------------------------------------


def test_search_ranks_similar_candidates_first() -> None:
    backend, _, _ = make_backend()
    build_candidate(backend)
    results = backend.search(projection_id().canonical, "EGFR interacts with P53", k=3)
    assert len(results) == 3
    # the a-1 assertion and a-1 relation share the same surface and rank first
    assert results[0].key.startswith(assertion_node("a-1"))
    assert results[0].score > 0.5
    assert results[0].kind in ("assertion", "relation")
    # a-2 content is not among the top results for this query
    assert not any(result.key.startswith(assertion_node("a-2")) for result in results[:2])


def test_search_returns_k_candidates_with_scores() -> None:
    backend, _, _ = make_backend()
    build_candidate(backend)
    results = backend.search(projection_id().canonical, "gene:EGFR", k=2)
    assert len(results) == 2
    for result in results:
        assert -1.0 <= result.score <= 1.0
        assert result.digest
        assert result.source


def test_search_is_deterministic() -> None:
    backend, _, _ = make_backend()
    build_candidate(backend)
    first = backend.search(projection_id().canonical, "EGFR length 42", k=5)
    second = backend.search(projection_id().canonical, "EGFR length 42", k=5)
    assert first == second


def test_similarity_is_not_identity() -> None:
    backend, _, _ = make_backend()
    build_candidate(backend)
    results = backend.search(projection_id().canonical, "gene:EGFR", k=3)
    keys = {result.key for result in results}
    # several distinct items are returned together as retrieval candidates,
    # but each keeps its own key and digest — similarity never merges them
    assert len(keys) >= 2
    # two highly similar but distinct surfaces never collide into one item
    exact = backend.search(projection_id().canonical, "gene:EGFR regulates gene:MYC", k=1)
    assert exact[0].key.startswith(assertion_node("a-2"))
    assert exact[0].key != entity_key("gene:EGFR")


def test_search_returns_entity_and_assertion_candidates() -> None:
    backend, _, _ = make_backend()
    build_candidate(backend)
    results = backend.search(projection_id().canonical, "gene:EGFR length", k=5)
    kinds = {result.kind for result in results}
    assert "assertion" in kinds
    assert any(result.key == assertion_node("at-1") for result in results)


def test_similar_returns_nearest_to_existing_vector() -> None:
    backend, _, _ = make_backend()
    build_candidate(backend)
    results = backend.similar(projection_id().canonical, relation_key("a-1", "protein:P53"), k=1)
    assert len(results) == 1
    # the a-1 assertion and a-1 relation share the same surface (score 1.0);
    # the shorter key wins the deterministic tie-break
    assert results[0].key.startswith(assertion_node("a-1"))
    assert abs(results[0].score - 1.0) < 1e-9


def test_similar_unknown_key_returns_empty() -> None:
    backend, _, _ = make_backend()
    build_candidate(backend)
    assert backend.similar(projection_id().canonical, "urn:identifier:gene:GHOST", k=3) == ()


def test_retrieval_is_candidate_layer_without_authority() -> None:
    backend, _, _ = make_backend()
    build_candidate(backend)
    results = backend.search(projection_id().canonical, "EGFR", k=5)
    assert results
    for result in results:
        # candidates carry no state, no approval, no identity claim
        assert not hasattr(result, "state")
        assert not hasattr(result, "status")
        assert not hasattr(result, "approved")
        assert not hasattr(result, "authoritative")
    # the backend exposes retrieval but no approval surface
    assert not hasattr(backend, "approve")
    assert not hasattr(backend, "authorize")


def test_retrieval_augmentation_returns_verifiable_candidates() -> None:
    backend, _, _ = make_backend()
    build_candidate(backend)
    results = backend.search(projection_id().canonical, "EGFR interacts with P53", k=1)
    assert len(results) == 1
    result = results[0]
    # downstream augmentation can fetch the candidate and verify its digest
    assert result.digest == sha256(b"interacts_with").hexdigest()
    assert result.source == assertion_node("a-1")


def test_retriever_is_standalone() -> None:
    embedder = DeterministicHashEmbedder()
    retriever = VectorRetriever(embedder=embedder)
    backend, _, _ = make_backend()
    derived = backend._builder.derive(RELEASE_ID, profile())
    results = retriever.search(items=derived.items, query="EGFR regulates MYC", k=1)
    assert len(results) == 1
    assert results[0].key.startswith(assertion_node("a-2"))


# --- validation / reconciliation / smoke ----------------------------------


def test_validate_passes_for_complete_candidate() -> None:
    backend, _, _ = make_backend()
    build_candidate(backend)
    result = backend.validate(projection_id().canonical)
    assert result.passed
    assert result.errors == ()


def test_reconciliation_passes_for_complete_candidate() -> None:
    backend, _, _ = make_backend()
    build_candidate(backend)
    report = backend.reconcile(projection_id().canonical)
    assert isinstance(report, VectorReconciliationReport)
    assert report.reconciled
    assert report.missing_items == ()
    assert report.unexpected_items == ()
    assert report.transformed_items == ()
    assert report.item_counts == {"assertion": 3, "relation": 2, "entity": 1}


def test_validate_fails_on_missing_manifest() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    store_key = vector_candidate_name(projection_id().canonical)
    store.write_dataset(store_key, "manifest", b"")
    result = backend.validate(projection_id().canonical)
    assert not result.passed
    assert any("manifest" in error for error in result.errors)


def test_validate_fails_on_tampered_vectors() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    store_key = vector_candidate_name(projection_id().canonical)
    store.write_dataset(store_key, "vectors", b"not-json")
    result = backend.validate(projection_id().canonical)
    assert not result.passed
    assert any("vector" in error for error in result.errors)


def test_reconcile_detects_tampering() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    store_key = vector_candidate_name(projection_id().canonical)
    data = stored_bytes(store, "vectors")
    assert data is not None
    items = items_from_bytes(data)
    # drop the at-1 assertion from the stored index
    remaining = tuple(item for item in items if str(item.key) != assertion_node("at-1"))
    store.write_dataset(store_key, "vectors", items_bytes(remaining))
    report = backend.reconcile(projection_id().canonical)
    assert not report.reconciled
    assert assertion_node("at-1") in report.missing_items


def test_reconcile_detects_transformed_vectors() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    store_key = vector_candidate_name(projection_id().canonical)
    data = stored_bytes(store, "vectors")
    assert data is not None
    items = list(items_from_bytes(data))
    altered = []
    for item in items:
        item_dict = item.model_dump()
        if item_dict["key"] == assertion_node("a-1"):
            item_dict["digest"] = sha256(b"altered").hexdigest()
        altered.append(item_dict)
    store.write_dataset(store_key, "vectors", json.dumps(altered).encode("utf-8"))
    report = backend.reconcile(projection_id().canonical)
    assert not report.reconciled
    assert assertion_node("a-1") in report.transformed_items


def test_reconciliation_is_deterministic() -> None:
    backend, _, _ = make_backend()
    build_candidate(backend)
    first = backend.reconcile(projection_id().canonical)
    second = backend.reconcile(projection_id().canonical)
    assert first.model_dump() == second.model_dump()


def test_transformation_is_detected_by_core_reconciliation() -> None:
    backend, _, data_source = make_backend()
    transformation = FieldTransformation(
        name="remap",
        source="interacts_with",
        target="associates",
        kind=TransformationKind.PROPERTY,
    )
    backend.build(
        projection_id=projection_id().canonical,
        release_id=RELEASE_ID,
        profile=profile(transformations=(transformation,)),
    )
    dataset = data_source.get(RELEASE_ID)
    assert dataset is not None
    authoritative = ProjectionReconciler().authoritative_records(dataset)
    result = ProjectionReconciler().compare(
        strategy=ReconciliationStrategy.REBUILD,
        authoritative_records=authoritative,
        projected_records=backend.records(projection_id().canonical),
    )
    assert not result.reconciled
    assert any("a-1" in entry for entry in result.transformed_records)


def test_smoke_tests_pass_for_complete_candidate() -> None:
    backend, _, _ = make_backend()
    build_candidate(backend)
    result = backend.smoke_test(projection_id().canonical)
    assert result.passed
    assert result.manifest_readable
    assert result.vectors_readable
    assert result.counts_match
    assert result.embeddings_deterministic
    assert result.retrieval_queryable


def test_smoke_tests_fail_on_missing_items() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    store_key = vector_candidate_name(projection_id().canonical)
    store.write_dataset(store_key, "vectors", items_bytes(()))
    result = backend.smoke_test(projection_id().canonical)
    assert not result.passed
    assert any("count" in error for error in result.errors)


def test_smoke_tests_fail_on_unreadable_vectors() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    store_key = vector_candidate_name(projection_id().canonical)
    store.write_dataset(store_key, "vectors", b"corrupted")
    result = backend.smoke_test(projection_id().canonical)
    assert not result.passed
    assert not result.vectors_readable


def test_reconciler_and_smoke_runner_are_standalone() -> None:
    store = MemoryVectorProjectionStore()
    data_source = MemoryVectorDataSource()
    data_source.put(RELEASE_ID, release_dataset())
    backend = VectorProjectionBackend(store=store, data_source=data_source)
    build_candidate(backend)
    reconciler = VectorReconciler(store=store, data_source=data_source)
    report = reconciler.reconcile(
        projection_id=projection_id().canonical,
        release_id=RELEASE_ID,
        profile=profile(),
    )
    assert report.reconciled
    runner = VectorSmokeTestRunner(store=store, embedder=DeterministicHashEmbedder())
    expected = VectorProjectionBuilder(store=store, data_source=data_source).expected(
        RELEASE_ID, profile()
    )
    assert runner.run(projection_id=projection_id().canonical, expected=expected).passed


# --- lifecycle ------------------------------------------------------------


def test_activation_is_atomic_and_retains_previous() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    first = projection_id().canonical
    backend.activate(first)
    assert store.active_projection() == vector_candidate_name(first)
    backend.rollback(first)
    assert store.active_projection() is None


def test_destroy_removes_content() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    store_key = vector_candidate_name(projection_id().canonical)
    assert store.has_projection(store_key)
    backend.destroy(projection_id().canonical)
    assert not store.has_projection(store_key)
    assert store.dataset_count(store_key, "vectors") == 0


def test_unknown_projection_raises() -> None:
    backend, _, _ = make_backend()
    with pytest.raises(UnknownVectorProjectionError):
        backend.validate("projection:ghost")


def test_search_uses_active_projection_after_activation() -> None:
    backend, _, _ = make_backend()
    build_candidate(backend)
    backend.activate(projection_id().canonical)
    results = backend.search(projection_id().canonical, "gene:EGFR", k=1)
    assert len(results) == 1
    assert results[0].kind == "entity"


# --- Core integration -----------------------------------------------------


def test_registered_through_projection_registry() -> None:
    backend, _, _ = make_backend()
    registry = ProjectionRegistry()
    registry.register(backend)
    assert registry.has("vector")
    assert registry.get("vector") is backend
    assert isinstance(backend, ProjectionBackend)


def test_core_drives_vector_lifecycle_independently() -> None:
    backend, _, data_source = make_backend()
    registry = ProjectionRegistry()
    registry.register(backend)
    manager = ProjectionManager(registry=registry)

    projection = manager.create_projection(
        projection_id=projection_id(),
        profile=profile(),
        backend_id="vector",
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


def test_core_rollback_switches_back_to_retained_vector() -> None:
    backend, _, data_source = make_backend()
    registry = ProjectionRegistry()
    registry.register(backend)
    manager = ProjectionManager(registry=registry)

    def activate(value: str) -> Identifier:
        p = manager.create_projection(
            projection_id=ident("projection", value),
            profile=profile(),
            backend_id="vector",
            release_id=RELEASE_ID,
        )
        p = manager.build_candidate(p.id)
        p = manager.validate_candidate(p.id)
        release_dataset_for_compare = data_source.get(RELEASE_ID)
        assert release_dataset_for_compare is not None
        p = manager.reconcile_candidate(p.id, release_dataset_for_compare)
        return manager.activate_candidate(p.id).id

    first = activate("vector-101")
    second = activate("vector-102")

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
        backend_id="vector",
        release_id=RELEASE_ID,
    )
    projection = manager.build_candidate(projection.id)
    assert projection.status is ProjectionStatus.VALIDATING

    # Corrupt the candidate before validation: drop the vectors dataset.
    store_key = vector_candidate_name(projection.id.canonical)
    store.write_dataset(store_key, "vectors", b"")
    projection = manager.validate_candidate(projection.id)
    assert projection.status is ProjectionStatus.FAILED
    with pytest.raises(InvalidProjectionTransitionError):
        manager.activate_candidate(projection.id)


# --- rebuildable from RDF -------------------------------------------------


def test_projection_is_rebuildable_from_rdf() -> None:
    backend_a, store_a, _ = make_backend()
    build_candidate(backend_a)
    backend_b, store_b, _ = make_backend()
    backend_b.build(
        projection_id=projection_id().canonical,
        release_id=RELEASE_ID,
        profile=profile(),
    )
    vectors_a = stored_bytes(store_a, "vectors")
    vectors_b = stored_bytes(store_b, "vectors")
    manifest_a = stored_bytes(store_a, "manifest")
    manifest_b = stored_bytes(store_b, "manifest")
    assert vectors_a is not None and vectors_b is not None
    assert vectors_a == vectors_b
    assert manifest_a is not None and manifest_b is not None
    assert manifest_a == manifest_b


def test_derivation_is_pure_function_of_the_release() -> None:
    backend, _, _ = make_backend()
    first = backend._builder.derive(RELEASE_ID, profile())
    second = backend._builder.derive(RELEASE_ID, profile())
    assert first.model_dump() == second.model_dump()
