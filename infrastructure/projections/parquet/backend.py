"""ParquetProjectionBackend: project an RDF release into analytical datasets.

RDF is authoritative. This backend materializes a release's approved and
source content into deterministic Parquet datasets for large-scale analytics —
DuckDB or any columnar engine can read the files directly. Parquet is never
authoritative: no analytical database is written by Core, records reported to
Core are derived from the materialized rows, and the projection's content is
verified against the policy-derived expectation before it can become active.
It implements the Phase 13 ``ProjectionBackend`` contract and is registered
through ``ProjectionRegistry``; Core never imports it and never knows its
store.

Lifecycle within the backend:

    BUILD (candidate) -> VALIDATE -> RECONCILE -> SMOKE TEST -> READY

Activation is atomic: the candidate is promoted to active while the previous
active projection is retained for rollback (its content is never deleted
before activation).
"""

from __future__ import annotations

from core.projection.backend import ProjectionBackend
from core.projection.profile import ProjectionProfile
from core.projection.reconciliation import ProjectedRecord, ProjectionReconciler
from core.projection.result import ProjectionResult, ProjectionValidationResult
from core.rdf.graph import NamedGraph, NamedGraphCategory, RDFDataset, graph_name
from core.rdf.terms import Triple, iri, string_literal
from core.rdf.writer import ASN_OBJECT, ASN_PREDICATE, ASN_SUBJECT, identifier_iri
from infrastructure.projections.parquet.builder import (
    ParquetDataSource,
    ParquetProjectionBuilder,
)
from infrastructure.projections.parquet.errors import UnknownParquetProjectionError
from infrastructure.projections.parquet.reconciler import (
    ParquetReconciler,
    ParquetReconciliationReport,
)
from infrastructure.projections.parquet.smoke_tests import (
    ParquetSmokeTestResult,
    ParquetSmokeTestRunner,
)
from infrastructure.projections.parquet.store import (
    ParquetProjectionStore,
    parquet_candidate_name,
)
from infrastructure.projections.parquet.writer import (
    rows_from_bytes,
    try_table_from_bytes,
)


