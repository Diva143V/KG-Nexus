"""Phase 16: Parquet analytical projection backend tests.

Exercises the analytical projection end to end: an authoritative RDF release
is materialized into deterministic Parquet datasets (entities, relations,
assertions, provenance, evidence) whose exact content is defined by the
ProjectionProfile, through the pluggable ProjectionBackend contract. RDF stays
authoritative; Parquet is a consumer-only view for large-scale analytics and
is never a second semantic authority.
"""

from __future__ import annotations

from hashlib import sha256

import pyarrow.parquet as pq
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
    NamedGraphCategory,
    RDFDataset,
    RDFReleaseWriter,
    graph_name,
)
from core.rdf.writer import (
    EV_CLAIM,
    EV_EVIDENCE,
    EV_KIND,
    EV_OBTAINED_AT,
    EV_RECORD,
)
from core.releases.manifest import LockfileSet, ReleaseManifest
from core.releases.release import Release, ReleaseGate
from core.releases.status import ReleaseStatus
from infrastructure.projections.parquet import (
    MemoryParquetDataSource,
    MemoryParquetProjectionStore,
    ParquetProjectionBackend,
    ParquetProjectionBuilder,
    ParquetProjectionPolicy,
    ParquetReconciler,
    ParquetReconciliationReport,
    ParquetSmokeTestRunner,
    ParquetUnsupportedSemanticsError,
    UnknownParquetProjectionError,
    parquet_candidate_name,
    policy_from_profile,
)
from infrastructure.projections.parquet.datasets import DATASET_COLUMNS
from infrastructure.projections.parquet.writer import (
    parquet_bytes,
    rows_from_bytes,
    table_from_bytes,
)
from tests.helpers import ident, utc

RELEASE_ID = "release:kg-2026.1"
PROJECTION_VALUE = "parquet-2026-001"

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
    preserved_fields: tuple[str, ...] = (),
    transformations: tuple[FieldTransformation, ...] = (),
    dropped_semantics: tuple[str, ...] = (),
    unsupported_semantics: tuple[str, ...] = (),
    unsupported_behavior: UnsupportedBehavior = UnsupportedBehavior.ERROR,
) -> ProjectionProfile:
    return ProjectionProfile(
        profile_id="parquet-analytics",
        profile_version="1",
        source_release_type="approved",
        preserved_fields=preserved_fields,
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
    ParquetProjectionBackend, MemoryParquetProjectionStore, MemoryParquetDataSource
]:
    store = MemoryParquetProjectionStore()
    data_source = MemoryParquetDataSource()
    data_source.put(RELEASE_ID, release_dataset())
    backend = ParquetProjectionBackend(store=store, data_source=data_source)
    return backend, store, data_source


def projection_id() -> Identifier:
    return ident("projection", PROJECTION_VALUE)


def assertion_node(aid: str) -> str:
    """RDF IRI of an assertion node, matching the Phase 11 writer."""
    return f"urn:assertion:{ident('assertion', aid).canonical}"


def build_candidate(backend: ParquetProjectionBackend) -> None:
    backend.build(
        projection_id=projection_id().canonical,
        release_id=RELEASE_ID,
        profile=profile(),
    )


def stored_rows(
    store: MemoryParquetProjectionStore,
    name: str,
    projection_value: str = PROJECTION_VALUE,
) -> tuple[dict[str, object], ...]:
    store_key = parquet_candidate_name(f"projection:{projection_value}")
    data = store.read_dataset(store_key, name)
    assert data is not None
    return rows_from_bytes(data)


def expectation_rows() -> tuple[dict[str, object], ...]:
    return (
        {
            "assertion_id": "assertion:a-1",
            "kind": "relationship",
            "subject": "gene:EGFR",
            "predicate": "interacts_with",
            "object": "protein:P53",
            "value": None,
            "state": "approved",
        },
        {
            "assertion_id": "assertion:a-2",
            "kind": "relationship",
            "subject": "gene:EGFR",
            "predicate": "regulates",
            "object": "gene:MYC",
            "value": None,
            "state": "approved",
        },
        {
            "assertion_id": "assertion:a-9",
            "kind": "relationship",
            "subject": "entity:e-9",
            "predicate": "causes",
            "object": "entity:e-10",
            "value": None,
            "state": "candidate",
        },
        {
            "assertion_id": "assertion:at-1",
            "kind": "attribute",
            "subject": "gene:EGFR",
            "predicate": "length",
            "object": None,
            "value": "42",
            "state": "approved",
        },
    )


# --- store / naming --------------------------------------------------------


def test_candidate_name_is_scoped() -> None:
    assert parquet_candidate_name("projection:p1") == "parquet_projection:p1_candidate"


def test_memory_store_roundtrip() -> None:
    store = MemoryParquetProjectionStore()
    data = parquet_bytes(
        ({"entity_id": "gene:EGFR", "namespace": "gene"},),
        DATASET_COLUMNS["entities"],
    )
    store.write_dataset("k1", "entities", data)
    assert store.read_dataset("k1", "entities") == data
    assert store.dataset_names("k1") == ("entities",)
    assert store.dataset_row_count("k1", "entities") == 1


# --- parquet writer --------------------------------------------------------


def test_parquet_roundtrip_preserves_values() -> None:
    columns = (
        "assertion_id",
        "agent",
        "activity",
        "asserted_at",
        "method",
        "input_assertions",
        "input_resources",
    )
    source = (
        {
            "assertion_id": "assertion:a-1",
            "agent": "agent:curator-1",
            "activity": "activity:act-1",
            "asserted_at": "2026-01-01T00:00:00",
            "method": None,
            "input_assertions": ["assertion:src-1", "assertion:src-2"],
            "input_resources": [],
        },
    )
    data = parquet_bytes(source, columns)
    assert rows_from_bytes(data) == source


def test_identical_rows_produce_identical_bytes() -> None:
    first = parquet_bytes(
        ({"entity_id": "gene:EGFR", "namespace": "gene"},),
        DATASET_COLUMNS["entities"],
    )
    second = parquet_bytes(
        ({"entity_id": "gene:EGFR", "namespace": "gene"},),
        DATASET_COLUMNS["entities"],
    )
    assert first == second


def test_parquet_bytes_are_real_parquet(tmp_path) -> None:
    data = parquet_bytes(
        (
            {"entity_id": "gene:EGFR", "namespace": "gene"},
            {"entity_id": "protein:P53", "namespace": "protein"},
        ),
        DATASET_COLUMNS["entities"],
    )
    path = tmp_path / "entities.parquet"
    path.write_bytes(data)
    table = pq.read_table(path)
    assert table.to_pylist() == [
        {"entity_id": "gene:EGFR", "namespace": "gene"},
        {"entity_id": "protein:P53", "namespace": "protein"},
    ]


# --- writer evidence -------------------------------------------------------


def test_writer_serializes_assertion_evidence() -> None:
    dataset = release_dataset()
    prov = dataset.graph(graph_name(NamedGraphCategory.PROVENANCE))
    assert prov is not None
    predicates = {triple.predicate.value for triple in prov.triples}
    assert {
        EV_EVIDENCE,
        EV_CLAIM,
        EV_KIND,
        EV_RECORD,
        EV_OBTAINED_AT,
    } <= predicates
    assert any(
        triple.predicate.value == EV_EVIDENCE
        and triple.subject.value == assertion_node("a-1")
        and triple.object.value == "urn:identifier:evidence:e-1"
        for triple in prov.triples
    )


# --- full materialization --------------------------------------------------


def test_derive_produces_all_five_datasets() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    store_key = parquet_candidate_name(projection_id().canonical)
    assert store.dataset_names(store_key) == (
        "assertions",
        "entities",
        "evidence",
        "provenance",
        "relations",
    )


def test_assertions_dataset_matches_expected_rows() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    assert stored_rows(store, "assertions") == expectation_rows()


def test_relations_dataset_contains_only_relationships() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    rows = stored_rows(store, "relations")
    assert {str(row["assertion_id"]) for row in rows} == {
        "assertion:a-1",
        "assertion:a-2",
        "assertion:a-9",
    }
    for row in rows:
        assert row["object"] is not None


def test_entities_dataset_is_deterministic() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    assert stored_rows(store, "entities") == (
        {"entity_id": "entity:e-10", "namespace": "entity"},
        {"entity_id": "entity:e-9", "namespace": "entity"},
        {"entity_id": "gene:EGFR", "namespace": "gene"},
        {"entity_id": "gene:MYC", "namespace": "gene"},
        {"entity_id": "protein:P53", "namespace": "protein"},
    )


def test_provenance_dataset_matches_expected_rows() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    rows = stored_rows(store, "provenance")
    assert len(rows) == 4
    for row in rows:
        assert row["agent"] == "agent:curator-1"
        assert row["activity"] == "activity:act-1"
        assert row["asserted_at"] == "2026-01-01T00:00:00"
        assert row["method"] is None
        assert row["input_assertions"] == []
        assert row["input_resources"] == []
    assert {str(row["assertion_id"]) for row in rows} == {
        "assertion:a-1",
        "assertion:a-2",
        "assertion:a-9",
        "assertion:at-1",
    }


def test_evidence_dataset_matches_expected_rows() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    assert stored_rows(store, "evidence") == (
        {
            "evidence_id": "evidence:e-1",
            "claim_id": "assertion:a-1",
            "kind": "primary",
            "record_id": "record:r-1",
            "artifact_id": "artifact:doc-1",
            "obtained_at": "2026-01-05T00:00:00",
        },
        {
            "evidence_id": "evidence:e-2",
            "claim_id": "assertion:at-1",
            "kind": "secondary",
            "record_id": "record:r-2",
            "artifact_id": None,
            "obtained_at": "2026-01-06T00:00:00",
        },
    )


def test_build_is_deterministic_for_identical_releases() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    store_key = parquet_candidate_name(projection_id().canonical)
    first = {name: store.read_dataset(store_key, name) for name in store.dataset_names(store_key)}

    other_store = MemoryParquetProjectionStore()
    other_data = MemoryParquetDataSource()
    other_data.put(RELEASE_ID, release_dataset())
    other = ParquetProjectionBackend(store=other_store, data_source=other_data)
    other.build(
        projection_id="projection:parquet-002",
        release_id=RELEASE_ID,
        profile=profile(),
    )
    other_key = parquet_candidate_name("projection:parquet-002")
    second = {
        name: other_store.read_dataset(other_key, name)
        for name in other_store.dataset_names(other_key)
    }

    assert first == second
    assert all(data is not None for data in first.values())


def test_derive_matches_build() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    derived = backend._builder.derive(RELEASE_ID, profile())
    for name in derived.dataset_names:
        assert stored_rows(store, name) == derived.datasets[name]


# --- profile policy --------------------------------------------------------


def test_policy_documents_datasets_and_columns() -> None:
    policy = policy_from_profile(
        profile(
            included_relations=("interacts_with",),
            included_entity_types=("gene",),
            preserved_fields=("urn:prov:agent", "urn:evidence:kind", "urn:evidence:record"),
            dropped_semantics=("regulates", "urn:parquet:evidence"),
            transformations=(
                FieldTransformation(
                    name="remap",
                    source="interacts_with",
                    target="associates",
                    kind=TransformationKind.EDGE,
                ),
            ),
        )
    )
    assert isinstance(policy, ParquetProjectionPolicy)
    assert policy.included_relations == ("interacts_with",)
    assert policy.included_entity_types == ("gene",)
    assert policy.dropped_predicates == ("regulates",)
    assert policy.dropped_datasets == ("evidence",)
    assert policy.transformed_predicates == (("interacts_with", "associates"),)
    assert policy.transformed_map == {"interacts_with": "associates"}
    assert policy.provenance_columns == ("agent",)
    assert policy.evidence_columns == ("kind", "record_id")
    assert not policy.dataset_included("evidence")
    assert policy.dataset_included("entities")


def test_dropped_dataset_is_omitted() -> None:
    backend, store, _ = make_backend()
    backend.build(
        projection_id=projection_id().canonical,
        release_id=RELEASE_ID,
        profile=profile(dropped_semantics=("urn:parquet:evidence",)),
    )
    store_key = parquet_candidate_name(projection_id().canonical)
    assert "evidence" not in store.dataset_names(store_key)
    assert store.read_dataset(store_key, "evidence") is None


def test_preserved_fields_select_dataset_columns() -> None:
    backend, store, _ = make_backend()
    backend.build(
        projection_id=projection_id().canonical,
        release_id=RELEASE_ID,
        profile=profile(
            preserved_fields=(
                "urn:prov:agent",
                "urn:evidence:kind",
                "urn:evidence:record",
            )
        ),
    )
    store_key = parquet_candidate_name(projection_id().canonical)
    provenance = table_from_bytes(store.read_dataset(store_key, "provenance"))
    assert provenance.column_names == ["assertion_id", "agent"]
    evidence_table = table_from_bytes(store.read_dataset(store_key, "evidence"))
    assert evidence_table.column_names == ["evidence_id", "claim_id", "kind", "record_id"]


# --- filters ---------------------------------------------------------------


def test_included_relations_filter() -> None:
    backend, store, _ = make_backend()
    backend.build(
        projection_id=projection_id().canonical,
        release_id=RELEASE_ID,
        profile=profile(included_relations=("interacts_with",)),
    )
    # approved content is filtered; the source assertion is copied verbatim
    rows = stored_rows(store, "relations")
    assert {(str(row["assertion_id"]), str(row["state"])) for row in rows} == {
        ("assertion:a-1", "approved"),
        ("assertion:a-9", "candidate"),
    }


def test_included_entity_types_filter() -> None:
    backend, store, _ = make_backend()
    backend.build(
        projection_id=projection_id().canonical,
        release_id=RELEASE_ID,
        profile=profile(included_entity_types=("gene",)),
    )
    rows = stored_rows(store, "assertions")
    # a-1 dropped (protein object), a-2 kept (gene subject+object), at-1 kept;
    # the source assertion is copied verbatim
    assert {str(row["assertion_id"]) for row in rows} == {
        "assertion:a-2",
        "assertion:a-9",
        "assertion:at-1",
    }


def test_included_assertion_types_filter() -> None:
    backend, store, _ = make_backend()
    backend.build(
        projection_id=projection_id().canonical,
        release_id=RELEASE_ID,
        profile=profile(included_assertion_types=("urn:assertion:RelationshipAssertion",)),
    )
    rows = stored_rows(store, "assertions")
    assert all(row["kind"] == "relationship" for row in rows)
    assert {str(row["assertion_id"]) for row in rows} == {
        "assertion:a-1",
        "assertion:a-2",
        "assertion:a-9",
    }


def test_dropped_predicate_filter() -> None:
    backend, store, _ = make_backend()
    backend.build(
        projection_id=projection_id().canonical,
        release_id=RELEASE_ID,
        profile=profile(dropped_semantics=("regulates",)),
    )
    rows = stored_rows(store, "assertions")
    assert {str(row["assertion_id"]) for row in rows} == {
        "assertion:a-1",
        "assertion:a-9",
        "assertion:at-1",
    }


def test_provenance_and_evidence_pruned_to_survivors() -> None:
    backend, store, _ = make_backend()
    backend.build(
        projection_id=projection_id().canonical,
        release_id=RELEASE_ID,
        profile=profile(dropped_semantics=("regulates", "urn:parquet:evidence")),
    )
    rows = stored_rows(store, "provenance")
    assert {str(row["assertion_id"]) for row in rows} == {
        "assertion:a-1",
        "assertion:a-9",
        "assertion:at-1",
    }


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
    rows = stored_rows(store, "assertions")
    by_id = {str(row["assertion_id"]): str(row["predicate"]) for row in rows}
    assert by_id["assertion:a-1"] == "associates"
    assert by_id["assertion:a-2"] == "regulates"


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
    assert not any(assertion_node("a-2") in entry for entry in report.transformed_records)
    assert backend.validate(projection_id().canonical).passed


# --- unsupported semantics -------------------------------------------------


def test_unsupported_error_blocks_build() -> None:
    backend, _, _ = make_backend()
    with pytest.raises(ParquetUnsupportedSemanticsError):
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
    rows = stored_rows(store, "assertions")
    assert {str(row["assertion_id"]) for row in rows} == {
        "assertion:a-1",
        "assertion:a-9",
        "assertion:at-1",
    }


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
    assert stored_rows(store, "assertions") == expectation_rows()


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
    # protein:P53 is only an object (never a subject), so no entity record
    assert "urn:identifier:protein:P53" not in keys


