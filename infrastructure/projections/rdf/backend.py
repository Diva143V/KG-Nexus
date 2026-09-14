"""RDFProjectionBackend: project an RDF release into another RDF deployment.

RDF is authoritative. This backend redeploys a release's RDF dataset as a
downstream RDF projection — it is never a second semantic authority. It
implements the Phase 13 ``ProjectionBackend`` contract and is registered
through ``ProjectionRegistry``; Core never imports it and never knows its
store.

Lifecycle within the backend:

    BUILD (candidate) -> VALIDATE -> RECONCILE -> SMOKE TEST -> READY

Activation is atomic: the candidate is promoted to active while the
previous active projection is retained for rollback (its content is never
deleted before activation).
"""

from __future__ import annotations

from core.projection.backend import ProjectionBackend
from core.projection.profile import ProjectionProfile
from core.projection.reconciliation import ProjectedRecord, ProjectionReconciler
from core.projection.result import ProjectionResult, ProjectionValidationResult
from core.rdf.graph import NamedGraphCategory, graph_name
from core.rdf.terms import Triple
from infrastructure.projections.rdf.builder import (
    RDFDataSource,
    RDFProjectionBuilder,
)
from infrastructure.projections.rdf.errors import UnknownRDFProjectionError
from infrastructure.projections.rdf.reconciler import (
    RDFReconciler,
    RDFReconciliationReport,
)
from infrastructure.projections.rdf.smoke_tests import (
    RDFSmokeTestResult,
    RDFSmokeTestRunner,
)
from infrastructure.projections.rdf.store import (
    RDFProjectionStore,
    rdf_candidate_name,
)
from infrastructure.projections.rdf.terms import canonical_triple, term_key


