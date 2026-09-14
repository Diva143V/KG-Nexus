"""Phase 18: search projection backend tests.

Exercises the search projection end to end: an authoritative RDF release is
materialized into deterministic search documents (entities, relations,
assertions) plus a manifest recording the search engine id, engine version,
engine configuration, source release, and content digest, through the
pluggable ProjectionBackend contract. The projection is a textual discovery
layer only: full-text search, aliases, labels, descriptions, and identifiers.
Search ranking never establishes identity or truth, results are retrieval
candidates with scores, and nothing here approves assertions or replaces any
policy or validator. RDF stays authoritative and the projection is rebuildable
from RDF.
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
from infrastructure.projections.search import (
    DEFAULT_ENGINE_ID,
    DEFAULT_ENGINE_VERSION,
    DefaultTextSearchEngine,
    InvertedSearchIndex,
    MemorySearchDataSource,
    MemorySearchProjectionStore,
    MissingSearchReleaseError,
    SearchDocument,
    SearchManifest,
    SearchProjectionBackend,
    SearchProjectionBuilder,
    SearchProjectionPolicy,
    SearchReconciler,
    SearchReconciliationReport,
    SearchRetriever,
    SearchSmokeTestRunner,
    SearchUnsupportedSemanticsError,
    UnknownSearchProjectionError,
    content_digest,
    policy_from_profile,
    search_candidate_name,
    tokenize,
)
from infrastructure.projections.search.writer import (
    documents_bytes,
    documents_from_bytes,
    manifest_from_bytes,
)
from tests.helpers import ident, utc

RELEASE_ID = "release:kg-2026.1"
PROJECTION_VALUE = "search-2026-001"

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
        # source (non-approved) assertion: never indexed by the search backend
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
        profile_id="search-discovery",
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
    SearchProjectionBackend, MemorySearchProjectionStore, MemorySearchDataSource
]:
    store = MemorySearchProjectionStore()
    data_source = MemorySearchDataSource()
    data_source.put(RELEASE_ID, release_dataset())
    backend = SearchProjectionBackend(store=store, data_source=data_source)
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


def build_candidate(backend: SearchProjectionBackend) -> None:
    backend.build(
        projection_id=projection_id().canonical,
        release_id=RELEASE_ID,
        profile=profile(),
    )


def stored_bytes(
    store: MemorySearchProjectionStore,
    name: str,
    projection_value: str = PROJECTION_VALUE,
) -> bytes | None:
    store_key = search_candidate_name(f"projection:{projection_value}")
    return store.read_dataset(store_key, name)


def stored_documents(
    store: MemorySearchProjectionStore,
    projection_value: str = PROJECTION_VALUE,
) -> tuple[object, ...]:
    data = stored_bytes(store, "documents", projection_value)
    assert data is not None
    return documents_from_bytes(data)


def stored_manifest(
    store: MemorySearchProjectionStore,
    projection_value: str = PROJECTION_VALUE,
) -> SearchManifest:
    data = stored_bytes(store, "manifest", projection_value)
    assert data is not None
    return manifest_from_bytes(data)


# --- store ----------------------------------------------------------------


def test_search_candidate_name_is_scoped() -> None:
    assert search_candidate_name("projection:p1") == "search_projection:p1_candidate"


def test_memory_store_roundtrip() -> None:
    store = MemorySearchProjectionStore()
    store_key = search_candidate_name("projection:p1")
    payload = b"search-bytes"
    store.write_dataset(store_key, "documents", payload)
    assert store.has_projection(store_key)
    assert store.read_dataset(store_key, "documents") == payload
    assert store.dataset_names(store_key) == ("documents",)
    assert store.dataset_count(store_key, "documents") == 0
    store.activate(store_key)
    assert store.active_projection() == store_key
    store.rollback(store_key)
    assert store.active_projection() is None
    store.delete_projection(store_key)
    assert not store.has_projection(store_key)


# --- serialization --------------------------------------------------------


def test_documents_serialization_roundtrip_is_byte_stable() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    data = stored_bytes(store, "documents")
    assert data is not None
    documents = documents_from_bytes(data)
    assert documents_bytes(documents) == data


def test_content_digest_is_deterministic() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    data = stored_bytes(store, "documents")
    assert data is not None
    documents = documents_from_bytes(data)
    assert content_digest(documents) == content_digest(documents)


# --- tokenizer / index ----------------------------------------------------


def test_tokenize_is_lower_alnum() -> None:
    assert tokenize("gene:EGFR interacts_with protein:P53!") == (
        "gene",
        "egfr",
        "interacts",
        "with",
        "protein",
        "p53",
    )


def test_inverted_index_counts_terms_and_resolves_aliases() -> None:
    documents = (
        SearchDocument(
            doc_id="d1",
            kind="entity",
            digest="digest-1",
            label="gene:EGFR",
            description="gene:EGFR",
            aliases=("EGFR", "gene", "gene:EGFR"),
            identifiers=("gene:EGFR",),
            text="gene:EGFR EGFR",
        ),
        SearchDocument(
            doc_id="d2",
            kind="assertion",
            digest="digest-2",
            label="regulates",
            description="gene:EGFR regulates gene:MYC",
            aliases=("gene:EGFR", "regulates", "gene:MYC"),
            identifiers=("gene:EGFR",),
            text="gene:EGFR regulates gene:MYC",
        ),
    )
    index = InvertedSearchIndex(documents)
    assert index.size == 2
    # full-text covers text, aliases, and identifiers; "EGFR" appears in both
    hits = index.search("EGFR", 5)
    assert hits == (("d1", 5), ("d2", 3))
    # "regulates" appears in d2's text and aliases
    exact = index.search("regulates", 5)
    assert exact == (("d2", 2),)
    assert index.resolve_alias("EGFR") == ("d1",)
    assert index.resolve_alias("egfr") == ("d1",)
    assert index.resolve_alias("gene:EGFR") == ("d1", "d2")
    assert index.search("", 5) == ()


def test_default_engine_records_configuration() -> None:
    engine = DefaultTextSearchEngine()
    assert engine.engine_id == DEFAULT_ENGINE_ID
    assert engine.engine_version == DEFAULT_ENGINE_VERSION
    assert engine.engine_config["tokenization"] == "lower-alnum"
    assert engine.engine_config["scoring"] == "term-frequency"


# --- builder --------------------------------------------------------------


def test_derive_produces_all_three_kinds() -> None:
    backend, store, _ = make_backend()
    expected = backend._builder.expected(RELEASE_ID, profile())
    assert expected.document_count == 6
    assert expected.assertion_count == 3
    assert expected.relation_count == 2
    assert expected.entity_count == 1
    build_candidate(backend)
    assert store.dataset_count(search_candidate_name(projection_id().canonical), "documents") == 6


def test_assertion_documents_match_expected_rows() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    documents = {str(document.doc_id): document for document in stored_documents(store)}
    a1 = documents[assertion_node("a-1")]
    assert a1.kind == "assertion"
    assert a1.digest == sha256(b"interacts_with").hexdigest()
    assert a1.label == "interacts_with"
    assert a1.description == "gene:EGFR interacts_with protein:P53"
    assert a1.text == "gene:EGFR interacts_with protein:P53"
    at1 = documents[assertion_node("at-1")]
    assert at1.description == "gene:EGFR length 42"
    assert at1.digest == sha256(b"length").hexdigest()


def test_relation_documents_match_expected_keys() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    keys = {
        str(document.doc_id)
        for document in stored_documents(store)
        if str(document.kind) == "relation"
    }
    assert relation_key("a-1", "protein:P53") in keys
    assert relation_key("a-2", "gene:MYC") in keys
    assert len(keys) == 2


def test_entity_documents_are_subjects_only_with_discovery_fields() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    entities = [document for document in stored_documents(store) if str(document.kind) == "entity"]
    assert [str(document.doc_id) for document in entities] == [entity_key("gene:EGFR")]
    entity = entities[0]
    assert entity.label == "gene:EGFR"
    assert entity.aliases == ("EGFR", "gene", "gene:EGFR")
    assert entity.identifiers == ("gene:EGFR", "urn:identifier:gene:EGFR")
    assert entity.text == "gene:EGFR"
    assert all("protein:P53" not in str(document.doc_id) for document in entities)


def test_manifest_records_engine_configuration() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    manifest = stored_manifest(store)
    assert manifest.engine_id == DEFAULT_ENGINE_ID
    assert manifest.engine_version == DEFAULT_ENGINE_VERSION
    assert manifest.release_id == RELEASE_ID
    assert manifest.record_count == 6
    assert manifest.engine_config["tokenization"] == "lower-alnum"
    assert manifest.engine_config["scoring"] == "term-frequency"


def test_content_digest_is_recorded_in_manifest() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    manifest = stored_manifest(store)
    documents = tuple(stored_documents(store))
    assert manifest.content_digest == content_digest(documents)


def test_build_is_deterministic_for_identical_releases() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    first = stored_bytes(store, "documents")
    second = stored_bytes(store, "documents")
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
    stored = tuple(stored_documents(store))
    assert [document.model_dump() for document in derived.documents] == [
        document.model_dump() for document in stored
    ]


def test_missing_release_raises() -> None:
    backend, _, _ = make_backend()
    with pytest.raises(MissingSearchReleaseError):
        backend.build(
            projection_id=projection_id().canonical,
            release_id="release:ghost",
            profile=profile(),
        )


# --- policy ---------------------------------------------------------------


def test_policy_documents_scopes() -> None:
    policy = policy_from_profile(profile())
    assert isinstance(policy, SearchProjectionPolicy)
    assert policy.profile_id == "search-discovery"
    assert policy.scope_included("entities")
    assert policy.scope_included("relations")
    assert policy.scope_included("assertions")


def test_dropped_scope_is_omitted() -> None:
    backend, store, _ = make_backend()
    backend.build(
        projection_id=projection_id().canonical,
        release_id=RELEASE_ID,
        profile=profile(dropped_semantics=("urn:search:relations",)),
    )
    kinds = {str(document.kind) for document in stored_documents(store)}
    assert "relation" not in kinds
    assert "assertion" in kinds
    assert "entity" in kinds


def test_dropped_entity_scope_is_omitted() -> None:
    backend, store, _ = make_backend()
    backend.build(
        projection_id=projection_id().canonical,
        release_id=RELEASE_ID,
        profile=profile(dropped_semantics=("urn:search:entities",)),
    )
    kinds = {str(document.kind) for document in stored_documents(store)}
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
    keys = {str(document.doc_id) for document in stored_documents(store)}
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
    keys = {str(document.doc_id) for document in stored_documents(store)}
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
    keys = {str(document.doc_id) for document in stored_documents(store)}
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
    keys = {str(document.doc_id) for document in stored_documents(store)}
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
    documents = {str(document.doc_id): document for document in stored_documents(store)}
    a1 = documents[assertion_node("a-1")]
    assert a1.description == "gene:EGFR associates protein:P53"
    assert a1.label == "associates"
    assert a1.digest == sha256(b"associates").hexdigest()
    # the relation surface reflects the transformed predicate
    relation = documents[relation_key("a-1", "protein:P53")]
    assert relation.description == "gene:EGFR associates protein:P53"


def test_unsupported_error_blocks_build() -> None:
    backend, _, _ = make_backend()
    with pytest.raises(SearchUnsupportedSemanticsError):
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
    keys = {str(document.doc_id) for document in stored_documents(store)}
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
    documents = {str(document.doc_id): document for document in stored_documents(store)}
    assert documents[assertion_node("a-2")].description == "gene:EGFR regulates gene:MYC"


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


def test_search_ranks_relevant_candidates_first() -> None:
    backend, _, _ = make_backend()
    build_candidate(backend)
    results = backend.search(projection_id().canonical, "EGFR interacts with P53", k=3)
    assert len(results) == 3
    # the a-1 assertion and a-1 relation carry the matching terms and rank first
    assert results[0].doc_id.startswith(assertion_node("a-1"))
    assert results[0].score >= results[1].score
    assert results[0].kind in ("assertion", "relation")
    # a-2 content is not among the top results for this query
    assert not any(result.doc_id.startswith(assertion_node("a-2")) for result in results[:2])


def test_search_returns_k_candidates_with_scores() -> None:
    backend, _, _ = make_backend()
    build_candidate(backend)
    results = backend.search(projection_id().canonical, "gene:EGFR", k=2)
    assert len(results) == 2
    for result in results:
        assert isinstance(result.score, int)
        assert result.score >= 0
        assert result.digest
        assert result.label


def test_search_is_deterministic() -> None:
    backend, _, _ = make_backend()
    build_candidate(backend)
    first = backend.search(projection_id().canonical, "EGFR length 42", k=5)
    second = backend.search(projection_id().canonical, "EGFR length 42", k=5)
    assert first == second


def test_search_covers_aliases_and_identifiers() -> None:
    backend, _, _ = make_backend()
    build_candidate(backend)
    # "EGFR" is an alias of the entity document, so it is discoverable
    results = backend.search(projection_id().canonical, "EGFR", k=5)
    assert any(result.doc_id == entity_key("gene:EGFR") for result in results)
    # the identifier IRI is itself a searchable field
    by_iri = backend.search(projection_id().canonical, "urn:identifier:gene:EGFR", k=5)
    assert any(result.doc_id == entity_key("gene:EGFR") for result in by_iri)


def test_ranked_results_keep_distinct_documents() -> None:
    backend, _, _ = make_backend()
    build_candidate(backend)
    results = backend.search(projection_id().canonical, "gene:EGFR", k=3)
    doc_ids = [result.doc_id for result in results]
    assert len(set(doc_ids)) == len(doc_ids)


def test_alias_resolution_is_exact_and_case_insensitive() -> None:
    backend, _, _ = make_backend()
    build_candidate(backend)
    exact = backend.resolve_alias(projection_id().canonical, "EGFR")
    assert len(exact) == 1
    assert exact[0].doc_id == entity_key("gene:EGFR")
    assert exact[0].kind == "entity"
    folded = backend.resolve_alias(projection_id().canonical, "egfr")
    assert folded == exact


def test_resolve_alias_matches_multiple_documents_deterministically() -> None:
    backend, _, _ = make_backend()
    build_candidate(backend)
    results = backend.resolve_alias(projection_id().canonical, "gene:EGFR")
    doc_ids = [result.doc_id for result in results]
    assert doc_ids == sorted(doc_ids)
    assert entity_key("gene:EGFR") in doc_ids
    assert assertion_node("a-1") in doc_ids


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


def test_search_result_is_verifiable_candidate() -> None:
    backend, _, _ = make_backend()
    build_candidate(backend)
    results = backend.search(projection_id().canonical, "interacts_with", k=1)
    assert len(results) == 1
    result = results[0]
    # downstream consumers can fetch the candidate and verify its digest
    assert result.digest == sha256(b"interacts_with").hexdigest()
    assert result.doc_id.startswith(assertion_node("a-1"))


def test_retriever_is_standalone() -> None:
    engine = DefaultTextSearchEngine()
    backend, _, _ = make_backend()
    derived = backend._builder.derive(RELEASE_ID, profile())
    index = engine.index(derived.documents)
    retriever = SearchRetriever(index=index)
    results = retriever.search(
        documents=derived.documents,
        query="EGFR regulates MYC",
        k=1,
    )
    assert len(results) == 1
    assert results[0].doc_id.startswith(assertion_node("a-2"))


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
    assert isinstance(report, SearchReconciliationReport)
    assert report.reconciled
    assert report.missing_documents == ()
    assert report.unexpected_documents == ()
    assert report.transformed_documents == ()
    assert report.document_counts == {"assertion": 3, "relation": 2, "entity": 1}


def test_validate_fails_on_missing_manifest() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    store_key = search_candidate_name(projection_id().canonical)
    store.write_dataset(store_key, "manifest", b"")
    result = backend.validate(projection_id().canonical)
    assert not result.passed
    assert any("manifest" in error for error in result.errors)


def test_validate_fails_on_tampered_documents() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    store_key = search_candidate_name(projection_id().canonical)
    store.write_dataset(store_key, "documents", b"not-json")
    result = backend.validate(projection_id().canonical)
    assert not result.passed
    assert any("document" in error for error in result.errors)


def test_reconcile_detects_tampering() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    store_key = search_candidate_name(projection_id().canonical)
    data = stored_bytes(store, "documents")
    assert data is not None
    documents = documents_from_bytes(data)
    # drop the at-1 assertion from the stored index
    remaining = tuple(
        document for document in documents if str(document.doc_id) != assertion_node("at-1")
    )
    store.write_dataset(store_key, "documents", documents_bytes(remaining))
    report = backend.reconcile(projection_id().canonical)
    assert not report.reconciled
    assert assertion_node("at-1") in report.missing_documents


def test_reconcile_detects_transformed_documents() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    store_key = search_candidate_name(projection_id().canonical)
    data = stored_bytes(store, "documents")
    assert data is not None
    documents = list(documents_from_bytes(data))
    altered = []
    for document in documents:
        document_dict = document.model_dump()
        if document_dict["doc_id"] == assertion_node("a-1"):
            document_dict["digest"] = sha256(b"altered").hexdigest()
        altered.append(document_dict)
    store.write_dataset(store_key, "documents", json.dumps(altered).encode("utf-8"))
    report = backend.reconcile(projection_id().canonical)
    assert not report.reconciled
    assert assertion_node("a-1") in report.transformed_documents


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
    assert result.documents_readable
    assert result.counts_match
    assert result.documents_deterministic
    assert result.full_text_queryable
    assert result.aliases_resolvable


def test_smoke_tests_fail_on_missing_documents() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    store_key = search_candidate_name(projection_id().canonical)
    store.write_dataset(store_key, "documents", documents_bytes(()))
    result = backend.smoke_test(projection_id().canonical)
    assert not result.passed
    assert any("count" in error for error in result.errors)


def test_smoke_tests_fail_on_unreadable_documents() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    store_key = search_candidate_name(projection_id().canonical)
    store.write_dataset(store_key, "documents", b"corrupted")
    result = backend.smoke_test(projection_id().canonical)
    assert not result.passed
    assert not result.documents_readable


def test_reconciler_and_smoke_runner_are_standalone() -> None:
    store = MemorySearchProjectionStore()
    data_source = MemorySearchDataSource()
    data_source.put(RELEASE_ID, release_dataset())
    backend = SearchProjectionBackend(store=store, data_source=data_source)
    build_candidate(backend)
    reconciler = SearchReconciler(store=store, data_source=data_source)
    report = reconciler.reconcile(
        projection_id=projection_id().canonical,
        release_id=RELEASE_ID,
        profile=profile(),
    )
    assert report.reconciled
    runner = SearchSmokeTestRunner(store=store, engine=DefaultTextSearchEngine())
    expected = SearchProjectionBuilder(store=store, data_source=data_source).expected(
        RELEASE_ID, profile()
    )
    assert runner.run(projection_id=projection_id().canonical, expected=expected).passed


# --- lifecycle ------------------------------------------------------------


def test_activation_is_atomic_and_retains_previous() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    first = projection_id().canonical
    backend.activate(first)
    assert store.active_projection() == search_candidate_name(first)
    backend.rollback(first)
    assert store.active_projection() is None


def test_destroy_removes_content() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    store_key = search_candidate_name(projection_id().canonical)
    assert store.has_projection(store_key)
    backend.destroy(projection_id().canonical)
    assert not store.has_projection(store_key)
    assert store.dataset_count(store_key, "documents") == 0


def test_unknown_projection_raises() -> None:
    backend, _, _ = make_backend()
    with pytest.raises(UnknownSearchProjectionError):
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
    assert registry.has("search")
    assert registry.get("search") is backend
    assert isinstance(backend, ProjectionBackend)


def test_core_drives_search_lifecycle_independently() -> None:
    backend, _, data_source = make_backend()
    registry = ProjectionRegistry()
    registry.register(backend)
    manager = ProjectionManager(registry=registry)

    projection = manager.create_projection(
        projection_id=projection_id(),
        profile=profile(),
        backend_id="search",
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


def test_core_rollback_switches_back_to_retained_search() -> None:
    backend, _, data_source = make_backend()
    registry = ProjectionRegistry()
    registry.register(backend)
    manager = ProjectionManager(registry=registry)

    def activate(value: str) -> Identifier:
        p = manager.create_projection(
            projection_id=ident("projection", value),
            profile=profile(),
            backend_id="search",
            release_id=RELEASE_ID,
        )
        p = manager.build_candidate(p.id)
        p = manager.validate_candidate(p.id)
        release_dataset_for_compare = data_source.get(RELEASE_ID)
        assert release_dataset_for_compare is not None
        p = manager.reconcile_candidate(p.id, release_dataset_for_compare)
        return manager.activate_candidate(p.id).id

    first = activate("search-101")
    second = activate("search-102")

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
        backend_id="search",
        release_id=RELEASE_ID,
    )
    projection = manager.build_candidate(projection.id)
    assert projection.status is ProjectionStatus.VALIDATING

    # Corrupt the candidate before validation: drop the documents dataset.
    store_key = search_candidate_name(projection.id.canonical)
    store.write_dataset(store_key, "documents", b"")
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
    documents_a = stored_bytes(store_a, "documents")
    documents_b = stored_bytes(store_b, "documents")
    manifest_a = stored_bytes(store_a, "manifest")
    manifest_b = stored_bytes(store_b, "manifest")
    assert documents_a is not None and documents_b is not None
    assert documents_a == documents_b
    assert manifest_a is not None and manifest_b is not None
    assert manifest_a == manifest_b


def test_derivation_is_pure_function_of_the_release() -> None:
    backend, _, _ = make_backend()
    first = backend._builder.derive(RELEASE_ID, profile())
    second = backend._builder.derive(RELEASE_ID, profile())
    assert first.model_dump() == second.model_dump()
