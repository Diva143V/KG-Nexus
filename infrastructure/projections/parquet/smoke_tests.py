"""Parquet projection smoke tests.

Smoke tests spot-check that the materialized analytical content is usable
where it landed: every expected dataset is present and readable as real
Parquet, its schema matches the profile-defined columns, row counts match the
expected content, and a columnar aggregate query runs successfully (the
"analytics without authority" guarantee — reading and aggregating the files
never changes the authoritative RDF). They are deterministic and do not depend
on the shape of any particular release.
"""

from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, ConfigDict, Field

from infrastructure.projections.parquet.builder import ExpectedParquet
from infrastructure.projections.parquet.datasets import (
    ANALYTICS_GROUP,
    KEY_COLUMNS,
)
from infrastructure.projections.parquet.store import (
    ParquetProjectionStore,
    parquet_candidate_name,
)
from infrastructure.projections.parquet.writer import try_table_from_bytes


class ParquetSmokeTestResult(BaseModel):
    """Outcome of the smoke tests for one analytical projection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    datasets_readable: bool = False
    schema_matches: bool = False
    row_counts_match: bool = False
    analytics_queryable: bool = False
    errors: tuple[str, ...] = Field(default_factory=tuple)

    @property
    def passed(self) -> bool:
        """True when every smoke check succeeded."""
        return (
            self.datasets_readable
            and self.schema_matches
            and self.row_counts_match
            and self.analytics_queryable
            and not self.errors
        )


class ParquetSmokeTestRunner:
    """Runs deterministic smoke tests against the materialized datasets."""

    def __init__(self, *, store: ParquetProjectionStore) -> None:
        self._store = store

    def run(
        self,
        *,
        projection_id: str,
        expected: ExpectedParquet,
    ) -> ParquetSmokeTestResult:
        """Run the smoke tests for the projection under ``projection_id``."""
        store_key = parquet_candidate_name(projection_id)
        if not self._store.has_projection(store_key):
            return ParquetSmokeTestResult(errors=("no candidate projection",))

        datasets_readable = True
        schema_matches = True
        row_counts_match = True
        for name in expected.projection.dataset_names:
            data = self._store.read_dataset(store_key, name)
            if data is None:
                datasets_readable = False
                continue
            table = try_table_from_bytes(data)
            if table is None:
                datasets_readable = False
                continue
            if table.column_names != list(expected.projection.columns[name]):
                schema_matches = False
            if table.num_rows != len(expected.projection.datasets[name]):
                row_counts_match = False

        analytics_queryable = self._aggregate_matches(store_key, expected)

        errors: list[str] = []
        if not datasets_readable:
            errors.append("datasets are not readable")
        if not schema_matches:
            errors.append("dataset schema does not match the profile")
        if not row_counts_match:
            errors.append("dataset row counts do not match the expected content")
        if not analytics_queryable:
            errors.append("analytical aggregation failed")

        return ParquetSmokeTestResult(
            datasets_readable=datasets_readable,
            schema_matches=schema_matches,
            row_counts_match=row_counts_match,
            analytics_queryable=analytics_queryable,
            errors=tuple(errors),
        )

    def _aggregate_matches(self, store_key: str, expected: ExpectedParquet) -> bool:
        name = self._aggregate_dataset(expected)
        if name is None:
            return True
        data = self._store.read_dataset(store_key, name)
        if data is None:
            return False
        table = try_table_from_bytes(data)
        if table is None:
            return False
        group_column = ANALYTICS_GROUP[name]
        key_column = KEY_COLUMNS[name]
        aggregate = table.group_by([group_column]).aggregate([(key_column, "count")])
        aggregate_rows = aggregate.to_pylist()
        count_column = f"{key_column}_count"

        actual: Counter[str] = Counter()
        for record in aggregate_rows:
            group_value = record.get(group_column)
            if group_value is not None:
                actual[str(group_value)] += int(record.get(count_column, 0))

        expected_groups: Counter[str] = Counter()
        for row in expected.projection.datasets.get(name, ()):
            group_value = row.get(group_column)
            if group_value is not None:
                expected_groups[str(group_value)] += 1
        return dict(actual) == dict(expected_groups)

    @staticmethod
    def _aggregate_dataset(expected: ExpectedParquet) -> str | None:
        for name in ("assertions", "relations", "entities", "provenance", "evidence"):
            if name in expected.projection.datasets:
                return name
        return None
