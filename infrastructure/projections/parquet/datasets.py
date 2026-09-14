"""Analytical dataset definitions for the Parquet projection.

The analytical tables are domain-neutral: no biomedical or other domain
assumptions live here. Each dataset has a fixed, documented column order (the
profile can select a subset of the ``provenance``/``evidence`` columns and
drop whole datasets). All timestamps are stored as UTC-naive microsecond
timestamps; their canonical string form is the UTC-naive ISO 8601 string
without an offset suffix.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum


class ColumnType(StrEnum):
    """Storage type of one analytical column."""

    STRING = "string"
    LIST_STRING = "list<string>"
    TIMESTAMP_US = "timestamp[us]"


#: Full column set of every dataset, in fixed order.
DATASET_COLUMNS: dict[str, tuple[str, ...]] = {
    "entities": ("entity_id", "namespace"),
    "relations": ("assertion_id", "subject", "predicate", "object", "state"),
    "assertions": (
        "assertion_id",
        "kind",
        "subject",
        "predicate",
        "object",
        "value",
        "state",
    ),
    "provenance": (
        "assertion_id",
        "agent",
        "activity",
        "asserted_at",
        "method",
        "input_assertions",
        "input_resources",
    ),
    "evidence": (
        "evidence_id",
        "claim_id",
        "kind",
        "record_id",
        "artifact_id",
        "obtained_at",
    ),
}

#: Key column of each dataset, used for row-level reconciliation.
KEY_COLUMNS: dict[str, str] = {
    "entities": "entity_id",
    "relations": "assertion_id",
    "assertions": "assertion_id",
    "provenance": "assertion_id",
    "evidence": "evidence_id",
}

#: Column used by the analytical smoke-test aggregate, per dataset.
ANALYTICS_GROUP: dict[str, str] = {
    "entities": "namespace",
    "relations": "state",
    "assertions": "state",
    "provenance": "agent",
    "evidence": "kind",
}

_COLUMN_TYPES: dict[str, ColumnType] = {
    "asserted_at": ColumnType.TIMESTAMP_US,
    "obtained_at": ColumnType.TIMESTAMP_US,
    "input_assertions": ColumnType.LIST_STRING,
    "input_resources": ColumnType.LIST_STRING,
}


def column_type(column: str) -> ColumnType:
    """Storage type of one analytical column."""
    return _COLUMN_TYPES.get(column, ColumnType.STRING)


def is_timestamp_column(column: str) -> bool:
    """Whether ``column`` is stored as a UTC-naive timestamp."""
    return column_type(column) is ColumnType.TIMESTAMP_US


def is_list_column(column: str) -> bool:
    """Whether ``column`` is stored as a string list."""
    return column_type(column) is ColumnType.LIST_STRING


def utc_naive_iso(value: str | None) -> str | None:
    """Canonical UTC-naive ISO string for a datetime literal value.

    The authoritative RDF literals are timezone-aware (``...+00:00``); the
    canonical analytical form is the same instant as a UTC-naive string, so
    row comparisons and Parquet round-trips are deterministic.
    """
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed.isoformat()


def canonical_row(row: Mapping[str, object]) -> str:
    """Deterministic string form of one analytical row."""
    return json.dumps(dict(row), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
