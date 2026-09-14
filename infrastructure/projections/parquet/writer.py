"""Deterministic Parquet serialization for the analytical projection.

This module is the only place this backend touches pyarrow. Rows are plain
``dict``s with string / ``None`` / string-list values and canonical UTC-naive
ISO datetime strings; the writer maps them onto the documented column types
and serializes with fixed Parquet options, so identical content always
produces identical bytes (within a pyarrow version). Reading normalizes values
back to the same canonical plain form.
"""

from __future__ import annotations

import io
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from infrastructure.projections.parquet.datasets import (
    is_list_column,
    is_timestamp_column,
)

_WRITE_OPTIONS = {"version": "2.6", "compression": "snappy"}


def parquet_bytes(rows: Sequence[dict[str, object]], columns: tuple[str, ...]) -> bytes:
    """Serialize ``rows`` (with the given columns) to deterministic Parquet bytes."""
    arrays = [_array(rows, column) for column in columns]
    table = pa.table(dict(zip(columns, arrays, strict=False)))
    buffer = io.BytesIO()
    pq.write_table(table, buffer, **_WRITE_OPTIONS)
    return buffer.getvalue()


def table_from_bytes(data: bytes) -> Any:
    """Read a pyarrow Table back from serialized Parquet bytes."""
    return pq.read_table(io.BytesIO(data))


def try_table_from_bytes(data: bytes) -> Any | None:
    """Read a Table back, or ``None`` when ``data`` is not readable Parquet."""
    try:
        return pq.read_table(io.BytesIO(data))
    except Exception:
        return None


def rows_from_bytes(data: bytes) -> tuple[dict[str, object], ...]:
    """Read rows back from serialized Parquet bytes in canonical plain form."""
    table = pq.read_table(io.BytesIO(data))
    rows: list[dict[str, object]] = []
    for record in table.to_pylist():
        row: dict[str, object] = {}
        for column, value in record.items():
            if is_timestamp_column(column) and value is not None:
                value = value.isoformat()
            row[column] = value
        rows.append(row)
    return tuple(rows)


def try_rows_from_bytes(data: bytes) -> tuple[dict[str, object], ...] | None:
    """Read rows back, or ``None`` when ``data`` is not readable Parquet."""
    try:
        return rows_from_bytes(data)
    except Exception:
        return None


def _array(rows: Sequence[dict[str, object]], column: str) -> Any:
    values = [row.get(column) for row in rows]
    if is_list_column(column):
        return pa.array(values, type=pa.list_(pa.string()))
    if is_timestamp_column(column):
        return pa.array([_utc_naive(value) for value in values], type=pa.timestamp("us"))
    return pa.array(values, type=pa.string())


def _utc_naive(value: object | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed
