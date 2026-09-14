"""Provenance models and services (lazy re-exports).

Heavy modules that depend on ``core.assertions`` (lineage, activity
recorder, provenance service) are imported lazily so that importing this
package never triggers an import cycle through ``core.assertions``.
"""

from __future__ import annotations

from typing import Any

from core.provenance.errors import (
    IncompleteLineageError,
    ProvenanceError,
    UnresolvedReferenceError,
)
from core.provenance.provenance import AssertionOrigin, Provenance

__all__ = [
    "ActivityRecorder",
    "AssertionOrigin",
    "IncompleteLineageError",
    "Lineage",
    "LineageResolver",
    "Provenance",
    "ProvenanceError",
    "ProvenanceService",
    "UnresolvedReferenceError",
]


def __getattr__(name: str) -> Any:
    if name == "ActivityRecorder":
        from core.provenance.activity_recorder import ActivityRecorder

        return ActivityRecorder
    if name == "ProvenanceService":
        from core.provenance.service import ProvenanceService

        return ProvenanceService
    if name == "Lineage":
        from core.provenance.lineage import Lineage

        return Lineage
    if name == "LineageResolver":
        from core.provenance.lineage import LineageResolver

        return LineageResolver
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