class RDFProjectionBackend:
    """Concrete ProjectionBackend that redeploys RDF releases as RDF.

    ``data_source`` supplies the authoritative RDF release the backend
    projects. ``store`` is where a real triplestore adapter plugs in; tests
    inject an in-memory store.
    """

    def __init__(
        self,
        *,
        store: RDFProjectionStore,
        data_source: RDFDataSource,
        backend_id: str = "rdf",
        builder: RDFProjectionBuilder | None = None,
        reconciler: RDFReconciler | None = None,
        smoke_tests: RDFSmokeTestRunner | None = None,
    ) -> None:
        self.backend_id = backend_id
        self._store = store
        self._data_source = data_source
        self._builder = builder or RDFProjectionBuilder(
            store=store,
            data_source=data_source,
        )
        self._reconciler = reconciler or RDFReconciler(
            store=store,
            data_source=data_source,
        )
        self._smoke_tests = smoke_tests or RDFSmokeTestRunner(store=store)
        self._projects: dict[str, tuple[str, ProjectionProfile]] = {}

    def build(
        self,
        projection_id: str,
        release_id: str,
        profile: ProjectionProfile,
    ) -> ProjectionResult:
        """Build a candidate projection from the authoritative RDF release."""
        record_count = self._builder.build(
            projection_id=projection_id,
            release_id=release_id,
            profile=profile,
        )
        self._projects[projection_id] = (release_id, profile)
        return ProjectionResult(
            projection_id=projection_id,
            backend_id=self.backend_id,
            message="rdf projection built",
            record_count=record_count,
        )

    def validate(
        self,
        projection_id: str,
    ) -> ProjectionValidationResult:
        """Validate the candidate: structure, reconciliation, and smoke tests.

        A candidate is only valid if it matches the policy-derived expected
        dataset exactly and passes smoke tests. Failed candidates are
        reported, never activated.
        """
        release_id, profile = self._require(projection_id)
        store_key = rdf_candidate_name(projection_id)
        if not self._store.has_projection(store_key):
            return ProjectionValidationResult(
                projection_id=projection_id,
                passed=False,
                errors=("no candidate projection",),
            )

        errors: list[str] = []
        structural = self._structural_errors(projection_id, release_id, profile)
        errors.extend(structural)

        report = self._reconciler.reconcile(
            projection_id=projection_id,
            release_id=release_id,
            profile=profile,
        )
        if not report.reconciled:
            errors.append(f"reconciliation: {self._report_summary(report)}")

        expected = self._builder.expected(release_id, profile)
        smoke = self._smoke_tests.run(projection_id=projection_id, expected=expected)
        if not smoke.passed:
            errors.append(f"smoke tests: {'; '.join(smoke.errors)}")

        return ProjectionValidationResult(
            projection_id=projection_id,
            passed=not errors,
            errors=tuple(errors),
        )

    def records(
        self,
        projection_id: str,
    ) -> tuple[ProjectedRecord, ...]:
        """Backend-neutral records for the candidate, in Core's canonical form.

        RDF is the projection's own format, so records are derived from the
        projected approved graph with Core's authoritative derivation — a
        faithful full copy is therefore indistinguishable from the release.
        """
        self._require(projection_id)
        dataset = self._store.read_dataset(rdf_candidate_name(projection_id))
        if dataset is None:
            return ()
        return ProjectionReconciler().authoritative_records(dataset)

    def activate(
        self,
        projection_id: str,
    ) -> None:
        """Atomically promote the candidate to active."""
        self._require(projection_id)
        self._store.activate(rdf_candidate_name(projection_id))

    def rollback(
        self,
        projection_id: str,
    ) -> None:
        """Roll back the projection; retained content stays untouched."""
        self._require(projection_id)
        self._store.rollback(rdf_candidate_name(projection_id))

    def destroy(
        self,
        projection_id: str,
    ) -> None:
        """Destroy the projection's content, if present."""
        self._store.delete_projection(rdf_candidate_name(projection_id))
        self._projects.pop(projection_id, None)

    def reconcile(
        self,
        projection_id: str,
    ) -> RDFReconciliationReport:
        """RDF-specific reconciliation report for the candidate."""
        release_id, profile = self._require(projection_id)
        return self._reconciler.reconcile(
            projection_id=projection_id,
            release_id=release_id,
            profile=profile,
        )

    def smoke_test(
        self,
        projection_id: str,
    ) -> RDFSmokeTestResult:
        """Smoke test report for the candidate."""
        release_id, profile = self._require(projection_id)
        expected = self._builder.expected(release_id, profile)
        return self._smoke_tests.run(projection_id=projection_id, expected=expected)

    def _structural_errors(
        self,
        projection_id: str,
        release_id: str,
        profile: ProjectionProfile,
    ) -> list[str]:
        expected = self._builder.derive(release_id, profile)
        store_key = rdf_candidate_name(projection_id)
        errors: list[str] = []

        for graph in expected.graphs:
            if self._store.graph(store_key, graph.name) is None:
                errors.append(f"graph missing: {graph.name}")

        actual = self._store.read_dataset(store_key)
        if actual is None:
            return errors
        expected_approved = expected.graph(graph_name(NamedGraphCategory.APPROVED_ASSERTION))
        actual_approved = actual.graph(graph_name(NamedGraphCategory.APPROVED_ASSERTION))
        if expected_approved is not None and actual_approved is not None:
            errors.extend(
                self._assertion_errors(
                    expected_approved.name,
                    expected_approved.triples,
                    actual_approved.triples,
                )
            )
        return errors

    @staticmethod
    def _assertion_errors(
        graph_name: str,
        expected: tuple[Triple, ...],
        actual: tuple[Triple, ...],
    ) -> list[str]:
        errors: list[str] = []
        expected_by_subject: dict[str, set[str]] = {}
        for triple in expected:
            expected_by_subject.setdefault(term_key(triple.subject), set()).add(
                canonical_triple(graph_name, triple)
            )
        actual_by_subject: dict[str, set[str]] = {}
        for triple in actual:
            actual_by_subject.setdefault(term_key(triple.subject), set()).add(
                canonical_triple(graph_name, triple)
            )
        for subject in sorted(expected_by_subject):
            if subject not in actual_by_subject:
                errors.append(f"assertion missing: {subject}")
                continue
            missing = sorted(expected_by_subject[subject] - actual_by_subject[subject])
            for entry in missing:
                errors.append(f"assertion triples missing for {subject}: {entry}")
        return errors

    def _require(self, projection_id: str) -> tuple[str, ProjectionProfile]:
        entry = self._projects.get(projection_id)
        if entry is None:
            raise UnknownRDFProjectionError(projection_id)
        return entry

    @staticmethod
    def _report_summary(report: RDFReconciliationReport) -> str:
        parts = [
            f"missing_graphs={len(report.missing_graphs)}",
            f"unexpected_graphs={len(report.unexpected_graphs)}",
            f"missing_triples={len(report.missing_triples)}",
            f"unexpected_triples={len(report.unexpected_triples)}",
            f"transformed_triples={len(report.transformed_triples)}",
        ]
        return ", ".join(parts)


def conforms_to_backend(backend: object) -> bool:
    """True when ``backend`` implements the ProjectionBackend contract."""
    return isinstance(backend, ProjectionBackend)
