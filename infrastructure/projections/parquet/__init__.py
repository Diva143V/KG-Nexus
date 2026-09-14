"""Parquet analytical projection backend.

A derived analytical materialization of an authoritative RDF release:
deterministic Parquet datasets (entities, relations, assertions, provenance,
evidence) whose exact content is defined by the ``ProjectionProfile``. RDF is
authoritative and remains so — Parquet is a consumer-only view for large-scale
analytics, never a second semantic authority. Core never imports this package;
it reaches the backend through the ``ProjectionRegistry``.
"""

from __future__ import annotations

from infrastructure.projections.parquet.backend import ParquetProjectionBackend
from infrastructure.projections.parquet.builder import (
    ExpectedParquet,
    MemoryParquetDataSource,
    ParquetDataSource,
    ParquetProjection,
    ParquetProjectionBuilder,
)
from infrastructure.projections.parquet.datasets import (
    DATASET_COLUMNS,
    KEY_COLUMNS,
    canonical_row,
)
from infrastructure.projections.parquet.errors import (
    MissingParquetReleaseError,
    ParquetClientError,
    ParquetProjectionError,
    ParquetReconciliationError,
    ParquetSmokeTestError,
    ParquetUnsupportedSemanticsError,
    ParquetValidationError,
    UnknownParquetProjectionError,
)
from infrastructure.projections.parquet.policy import (
    ParquetProjectionPolicy,
    policy_from_profile,
)
from infrastructure.projections.parquet.reconciler import (
    ParquetReconciler,
    ParquetReconciliationReport,
)
from infrastructure.projections.parquet.smoke_tests import (
    ParquetSmokeTestResult,
    ParquetSmokeTestRunner,
)
from infrastructure.projections.parquet.store import (
    MemoryParquetProjectionStore,
    ParquetProjectionStore,
    parquet_candidate_name,
)
from infrastructure.projections.parquet.writer import (
    parquet_bytes,
    rows_from_bytes,
    table_from_bytes,
)

__all__ = [
    "DATASET_COLUMNS",
    "ExpectedParquet",
    "KEY_COLUMNS",
    "MemoryParquetDataSource",
    "MemoryParquetProjectionStore",
    "MissingParquetReleaseError",
    "ParquetClientError",
    "ParquetDataSource",
    "ParquetProjection",
    "ParquetProjectionBackend",
    "ParquetProjectionBuilder",
    "ParquetProjectionError",
    "ParquetProjectionPolicy",
    "ParquetProjectionStore",
    "ParquetReconciler",
    "ParquetReconciliationError",
    "ParquetReconciliationReport",
    "ParquetSmokeTestError",
    "ParquetSmokeTestResult",
    "ParquetSmokeTestRunner",
    "ParquetUnsupportedSemanticsError",
    "ParquetValidationError",
    "UnknownParquetProjectionError",
    "canonical_row",
    "parquet_bytes",
    "parquet_candidate_name",
    "policy_from_profile",
    "rows_from_bytes",
    "table_from_bytes",
]