class ParquetProjectionBackend:
    """Concrete ProjectionBackend that materializes analytical datasets.

    ``data_source`` supplies the authoritative RDF release the backend
    projects. ``store`` is where a real analytical store (a filesystem of
    Parquet files, a query engine) plugs in; tests inject an in-memory store.
    """

    def __init__(
        self,
        *,
        store: ParquetProjectionStore,
        data_source: ParquetDataSource,
        backend_id: str = "parquet",
        builder: ParquetProjectionBuilder | None = None,
        reconciler: ParquetReconciler | None = None,
        smoke_tests: ParquetSmokeTestRunner | None = None,
    ) -> None:
        self.backend_id = backend_id
        self._store = store
        self._data_source = data_source
        self._builder = builder or ParquetProjectionBuilder(
            store=store,
            data_source=data_source,
        )
        self._reconciler = reconciler or ParquetReconciler(
            store=store,
            data_source=data_source,
        )
        self._smoke_tests = smoke_tests or ParquetSmokeTestRunner(store=store)
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
            message="parquet projection built",
            record_count=record_count,
        )

    def validate(
        self,
        projection_id: str,
    ) -> ProjectionValidationResult:
        """Validate the candidate: structure, reconciliation, and smoke tests.

        A candidate is only valid if it matches the policy-derived expected
        datasets exactly and passes smoke tests. Failed candidates are
        reported, never activated.
        """
        release_id, profile = self._require(projection_id)
        store_key = parquet_candidate_name(projection_id)
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

        Records are derived from the materialized approved rows (rebuilt into
        the RDF assertion form Core's reconciler understands), so they reflect
        exactly what is stored — a faithful full copy is indistinguishable
        from the release, and declared transformations surface as Core-level
        "transformed" records.
        """
        self._require(projection_id)
        store_key = parquet_candidate_name(projection_id)
        rows = self._approved_rows(store_key)
        if not rows:
            return ()
        triples: list[Triple] = []
        for row in rows:
            node = iri(f"urn:assertion:{row['assertion_id']}")
            triples.append(
                Triple(
                    subject=node,
                    predicate=iri(ASN_SUBJECT),
                    object=identifier_iri(str(row["subject"])),
                )
            )
            triples.append(
                Triple(
                    subject=node,
                    predicate=iri(ASN_PREDICATE),
                    object=string_literal(str(row["predicate"])),
                )
            )
            object_id = row.get("object")
            if object_id is not None:
                triples.append(
                    Triple(
                        subject=node,
                        predicate=iri(ASN_OBJECT),
                        object=identifier_iri(str(object_id)),
                    )
                )
        dataset = RDFDataset(
            graphs=(
                NamedGraph(
                    name=graph_name(NamedGraphCategory.APPROVED_ASSERTION),
                    triples=tuple(triples),
                ),
            )
        )
        return ProjectionReconciler().authoritative_records(dataset)

    def activate(
        self,
        projection_id: str,
    ) -> None:
        """Atomically promote the candidate to active."""
        self._require(projection_id)
        self._store.activate(parquet_candidate_name(projection_id))

    def rollback(
        self,
        projection_id: str,
    ) -> None:
        """Roll back the projection; retained content stays untouched."""
        self._require(projection_id)
        self._store.rollback(parquet_candidate_name(projection_id))

    def destroy(
        self,
        projection_id: str,
    ) -> None:
        """Destroy the projection's content, if present."""
        self._store.delete_projection(parquet_candidate_name(projection_id))
        self._projects.pop(projection_id, None)

    def reconcile(
        self,
        projection_id: str,
    ) -> ParquetReconciliationReport:
        """Parquet-specific reconciliation report for the candidate."""
        release_id, profile = self._require(projection_id)
        return self._reconciler.reconcile(
            projection_id=projection_id,
            release_id=release_id,
            profile=profile,
        )

    def smoke_test(
        self,
        projection_id: str,
    ) -> ParquetSmokeTestResult:
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
        store_key = parquet_candidate_name(projection_id)
        errors: list[str] = []
        for name in expected.dataset_names:
            data = self._store.read_dataset(store_key, name)
            if data is None:
                errors.append(f"dataset missing: {name}")
                continue
            table = try_table_from_bytes(data)
            if table is None:
                errors.append(f"dataset unreadable: {name}")
                continue
            if table.column_names != list(expected.columns[name]):
                errors.append(f"dataset schema mismatch: {name}")
            if table.num_rows != len(expected.datasets[name]):
                errors.append(f"dataset row count mismatch: {name}")
        return errors

    def _approved_rows(
        self,
        store_key: str,
    ) -> tuple[dict[str, object], ...]:
        for name in ("assertions", "relations"):
            data = self._store.read_dataset(store_key, name)
            if data is None:
                continue
            rows = rows_from_bytes(data)
            return tuple(row for row in rows if str(row.get("state")) == "approved")
        return ()

    def _require(self, projection_id: str) -> tuple[str, ProjectionProfile]:
        entry = self._projects.get(projection_id)
        if entry is None:
            raise UnknownParquetProjectionError(projection_id)
        return entry

    @staticmethod
    def _report_summary(report: ParquetReconciliationReport) -> str:
        parts = [
            f"missing_datasets={len(report.missing_datasets)}",
            f"unexpected_datasets={len(report.unexpected_datasets)}",
            f"missing_rows={len(report.missing_rows)}",
            f"unexpected_rows={len(report.unexpected_rows)}",
            f"transformed_rows={len(report.transformed_rows)}",
        ]
        return ", ".join(parts)


def conforms_to_backend(backend: object) -> bool:
    """True when ``backend`` implements the ProjectionBackend contract."""
    return isinstance(backend, ProjectionBackend)
