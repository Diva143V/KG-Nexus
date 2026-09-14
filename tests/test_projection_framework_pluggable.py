"""Phase 13: Pluggable Projection Framework tests.

Exercises the backend-independent projection lifecycle in ``core.projection``
using a fake in-memory backend. No real downstream projection (graph
database, vector store, search engine, columnar file) is involved: the point
of Phase 13 is that Core manages projections without knowing which backend it
is talking to.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.projection import (
    ActiveProjectionError,
    DuplicateBackendError,
    FieldTransformation,
    InvalidProjectionTransitionError,
    NoActiveProjectionError,
    NoRetainedProjectionError,
    ProjectedRecord,
    Projection,
    ProjectionBackend,
    ProjectionManager,
    ProjectionProfile,
    ProjectionReconciler,
    ProjectionRegistry,
    ProjectionResult,
    ProjectionStatus,
    ProjectionValidationResult,
    ReconciliationStrategy,
    TransformationKind,
    UnknownBackendError,
    UnknownProjectionError,
    UnsupportedBehavior,
)
from core.projection.reconciliation import (
    APPROVED_GRAPH,
    ASN_OBJECT,
    ASN_PREDICATE,
    ASN_STATE,
    ASN_SUBJECT,
)
from core.rdf.graph import NamedGraph, RDFDataset
from core.rdf.terms import Triple, iri, string_literal
from tests.helpers import ident

RELEASE_ID = "release:r1"


class FakeProjectionBackend:
    """In-memory ProjectionBackend for tests."""

    def __init__(self, backend_id: str = "fake-memory") -> None:
        self.backend_id = backend_id
        self._validation_results: dict[str, ProjectionValidationResult] = {}
        self._records: tuple[ProjectedRecord, ...] | None = None
        self.activated: list[str] = []
        self.rolled_back: list[str] = []
        self.destroyed: list[str] = []
        self.build_error: Exception | None = None
        self.validate_error: Exception | None = None
        self.records_error: Exception | None = None
        self.activate_error: Exception | None = None
        self.rollback_error: Exception | None = None

    def build(
        self,
        projection_id: str,
        release_id: str,
        profile: ProjectionProfile,
    ) -> ProjectionResult:
        if self.build_error is not None:
            raise self.build_error
        return ProjectionResult(
            projection_id=projection_id,
            backend_id=self.backend_id,
            message="built",
            record_count=0,
        )

    def validate(self, projection_id: str) -> ProjectionValidationResult:
        if self.validate_error is not None:
            raise self.validate_error
        return self._validation_results.get(
            projection_id,
            ProjectionValidationResult(projection_id=projection_id, passed=True),
        )

    def records(self, projection_id: str) -> tuple[ProjectedRecord, ...]:
        if self.records_error is not None:
            raise self.records_error
        return self._records or ()

    def activate(self, projection_id: str) -> None:
        if self.activate_error is not None:
            raise self.activate_error
        self.activated.append(projection_id)

    def rollback(self, projection_id: str) -> None:
        if self.rollback_error is not None:
            raise self.rollback_error
        self.rolled_back.append(projection_id)

    def destroy(self, projection_id: str) -> None:
        self.destroyed.append(projection_id)

    def set_validation(self, result: ProjectionValidationResult) -> None:
        self._validation_results[result.projection_id] = result

    def provide_records(self, records: tuple[ProjectedRecord, ...]) -> None:
        self._records = records


def profile(
    *,
    strategy: ReconciliationStrategy = ReconciliationStrategy.REBUILD,
    unsupported: tuple[str, ...] = (),
) -> ProjectionProfile:
    return ProjectionProfile(
        profile_id="entity-graph",
        profile_version="1",
        source_release_type="approved",
        preserved_fields=("urn:label",),
        reconciliation_strategy=strategy,
        unsupported_semantics=unsupported,
    )


def approved_dataset() -> RDFDataset:
    return RDFDataset(
        graphs=(
            NamedGraph(
                name=APPROVED_GRAPH,
                triples=(
                    *_relationship(
                        "urn:assertion:a1",
                        "gene:EGFR",
                        "urn:predicate:interacts_with",
                        "protein:P53",
                    ),
                    *_relationship(
                        "urn:assertion:a2",
                        "protein:P53",
                        "urn:predicate:expresses",
                        "gene:MYC",
                    ),
                ),
            ),
        )
    )


def _relationship(
    assertion_id: str,
    subject: str,
    predicate: str,
    obj: str,
) -> tuple[Triple, ...]:
    node = iri(assertion_id)
    return (
        Triple(subject=node, predicate=iri(ASN_SUBJECT), object=iri(f"urn:identifier:{subject}")),
        Triple(subject=node, predicate=iri(ASN_PREDICATE), object=string_literal(predicate)),
        Triple(subject=node, predicate=iri(ASN_OBJECT), object=iri(f"urn:identifier:{obj}")),
        Triple(subject=node, predicate=iri(ASN_STATE), object=string_literal("approved")),
    )


def reconciler() -> ProjectionReconciler:
    return ProjectionReconciler()


def make_manager() -> tuple[ProjectionManager, FakeProjectionBackend]:
    registry = ProjectionRegistry()
    backend = FakeProjectionBackend()
    registry.register(backend)
    return ProjectionManager(registry=registry), backend


def new_projection(
    manager: ProjectionManager,
    value: str,
) -> Projection:
    return manager.create_projection(
        projection_id=ident("projection", value),
        profile=profile(),
        backend_id="fake-memory",
        release_id=RELEASE_ID,
    )


def to_ready(
    manager: ProjectionManager,
    backend: FakeProjectionBackend,
    projection: Projection,
    *,
    records: tuple[ProjectedRecord, ...] | None = None,
) -> Projection:
    projection = manager.build_candidate(projection.id)
    projection = manager.validate_candidate(projection.id)
    backend.provide_records(records or reconciler().authoritative_records(approved_dataset()))
    return manager.reconcile_candidate(projection.id, approved_dataset())


def to_active(
    manager: ProjectionManager,
    backend: FakeProjectionBackend,
    projection: Projection,
) -> Projection:
    ready = to_ready(manager, backend, projection)
    assert ready.status is ProjectionStatus.READY
    return manager.activate_candidate(ready.id)


# --- registry --------------------------------------------------------------


def test_register_and_resolve_backend() -> None:
    registry = ProjectionRegistry()
    backend = FakeProjectionBackend("memory")
    registry.register(backend)
    assert registry.has("memory")
    assert registry.get("memory") is backend
    assert registry.create("memory") is backend
    assert registry.list_backends() == ("memory",)


def test_duplicate_backend_registration_raises() -> None:
    registry = ProjectionRegistry()
    registry.register(FakeProjectionBackend("memory"))
    with pytest.raises(DuplicateBackendError):
        registry.register(FakeProjectionBackend("memory"))


def test_unknown_backend_raises() -> None:
    registry = ProjectionRegistry()
    with pytest.raises(UnknownBackendError):
        registry.get("missing")


def test_register_rejects_non_conforming_backend() -> None:
    registry = ProjectionRegistry()
    with pytest.raises(TypeError):
        registry.register("not-a-backend")  # type: ignore[arg-type]


def test_registered_backend_satisfies_protocol() -> None:
    assert isinstance(FakeProjectionBackend(), ProjectionBackend)


# --- profile ---------------------------------------------------------------


def test_profile_rejects_overlapping_declarations() -> None:
    with pytest.raises(ValidationError):
        ProjectionProfile(
            profile_id="x",
            profile_version="1",
            preserved_fields=("urn:a",),
            transformations=(
                FieldTransformation(
                    name="t",
                    source="urn:a",
                    target="a",
                    kind=TransformationKind.NODE,
                ),
            ),
        )


def test_profile_records_unsupported_semantics() -> None:
    prof = profile(unsupported=("urn:opaque",))
    prof = prof.model_copy(update={"unsupported_behavior": UnsupportedBehavior.SKIP})
    assert prof.unsupported_semantics == ("urn:opaque",)
    assert prof.unsupported_behavior is UnsupportedBehavior.SKIP


def test_profile_defaults() -> None:
    prof = profile()
    assert prof.reconciliation_strategy is ReconciliationStrategy.REBUILD
    assert prof.deterministic_ordering
    assert prof.unsupported_behavior is UnsupportedBehavior.ERROR


# --- lifecycle happy path --------------------------------------------------


def test_full_lifecycle_happy_path() -> None:
    manager, backend = make_manager()
    projection = new_projection(manager, "p1")

    assert projection.status is ProjectionStatus.BUILDING
    assert manager.active_projection() is None
    assert manager.candidate_projection() is not None

    projection = manager.build_candidate(projection.id)
    assert projection.status is ProjectionStatus.VALIDATING
    assert projection.build_result is not None
    assert projection.build_result.projection_id == "projection:p1"

    projection = manager.validate_candidate(projection.id)
    assert projection.status is ProjectionStatus.RECONCILING
    assert projection.validation_result is not None
    assert projection.validation_result.passed

    backend.provide_records(reconciler().authoritative_records(approved_dataset()))
    projection = manager.reconcile_candidate(projection.id, approved_dataset())
    assert projection.status is ProjectionStatus.READY
    assert projection.reconciliation_result is not None
    assert projection.reconciliation_result.reconciled

    projection = manager.activate_candidate(projection.id)
    assert projection.status is ProjectionStatus.ACTIVE
    assert projection.activated_at is not None
    active = manager.active_projection()
    assert active is not None
    assert active.id == projection.id
    assert manager.candidate_projection() is None
    assert backend.activated == ["projection:p1"]


def test_transitions_are_recorded() -> None:
    manager, _ = make_manager()
    projection = new_projection(manager, "p1")
    projection = manager.build_candidate(projection.id)
    projection = manager.validate_candidate(projection.id)
    assert [t.to_status for t in projection.transitions] == [
        ProjectionStatus.VALIDATING,
        ProjectionStatus.RECONCILING,
    ]


# --- invalid transitions ---------------------------------------------------


def test_invalid_transition_raises() -> None:
    manager, _ = make_manager()
    projection = new_projection(manager, "p1")
    with pytest.raises(InvalidProjectionTransitionError):
        manager.validate_candidate(projection.id)
    with pytest.raises(InvalidProjectionTransitionError):
        manager.activate_candidate(projection.id)


def test_activate_requires_ready() -> None:
    manager, _ = make_manager()
    projection = new_projection(manager, "p1")
    with pytest.raises(InvalidProjectionTransitionError):
        manager.activate_candidate(projection.id)


# --- build / validation / reconciliation failures --------------------------


def test_build_failure_marks_failed() -> None:
    manager, backend = make_manager()
    backend.build_error = ValueError("boom")
    projection = manager.build_candidate(new_projection(manager, "p1").id)
    assert projection.status is ProjectionStatus.FAILED
    assert projection.reasons == ("build failed: boom",)
    assert manager.candidate_projection() is None


def test_validation_failure_marks_failed() -> None:
    manager, backend = make_manager()
    projection = new_projection(manager, "p1")
    projection = manager.build_candidate(projection.id)
    backend.set_validation(
        ProjectionValidationResult(
            projection_id="projection:p1",
            passed=False,
            errors=("schema mismatch",),
        )
    )
    projection = manager.validate_candidate(projection.id)
    assert projection.status is ProjectionStatus.FAILED
    assert projection.validation_result is not None
    assert not projection.validation_result.passed
    assert "schema mismatch" in projection.reasons[0]


def test_validation_backend_error_marks_failed() -> None:
    manager, backend = make_manager()
    projection = new_projection(manager, "p1")
    projection = manager.build_candidate(projection.id)
    backend.validate_error = RuntimeError("down")
    projection = manager.validate_candidate(projection.id)
    assert projection.status is ProjectionStatus.FAILED
    assert "validation failed" in projection.reasons[0]


def test_reconciliation_failure_marks_failed() -> None:
    manager, backend = make_manager()
    projection = new_projection(manager, "p1")
    projection = manager.build_candidate(projection.id)
    projection = manager.validate_candidate(projection.id)
    backend.provide_records((ProjectedRecord(kind="entity", key="wrong", digest="a" * 64),))
    projection = manager.reconcile_candidate(projection.id, approved_dataset())
    assert projection.status is ProjectionStatus.FAILED
    result = projection.reconciliation_result
    assert result is not None
    assert not result.reconciled
    assert result.report.unexpected_records == ("entity:wrong",)
    assert "missing=6" in projection.reasons[0]
    assert "unexpected=1" in projection.reasons[0]


def test_reconciliation_reports_transformed_records() -> None:
    manager, backend = make_manager()
    projection = new_projection(manager, "p1")
    projection = manager.build_candidate(projection.id)
    projection = manager.validate_candidate(projection.id)
    authoritative = reconciler().authoritative_records(approved_dataset())
    first = authoritative[0]
    altered = tuple(
        ProjectedRecord(kind=first.kind, key=first.key, digest="b" * 64)
        if record is first
        else record
        for record in authoritative
    )
    backend.provide_records(altered)
    projection = manager.reconcile_candidate(projection.id, approved_dataset())
    assert projection.status is ProjectionStatus.FAILED
    result = projection.reconciliation_result
    assert result is not None
    assert result.report.transformed_records == (f"{first.kind}:{first.key}",)


# --- reconciliation determinism and strategies -----------------------------


def test_reconciliation_is_order_independent() -> None:
    authoritative = reconciler().authoritative_records(approved_dataset())
    reversed_records = tuple(reversed(authoritative))
    report = reconciler().compare(
        strategy=ReconciliationStrategy.REBUILD,
        authoritative_records=authoritative,
        projected_records=reversed_records,
    )
    assert report.reconciled
    assert report.assertion_count == 2
    assert report.entity_count == 2
    assert report.relation_count == 2
    assert (
        report.assertion_digest
        == reconciler()
        .compare(
            strategy=ReconciliationStrategy.REBUILD,
            authoritative_records=authoritative,
            projected_records=authoritative,
        )
        .assertion_digest
    )


def test_reconciliation_digest_strategy() -> None:
    manager, backend = make_manager()
    projection = manager.create_projection(
        projection_id=ident("projection", "p1"),
        profile=profile(strategy=ReconciliationStrategy.DIGEST),
        backend_id="fake-memory",
        release_id=RELEASE_ID,
    )
    projection = manager.build_candidate(projection.id)
    projection = manager.validate_candidate(projection.id)
    authoritative = reconciler().authoritative_records(approved_dataset())
    first = authoritative[0]
    altered = tuple(
        ProjectedRecord(kind=first.kind, key=first.key, digest="c" * 64)
        if record is first
        else record
        for record in authoritative
    )
    backend.provide_records(altered)
    projection = manager.reconcile_candidate(projection.id, approved_dataset())
    assert projection.status is ProjectionStatus.FAILED
    result = projection.reconciliation_result
    assert result is not None
    assert result.report.transformed_records == ("assertion-digest",)


# --- activation / rollback / quarantine / destroy --------------------------


def test_activation_retains_previous_active() -> None:
    manager, backend = make_manager()
    first = to_active(manager, backend, new_projection(manager, "p1"))
    second = to_active(manager, backend, new_projection(manager, "p2"))

    retained = manager.get_projection(first.id)
    assert retained is not None
    assert retained.status is ProjectionStatus.RETAINED_FOR_ROLLBACK
    assert retained.retained_at is not None

    active = manager.active_projection()
    assert active is not None
    assert active.id == second.id
    assert backend.activated == ["projection:p1", "projection:p2"]


def test_rollback_restores_retained_projection() -> None:
    manager, backend = make_manager()
    first = to_active(manager, backend, new_projection(manager, "p1"))
    second = to_active(manager, backend, new_projection(manager, "p2"))

    restored = manager.rollback(second.id)
    assert restored.id == first.id
    assert restored.status is ProjectionStatus.ACTIVE

    rolled = manager.get_projection(second.id)
    assert rolled is not None
    assert rolled.status is ProjectionStatus.RETAINED_FOR_ROLLBACK
    assert backend.rolled_back == ["projection:p2"]

    active = manager.active_projection()
    assert active is not None
    assert active.id == first.id


def test_rollback_without_retained_raises() -> None:
    manager, backend = make_manager()
    first = to_active(manager, backend, new_projection(manager, "p1"))
    with pytest.raises(NoRetainedProjectionError):
        manager.rollback(first.id)


def test_rollback_requires_active_projection() -> None:
    manager, _ = make_manager()
    projection = new_projection(manager, "p1")
    with pytest.raises(NoActiveProjectionError):
        manager.rollback(projection.id)


def test_quarantine_is_terminal() -> None:
    manager, _ = make_manager()
    projection = new_projection(manager, "p1")
    quarantined = manager.quarantine(projection.id, reason="bad")
    assert quarantined.status is ProjectionStatus.QUARANTINED
    assert quarantined.reasons == ("bad",)
    with pytest.raises(InvalidProjectionTransitionError):
        manager.fail(projection.id, reason="x")


def test_fail_marks_projection_failed() -> None:
    manager, _ = make_manager()
    projection = new_projection(manager, "p1")
    failed = manager.fail(projection.id, reason="manual")
    assert failed.status is ProjectionStatus.FAILED
    assert failed.reasons == ("manual",)


def test_destroy_removes_projection() -> None:
    manager, backend = make_manager()
    projection = new_projection(manager, "p1")
    projection = manager.build_candidate(projection.id)
    manager.destroy(projection.id)
    assert manager.get_projection(projection.id) is None
    assert backend.destroyed == ["projection:p1"]


def test_cannot_destroy_active_projection() -> None:
    manager, backend = make_manager()
    projection = to_active(manager, backend, new_projection(manager, "p1"))
    with pytest.raises(ActiveProjectionError):
        manager.destroy(projection.id)


# --- create / backend resolution -------------------------------------------


def test_create_projection_requires_registered_backend() -> None:
    manager = ProjectionManager(registry=ProjectionRegistry())
    with pytest.raises(UnknownBackendError):
        manager.create_projection(
            projection_id=ident("projection", "p1"),
            profile=profile(),
            backend_id="missing",
            release_id=RELEASE_ID,
        )


def test_duplicate_projection_raises() -> None:
    manager, _ = make_manager()
    new_projection(manager, "p1")
    with pytest.raises(ValueError):
        new_projection(manager, "p1")


def test_unknown_projection_raises() -> None:
    manager, _ = make_manager()
    with pytest.raises(UnknownProjectionError):
        manager.build_candidate(ident("projection", "ghost"))


def test_candidate_projection_returns_latest() -> None:
    manager, _ = make_manager()
    new_projection(manager, "p1")
    candidate = manager.candidate_projection()
    assert candidate is not None
    assert candidate.id == ident("projection", "p1")