def test_records_fallback_to_relations_when_assertions_dropped() -> None:
    backend, _, _ = make_backend()
    backend.build(
        projection_id=projection_id().canonical,
        release_id=RELEASE_ID,
        profile=profile(
            dropped_semantics=(
                "urn:parquet:assertions",
                "urn:parquet:provenance",
                "urn:parquet:evidence",
            )
        ),
    )
    records = backend.records(projection_id().canonical)
    keys = {r.key for r in records}
    assert assertion_node("a-1") in keys
    assert assertion_node("at-1") not in keys


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
    assert report.missing_datasets == ()
    assert report.unexpected_datasets == ()
    assert report.missing_rows == ()
    assert report.unexpected_rows == ()
    assert report.transformed_rows == ()
    assert report.row_counts["assertions"] == 4


def _tamper(store: MemoryParquetProjectionStore, projection_value: str) -> None:
    store_key = parquet_candidate_name(f"projection:{projection_value}")
    rows = rows_from_bytes(store.read_dataset(store_key, "assertions"))
    dropped = tuple(row for row in rows if str(row["assertion_id"]) != "assertion:a-2")
    store.write_dataset(
        store_key,
        "assertions",
        parquet_bytes(dropped, DATASET_COLUMNS["assertions"]),
    )


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
    assert report.missing_rows != ()
    assert report.unexpected_rows == ()


def test_reconciliation_is_deterministic() -> None:
    backend, _, _ = make_backend()
    build_candidate(backend)
    first = backend.reconcile(projection_id().canonical)
    second = backend.reconcile(projection_id().canonical)
    assert first == second
    assert first.missing_rows == second.missing_rows


def test_smoke_tests_pass_for_complete_candidate() -> None:
    backend, _, _ = make_backend()
    build_candidate(backend)
    smoke = backend.smoke_test(projection_id().canonical)
    assert smoke.passed, smoke.errors
    assert smoke.datasets_readable
    assert smoke.schema_matches
    assert smoke.row_counts_match
    assert smoke.analytics_queryable


def test_smoke_tests_fail_on_missing_rows() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    store_key = parquet_candidate_name(projection_id().canonical)
    store.write_dataset(store_key, "evidence", parquet_bytes((), DATASET_COLUMNS["evidence"]))
    smoke = backend.smoke_test(projection_id().canonical)
    assert not smoke.passed
    assert not smoke.row_counts_match
    assert "row counts" in " ".join(smoke.errors)


def test_smoke_tests_fail_on_unreadable_dataset() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    store_key = parquet_candidate_name(projection_id().canonical)
    store.write_dataset(store_key, "evidence", b"not parquet")
    smoke = backend.smoke_test(projection_id().canonical)
    assert not smoke.passed
    assert not smoke.datasets_readable
    assert "not readable" in " ".join(smoke.errors)


def test_reconciler_and_smoke_runner_are_standalone() -> None:
    store = MemoryParquetProjectionStore()
    data_source = MemoryParquetDataSource()
    data_source.put(RELEASE_ID, release_dataset())
    builder = ParquetProjectionBuilder(store=store, data_source=data_source)
    builder.build(
        projection_id=projection_id().canonical,
        release_id=RELEASE_ID,
        profile=profile(),
    )
    reconciler = ParquetReconciler(store=store, data_source=data_source)
    report = reconciler.reconcile(
        projection_id=projection_id().canonical,
        release_id=RELEASE_ID,
        profile=profile(),
    )
    assert isinstance(report, ParquetReconciliationReport)
    assert report.reconciled

    expected = ParquetProjectionBuilder(store=store, data_source=data_source).expected(
        RELEASE_ID, profile()
    )
    smoke = ParquetSmokeTestRunner(store=store).run(
        projection_id=projection_id().canonical,
        expected=expected,
    )
    assert smoke.passed


# --- analytics -------------------------------------------------------------


def test_analytical_aggregation_runs_on_real_parquet(tmp_path) -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    store_key = parquet_candidate_name(projection_id().canonical)
    data = store.read_dataset(store_key, "assertions")
    assert data is not None
    path = tmp_path / "assertions.parquet"
    path.write_bytes(data)
    table = pq.read_table(path)
    aggregate = table.group_by(["state"]).aggregate([("assertion_id", "count")])
    counts = {
        str(record["state"]): int(record["assertion_id_count"]) for record in aggregate.to_pylist()
    }
    assert counts == {"approved": 3, "candidate": 1}


