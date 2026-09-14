"""Parquet projection reconciliation against the authoritative RDF release.

RDF is authoritative. The reconciler compares the materialized analytical
rows against the policy-derived expected rows and reports, in deterministic
string terms:

* missing / unexpected datasets;
* missing / unexpected rows;
* transformed rows (same row key, different content).

Data loss is never silently accepted: any divergence is reported. Row
comparisons use the canonical plain row form, so Parquet round-trips
(timestamps, lists) never introduce spurious differences.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from core.projection.profile import ProjectionProfile
from infrastructure.projections.parquet.builder import (
    ParquetDataSource,
    ParquetProjectionBuilder,
)
from infrastructure.projections.parquet.datasets import (
    KEY_COLUMNS,
    canonical_row,
)
from infrastructure.projections.parquet.store import (
    ParquetProjectionStore,
    parquet_candidate_name,
)
from infrastructure.projections.parquet.writer import try_rows_from_bytes


class ParquetReconciliationReport(BaseModel):
    """Outcome of reconciling one analytical projection against its release."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    projection_id: str = Field(min_length=1)
    release_id: str = Field(min_length=1)
    missing_datasets: tuple[str, ...] = Field(default_factory=tuple)
    unexpected_datasets: tuple[str, ...] = Field(default_factory=tuple)
    missing_rows: tuple[str, ...] = Field(default_factory=tuple)
    unexpected_rows: tuple[str, ...] = Field(default_factory=tuple)
    transformed_rows: tuple[str, ...] = Field(default_factory=tuple)
    row_counts: dict[str, int] = Field(default_factory=dict)

    @property
    def reconciled(self) -> bool:
        """True when the projection matches the expected analytical content."""
        return not (
            self.missing_datasets
            or self.unexpected_datasets
            or self.missing_rows
            or self.unexpected_rows
            or self.transformed_rows
        )


class ParquetReconciler:
    """Reconciles materialized rows against the authoritative RDF release."""

    def __init__(
        self,
        *,
        store: ParquetProjectionStore,
        data_source: ParquetDataSource,
        builder: ParquetProjectionBuilder | None = None,
    ) -> None:
        self._store = store
        self._data_source = data_source
        self._builder = builder or ParquetProjectionBuilder(
            store=store,
            data_source=data_source,
        )

    def reconcile(
        self,
        *,
        projection_id: str,
        release_id: str,
        profile: ProjectionProfile,
    ) -> ParquetReconciliationReport:
        """Compare the materialized rows against the expected rows."""
        expected = self._builder.derive(release_id, profile)
        store_key = parquet_candidate_name(projection_id)

        expected_names = set(expected.dataset_names)
        actual_names = set(self._store.dataset_names(store_key))
        missing_datasets = sorted(expected_names - actual_names)
        unexpected_datasets = sorted(actual_names - expected_names)

        missing_rows: list[str] = []
        unexpected_rows: list[str] = []
        transformed_rows: list[str] = []
        row_counts: dict[str, int] = {}
        for name in sorted(expected_names | actual_names):
            expected_rows = expected.datasets.get(name, ())
            actual_rows = self._stored_rows(store_key, name)
            row_counts[name] = len(actual_rows)

            expected_by_form = {canonical_row(row) for row in expected_rows}
            actual_by_form = {canonical_row(row) for row in actual_rows}
            missing_rows.extend(
                f"{name}|{entry}" for entry in sorted(expected_by_form - actual_by_form)
            )
            unexpected_rows.extend(
                f"{name}|{entry}" for entry in sorted(actual_by_form - expected_by_form)
            )
            transformed_rows.extend(self._transformed(name, expected_rows, actual_rows))

        return ParquetReconciliationReport(
            projection_id=projection_id,
            release_id=release_id,
            missing_datasets=tuple(missing_datasets),
            unexpected_datasets=tuple(unexpected_datasets),
            missing_rows=tuple(missing_rows),
            unexpected_rows=tuple(unexpected_rows),
            transformed_rows=tuple(sorted(transformed_rows)),
            row_counts=row_counts,
        )

    def _transformed(
        self,
        name: str,
        expected_rows: tuple[dict[str, object], ...],
        actual_rows: tuple[dict[str, object], ...],
    ) -> list[str]:
        key_column = KEY_COLUMNS[name]
        expected_by_key = {self._key(row, key_column): canonical_row(row) for row in expected_rows}
        actual_by_key = {self._key(row, key_column): canonical_row(row) for row in actual_rows}
        transformed: list[str] = []
        for key in sorted(expected_by_key.keys() & actual_by_key.keys()):
            if expected_by_key[key] != actual_by_key[key]:
                transformed.append(f"{name}|{key}")
        return transformed

    def _stored_rows(
        self,
        store_key: str,
        name: str,
    ) -> tuple[dict[str, object], ...]:
        data = self._store.read_dataset(store_key, name)
        if data is None:
            return ()
        rows = try_rows_from_bytes(data)
        if rows is None:
            return ()
        return rows

    @staticmethod
    def _key(row: dict[str, object], key_column: str) -> str:
        return str(row.get(key_column, ""))