# --- atomic switch and rollback --------------------------------------------


def test_activation_is_atomic_and_retains_previous() -> None:
    backend, store, _ = make_backend()
    first = "projection:parquet-001"
    second = "projection:parquet-002"
    backend.build(projection_id=first, release_id=RELEASE_ID, profile=profile())
    assert backend.validate(first).passed
    backend.activate(first)
    first_key = parquet_candidate_name(first)
    assert store.active_projection() == first_key

    backend.build(projection_id=second, release_id=RELEASE_ID, profile=profile())
    assert backend.validate(second).passed
    backend.activate(second)
    second_key = parquet_candidate_name(second)
    assert store.active_projection() == second_key
    assert store.has_projection(first_key)


def test_rollback_restores_previous_without_rebuild() -> None:
    backend, store, _ = make_backend()
    first = "projection:parquet-001"
    second = "projection:parquet-002"
    backend.build(projection_id=first, release_id=RELEASE_ID, profile=profile())
    backend.activate(first)
    backend.build(projection_id=second, release_id=RELEASE_ID, profile=profile())
    backend.activate(second)

    backend.rollback(second)
    assert store.active_projection() is None
    assert store.has_projection(parquet_candidate_name(first))

    backend.activate(first)
    assert store.active_projection() == parquet_candidate_name(first)


def test_destroy_removes_content() -> None:
    backend, store, _ = make_backend()
    build_candidate(backend)
    store_key = parquet_candidate_name(projection_id().canonical)
    assert store.has_projection(store_key)
    backend.destroy(projection_id().canonical)
    assert not store.has_projection(store_key)
    assert store.dataset_row_count(store_key, "assertions") == 0


def test_unknown_projection_raises() -> None:
    backend, _, _ = make_backend()
    with pytest.raises(UnknownParquetProjectionError):
        backend.validate("projection:ghost")


# --- Core integration ------------------------------------------------------


def test_registered_through_projection_registry() -> None:
    backend, _, _ = make_backend()
    registry = ProjectionRegistry()
    registry.register(backend)
    assert registry.has("parquet")
    assert registry.get("parquet") is backend
    assert isinstance(backend, ProjectionBackend)


def test_core_drives_parquet_lifecycle_independently() -> None:
    backend, _, data_source = make_backend()
    registry = ProjectionRegistry()
    registry.register(backend)
    manager = ProjectionManager(registry=registry)

    projection = manager.create_projection(
        projection_id=projection_id(),
        profile=profile(),
        backend_id="parquet",
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


def test_core_rollback_switches_back_to_retained_parquet() -> None:
    backend, _, data_source = make_backend()
    registry = ProjectionRegistry()
    registry.register(backend)
    manager = ProjectionManager(registry=registry)

    def activate(value: str) -> Identifier:
        p = manager.create_projection(
            projection_id=ident("projection", value),
            profile=profile(),
            backend_id="parquet",
            release_id=RELEASE_ID,
        )
        p = manager.build_candidate(p.id)
        p = manager.validate_candidate(p.id)
        release_dataset_for_compare = data_source.get(RELEASE_ID)
        assert release_dataset_for_compare is not None
        p = manager.reconcile_candidate(p.id, release_dataset_for_compare)
        return manager.activate_candidate(p.id).id

    first = activate("parquet-101")
    second = activate("parquet-102")

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
        backend_id="parquet",
        release_id=RELEASE_ID,
    )
    projection = manager.build_candidate(projection.id)
    assert projection.status is ProjectionStatus.VALIDATING

    # Corrupt the candidate before validation: drop the assertions dataset.
    store_key = parquet_candidate_name(projection.id.canonical)
    store.write_dataset(store_key, "assertions", parquet_bytes((), DATASET_COLUMNS["assertions"]))
    projection = manager.validate_candidate(projection.id)
    assert projection.status is ProjectionStatus.FAILED
    with pytest.raises(InvalidProjectionTransitionError):
        manager.activate_candidate(projection.id)
